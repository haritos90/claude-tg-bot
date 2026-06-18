"""Permission gate for code mode.

Dangerous tools require an inline button tap from the owner before the
Agent SDK is allowed to proceed. Safe, read-only tools are auto-allowed.

All Telegram interaction here is intentionally minimal: the gate sends an
approval prompt with two inline buttons and awaits an asyncio.Future that
is resolved by handle_decision() when the owner taps a button.
"""

import asyncio
import contextlib
import os

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import i18n


# Read-only / non-destructive tools: never need owner approval.
SAFE_TOOLS: set[str] = {
    "Read",
    "Glob",
    "Grep",
    "LS",
    "NotebookRead",
    "TodoWrite",
}

# File-editing tools, auto-allowed under the "acceptEdits" policy (but not Bash,
# WebFetch, etc., which still prompt). "bypassPermissions" allows EVERYTHING.
EDIT_TOOLS: set[str] = {"Write", "Edit", "MultiEdit", "NotebookEdit"}

# How long we wait for the owner to decide before auto-denying.
DEFAULT_TIMEOUT = 300.0

# Max chars shown for a tool-input preview in the approval message.
_PREVIEW_LIMIT = 500


def _truncate(value: str, limit: int = _PREVIEW_LIMIT) -> str:
    """Trim a string to `limit` chars, appending an ellipsis if cut."""
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def _rel_to_cwd(path: str, cwd: str | None) -> str:
    """#204: render an in-workdir absolute path relative to the session's working
    directory, so an approval prompt shows ``readme.md`` instead of the full
    ``/var/lib/.../<sid>/work/readme.md``. A path OUTSIDE the workdir keeps its
    absolute form on purpose — a tool reaching out of the sandbox should stand out."""
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
    """Build a compact, human-readable preview of the tool input."""
    if not tool_input:
        return ""

    # Pick the most relevant field per tool for a concise preview.
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
                val = _rel_to_cwd(val, cwd)  # #204: show paths relative to the workdir
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
    """Minimal HTML escaping for Telegram parse_mode=HTML messages."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


class PermissionGate:
    """Owner-driven approval for dangerous tools in code mode."""

    def __init__(self, bot):
        self.bot = bot
        # Maps the short request id -> the Future awaited by the SDK callback.
        self._pending: dict[str, asyncio.Future] = {}
        # Maps request id -> (chat_id, message_id) of the prompt message,
        # used to edit it after a decision.
        self._messages: dict[str, tuple[int, int]] = {}
        # Maps request id -> the thread key it belongs to, so /stop can target
        # and deny every pending prompt for a specific thread.
        self._threads: dict[str, int | None] = {}
        # Monotonic counter for request ids (short -> fits callback_data <64B).
        self._counter: int = 0

    def _next_id(self) -> str:
        self._counter += 1
        return str(self._counter)

    @staticmethod
    def _kwargs(thread_id: int | None) -> dict:
        """message_thread_id only when this is not the General topic."""
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
        """Return a can_use_tool coroutine bound to a chat/session.

        send_thread_id is the Telegram message_thread_id to post the prompt into
        (None for a DM or General). key is the UNIQUE session key used for
        bookkeeping + cancellation — distinct per session even when two sessions
        share send_thread_id=None (a DM and General), so cancel_thread() never
        cancels the wrong session's prompts.

        permission_mode is the session's approval policy and decides what auto-runs
        WITHOUT a tap (the SDK invokes this callback for every non-auto-allowed
        tool, so the policy must be enforced HERE, not only in the SDK options):
          - "bypassPermissions" (full-access / auto mode) → allow everything, no prompts;
          - "acceptEdits"                          → also auto-allow file edits;
          - anything else                          → prompt for non-safe tools.

        Signature matches the SDK: (tool_name, tool_input, ctx) ->
        PermissionResultAllow | PermissionResultDeny.
        """

        async def can_use_tool(tool_name: str, tool_input: dict, ctx):
            # Safe, read-only tools never prompt.
            if tool_name in SAFE_TOOLS:
                return PermissionResultAllow()
            # Auto mode (full-access): run everything without asking.
            if permission_mode == "bypassPermissions":
                return PermissionResultAllow()
            # acceptEdits: file edits run without asking; the rest still prompt.
            if permission_mode == "acceptEdits" and tool_name in EDIT_TOOLS:
                return PermissionResultAllow()

            # Localize to the owner's interface language (DM chat_id == user id;
            # the prompt is always answered by the owner).
            lang = i18n.cached_lang(chat_id)

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
            lines.append(i18n.t("permgate.run_q", lang))
            prompt_text = "\n".join(lines)

            # Send the approval prompt. If sending fails, deny safely.
            try:
                sent = await self.bot.send_message(
                    chat_id,
                    prompt_text,
                    parse_mode="HTML",
                    reply_markup=keyboard,
                    **self._kwargs(send_thread_id),
                )
                self._messages[request_id] = (chat_id, sent.message_id)
            except Exception as exc:
                self._pending.pop(request_id, None)
                self._threads.pop(request_id, None)
                return PermissionResultDeny(
                    message=f"Failed to request approval: {exc}",
                    interrupt=False,
                )

            # Wait for the owner's decision (or time out).
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
                # The owning worker was cancelled (e.g. /stop) while we awaited
                # the tap. Clean up our state and update the message so no
                # orphaned entry or live button is left behind, then re-raise.
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
        """Clean up state for a finished request and update its message.

        note_key is an l10n key; the message is rendered in the owner's locale
        (resolved from the prompt's chat id).
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
        """Deny every pending permission prompt belonging to one session `key`.

        Called from SessionManager.stop()/reset() so a /stop that lands while a
        permission prompt is open resolves the awaiting SDK Future (deny),
        updates the inline message, and clears the gate's bookkeeping. Keyed by
        the UNIQUE session key (not the shared send_thread_id), so it never
        cancels a different session's prompts.
        """
        # Snapshot the matching ids first (we mutate the maps while iterating).
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
        """Resolve a pending permission request from an inline-button tap."""
        user = getattr(callback_query, "from_user", None)
        lang = i18n.cached_lang(getattr(user, "id", 0) or 0)
        data = callback_query.data or ""
        parts = data.split(":")
        # Expected: ["perm", "<id>", "allow"|"deny"]
        if len(parts) != 3 or parts[0] != "perm":
            with contextlib.suppress(Exception):
                await callback_query.answer(i18n.t("permgate.invalid", lang))
            return

        request_id, decision = parts[1], parts[2]
        future = self._pending.get(request_id)

        if future is None or future.done():
            # Unknown or already-resolved/expired request.
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

        # Update the original prompt message to reflect the decision.
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
