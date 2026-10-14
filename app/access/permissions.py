"""Permission gate for code mode.

- Dangerous tools need an owner inline-button tap
- Safe read-only tools are auto-allowed
- Prompt is a Future resolved by `handle_decision()`
"""

import asyncio
import contextlib
import os
import re

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from app import i18n


# Read-only, non-destructive tools never need approval.
SAFE_TOOLS: set[str] = {
    "Read",
    "Glob",
    "Grep",
    "LS",
    "NotebookRead",
    "TodoWrite",
    # Session-memory tool writes only this topic's notes; never prompts.
    # - Name mirrors `engine.MEMORY_TOOL`
    "mcp__memory__remember",
}

# File-editing tools, auto-allowed under `acceptEdits`.
# - Plain Bash is too, unless `_bash_needs_approval` flags it
# - WebFetch/WebSearch/Task still prompt; `bypassPermissions` allows everything
EDIT_TOOLS: set[str] = {"Write", "Edit", "MultiEdit", "NotebookEdit"}

# Bash risk classifier for the relaxed `acceptEdits` default.
# - The jail is the hard containment layer
# - Gate catches only push-class and destructive commands
# - Patterns match anywhere in the line; fail toward prompting
# - Obfuscation can slip past; the sandbox backstops it
# - Secret-using commands are not gated; egress gates leaks
_BASH_APPROVAL_PATTERNS: tuple[re.Pattern, ...] = (
    # Push-class or outbound commands carrying user credentials.
    re.compile(r"\bgit\s+push\b"),
    re.compile(r"\bgh\b"),                        # GitHub CLI, uses the PAT
    re.compile(r"\b(?:npm|yarn|pnpm)\s+publish\b"),
    re.compile(r"\btwine\s+upload\b"),
    re.compile(r"\bdocker\s+push\b"),
    re.compile(r"\b(?:ssh|scp|sftp)\b"),          # Remote shell and copy
    re.compile(r"\brsync\b.*(?:::|\S+@|rsync://|\s[\w.-]+:)"),  # Remote rsync only; local is fine
    # Destructive: irreversible loss of in-workdir work.
    re.compile(r"\brm\s+(?:-\w*[rR]|--recursive)"),   # Recursive remove, any flag spelling
    re.compile(r"\bgit\s+reset\s+--hard\b"),
    re.compile(r"\bgit\s+clean\s+(?:-\w*[fd]|--force)"),
    re.compile(r"\bgit\s+restore\b"),
    re.compile(r"\bgit\s+checkout\s+\."),                       # Discard all: `git checkout .`
    re.compile(r"\bgit\s+checkout\b[^&|;\n]*\s--(?:\s|$)"),     # Discard a pathspec, even after a ref
    re.compile(r"\b(?:dd|mkfs\w*|shred|truncate)\b"),
)


def _bash_needs_approval(command: str | None) -> bool:
    """True if Bash should still prompt under `acceptEdits`.

    - Push-class, outbound-with-credentials, or destructive commands
    - Empty or `None` returns False
    """
    if not command or not command.strip():
        return False
    return any(p.search(command) for p in _BASH_APPROVAL_PATTERNS)


# How long to wait for the owner before auto-denying.
DEFAULT_TIMEOUT = 300.0

# Max chars of tool input shown in the prompt.
_PREVIEW_LIMIT = 500


def _truncate(value: str, limit: int = _PREVIEW_LIMIT) -> str:
    """Trim a string to `limit` chars with an ellipsis."""
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def _rel_to_cwd(path: str, cwd: str | None) -> str:
    """Render an in-workdir path relative to the working directory.

    - Paths outside the workdir stay absolute, to stand out
    """
    if not cwd or not os.path.isabs(path):
        return path
    try:
        acwd = os.path.abspath(cwd)
        ap = os.path.abspath(path)
        if ap == acwd or ap.startswith(acwd + os.sep):
            return os.path.relpath(ap, acwd)
    except Exception:
        pass
    return path


def _preview_input(tool_name: str, tool_input: dict | None, cwd: str | None = None) -> str:
    """Build a compact, human-readable preview of tool input."""
    if not tool_input:
        return ""

    # Pick the most relevant field per tool.
    name = (tool_name or "").lower()
    candidate_keys: tuple[str, ...]
    if name == "bash":
        candidate_keys = ("command",)
    elif name in ("write", "edit", "multiedit", "notebookedit"):
        candidate_keys = ("file_path", "notebook_path", "path")
    elif name in ("webfetch", "websearch"):
        candidate_keys = ("url", "query", "prompt")
    elif name == "task":
        candidate_keys = ("description", "prompt")
    else:
        candidate_keys = ("command", "file_path", "path", "url", "query")

    for key in candidate_keys:
        val = tool_input.get(key)
        if isinstance(val, str) and val.strip():
            if key in ("file_path", "notebook_path", "path"):
                val = _rel_to_cwd(val, cwd)  # Show paths relative to workdir
            return _truncate(val)

    # Fallback: a short rendering of the whole dict.
    try:
        rendered = ", ".join(
            f"{k}={v!r}" for k, v in tool_input.items()
        )
    except Exception:
        rendered = str(tool_input)
    return _truncate(rendered)


def _escape(text: str) -> str:
    """Minimal HTML escaping for Telegram HTML parse mode."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


class PermissionGate:
    """Owner-driven approval for dangerous tools in code mode."""

    def __init__(self, bot, owner_id: int | None = None):
        self.bot = bot
        # Approval prompts go to the owner's chat.
        # - Only the owner may approve
        # - Non-owner sessions post there with the requester's id
        self.owner_id = owner_id
        # Request id maps to the Future the SDK awaits.
        self._pending: dict[str, asyncio.Future] = {}
        # Request id maps to `(chat_id, message_id)` of the prompt.
        # - Used to edit the prompt after a decision
        self._messages: dict[str, tuple[int, int]] = {}
        # Request id maps to its thread key.
        # - Lets stop deny every pending prompt for a thread
        self._threads: dict[str, int | None] = {}
        # Monotonic request id counter; short for 64-byte callback data.
        self._counter: int = 0

    def _next_id(self) -> str:
        self._counter += 1
        return str(self._counter)

    @staticmethod
    def _kwargs(thread_id: int | None) -> dict:
        """`message_thread_id` only when not the General topic."""
        if thread_id is None:
            return {}
        return {"message_thread_id": thread_id}

    def make_callback(
        self,
        chat_id: int,
        send_thread_id: int | None,
        key: int,
        permission_mode: str = "default",
        cwd: str | None = None,
    ):
        """Return a `can_use_tool` coroutine bound to a session.

        - `send_thread_id` is where prompts post (`None` for DM/General)
        - `key` is unique per session, so cancels never cross sessions
        - `permission_mode` is enforced here, not only in SDK options
        - `bypassPermissions` allows all; `acceptEdits` allows edits and in-jail Bash
        - Any other mode prompts for every non-safe tool
        """

        async def can_use_tool(tool_name: str, tool_input: dict, ctx):
            # Safe, read-only tools never prompt.
            if tool_name in SAFE_TOOLS:
                return PermissionResultAllow()
            # Auto mode: run everything without asking.
            if permission_mode == "bypassPermissions":
                return PermissionResultAllow()
            # `acceptEdits`: edits and in-jail Bash run without asking.
            # - Outbound/destructive Bash, WebFetch, WebSearch, Task still prompt
            # - The jail is the hard containment layer
            if permission_mode == "acceptEdits":
                if tool_name in EDIT_TOOLS:
                    return PermissionResultAllow()
                if tool_name == "Bash" and not _bash_needs_approval(
                    (tool_input or {}).get("command")
                ):
                    return PermissionResultAllow()

            # The owner answers prompts; post where the owner is.
            target_chat = chat_id
            target_thread = send_thread_id
            if self.owner_id is not None and chat_id != self.owner_id:
                target_chat = self.owner_id
                target_thread = None
            # Localize to the owner's interface language.
            lang = i18n.cached_lang(target_chat)

            request_id = self._next_id()
            loop = asyncio.get_running_loop()
            future: asyncio.Future = loop.create_future()
            self._pending[request_id] = future
            self._threads[request_id] = key

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=i18n.t("permgate.allow_btn", lang),
                            callback_data=f"perm:{request_id}:allow",
                        ),
                        InlineKeyboardButton(
                            text=i18n.t("permgate.deny_btn", lang),
                            callback_data=f"perm:{request_id}:deny",
                        ),
                    ]
                ]
            )

            preview = _preview_input(tool_name, tool_input, cwd)
            lines = [
                i18n.t("permgate.request", lang, tool=_escape(tool_name)),
            ]
            if preview:
                lines.append(f"<pre>{_escape(preview)}</pre>")
            if target_chat != chat_id:   # Say whose session is asking
                lines.append(i18n.t("permgate.for_user", lang, uid=chat_id))
            lines.append(i18n.t("permgate.run_q", lang))
            prompt_text = "\n".join(lines)

            # Send the approval prompt; deny safely on failure.
            try:
                sent = await self.bot.send_message(
                    target_chat,
                    prompt_text,
                    parse_mode="HTML",
                    reply_markup=keyboard,
                    **self._kwargs(target_thread),
                )
                self._messages[request_id] = (target_chat, sent.message_id)
            except Exception as exc:
                self._pending.pop(request_id, None)
                self._threads.pop(request_id, None)
                return PermissionResultDeny(
                    message=f"Failed to request approval: {exc}",
                    interrupt=False,
                )

            # Wait for the owner's decision, or time out.
            try:
                result = await asyncio.wait_for(future, timeout=DEFAULT_TIMEOUT)
                return result
            except asyncio.TimeoutError:
                await self._expire(request_id, "permgate.timed_out")
                return PermissionResultDeny(
                    message="Approval timed out",
                    interrupt=False,
                )
            except asyncio.CancelledError:
                # Worker cancelled (e.g. /stop) while awaiting the tap.
                # - Clean up state and update the message
                # - Leave no orphaned entry or live button, then re-raise
                await self._expire(request_id, "permgate.cancelled")
                raise
            finally:
                self._pending.pop(request_id, None)
                self._threads.pop(request_id, None)

        return can_use_tool

    async def _expire(
        self,
        request_id: str,
        note_key: str = "permgate.timed_out",
    ) -> None:
        """Clean up a finished request and update its message.

        - `note_key` is an l10n key, rendered in the owner's locale
        """
        self._pending.pop(request_id, None)
        self._threads.pop(request_id, None)
        msg = self._messages.pop(request_id, None)
        if msg is None:
            return
        chat_id, message_id = msg
        with contextlib.suppress(Exception):
            await self.bot.edit_message_text(
                i18n.t(note_key, i18n.cached_lang(chat_id)),
                chat_id=chat_id,
                message_id=message_id,
            )

    async def cancel_thread(self, key: int) -> None:
        """Deny every pending permission prompt for one session `key`.

        - Called on stop/reset so awaiting futures resolve
        - Keyed by unique session key, never the shared thread id
        """
        # Snapshot matching ids first; the maps mutate during iteration.
        ids = [rid for rid, k in self._threads.items() if k == key]
        for request_id in ids:
            future = self._pending.get(request_id)
            if future is not None and not future.done():
                with contextlib.suppress(Exception):
                    future.set_result(
                        PermissionResultDeny(message="Stopped by owner")
                    )
            await self._expire(request_id, "permgate.cancelled")

    async def handle_decision(self, callback_query) -> None:
        """Resolve a pending permission request from a button tap."""
        user = getattr(callback_query, "from_user", None)
        lang = i18n.cached_lang(getattr(user, "id", 0) or 0)
        data = callback_query.data or ""
        parts = data.split(":")
        # Expected callback data: `perm`, request id, allow or deny.
        if len(parts) != 3 or parts[0] != "perm":
            with contextlib.suppress(Exception):
                await callback_query.answer(i18n.t("permgate.invalid", lang))
            return

        request_id, decision = parts[1], parts[2]
        future = self._pending.get(request_id)

        if future is None or future.done():
            # Unknown, already-resolved, or expired request.
            with contextlib.suppress(Exception):
                await callback_query.answer(i18n.t("permgate.expired", lang))
            self._messages.pop(request_id, None)
            self._threads.pop(request_id, None)
            return

        if decision == "allow":
            result = PermissionResultAllow()
            verdict_text = i18n.t("permgate.allowed_msg", lang)
            toast = i18n.t("permgate.allowed_toast", lang)
        else:
            result = PermissionResultDeny(message="Denied by owner")
            verdict_text = i18n.t("permgate.denied_msg", lang)
            toast = i18n.t("permgate.denied_toast", lang)

        # Resolve the awaiting SDK callback.
        if not future.done():
            future.set_result(result)
        self._pending.pop(request_id, None)
        self._threads.pop(request_id, None)

        # Update the prompt message to reflect the decision.
        msg = self._messages.pop(request_id, None)
        if msg is not None:
            chat_id, message_id = msg
            with contextlib.suppress(Exception):
                await self.bot.edit_message_text(
                    verdict_text,
                    chat_id=chat_id,
                    message_id=message_id,
                )

        with contextlib.suppress(Exception):
            await callback_query.answer(toast)
