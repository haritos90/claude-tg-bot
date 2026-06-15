"""Engine layer: wraps ClaudeSDKClient for a single thread/session.

This is the ONLY module that imports the Agent SDK. It normalizes the raw SDK
message stream into a flat sequence of EngineEvent objects that the Telegram
layer (sessions.py / streamer.py) can consume without any SDK knowledge.

Subscription auth: we never set ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN — the
spawned `claude` CLI uses the logged-in Pro/Max subscription credentials when
no API key is present. We therefore strip those vars from the child env.
"""

import os
import contextlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    StreamEvent,
    RateLimitEvent,
    TextBlock,
    ToolUseBlock,
)

# Short, friendly system prompt for chat (no-tools) mode.
CHAT_SYSTEM_PROMPT = (
    "You are a friendly, helpful assistant. Answer clearly and to the point. "
    "Use Markdown formatting when it helps. "
    "Your replies are shown in a Telegram chat, which CANNOT render LaTeX or math "
    "markup — never use $...$, $$...$$, \\(...\\), \\[...\\], or backslash commands "
    "like \\frac or \\text. Write math in plain Unicode instead "
    "(e.g. ×, ÷, ≈, ≤, ≥, ², ₂, √, π, ½, →, ∞)."
)

# The full universe of tools the model may CALL in code mode (the `tools`
# option). Availability != auto-permission: dangerous tools here are NOT in
# allowed_tools, so the CLI's permission rules evaluate to "ask" and our
# can_use_tool gate (permissions.py) is invoked for each one.
CODE_TOOLS = [
    "Read",
    "Glob",
    "Grep",
    "LS",
    "Bash",
    "Write",
    "Edit",
    "MultiEdit",
    "NotebookRead",
    "NotebookEdit",
    "TodoWrite",
    "WebFetch",
    "WebSearch",
]

# Read-only / non-destructive tools that are auto-allowed WITHOUT a prompt
# (passed as allowed_tools). MUST stay in sync with permissions.SAFE_TOOLS so
# the gate is the single source of truth for what is auto-allowed. Everything
# else in CODE_TOOLS falls through to the can_use_tool approval gate. Critically,
# the dangerous tools (Bash/Write/Edit/MultiEdit/NotebookEdit/WebFetch/WebSearch)
# are deliberately NOT listed here.
CODE_AUTO_ALLOW_TOOLS = [
    "Read",
    "Glob",
    "Grep",
    "LS",
    "NotebookRead",
    "TodoWrite",
]


@dataclass
class EngineEvent:
    """A single normalized event emitted while running a turn.

    kind is one of:
      text_delta  -> .text holds the incremental delta
      text_full   -> .text holds the full accumulated assistant text so far
      tool        -> .tool_name / .tool_input describe a requested tool call
      status      -> .text holds a human-readable status line
      result      -> terminal event with .usage / .cost / .session_id / .text
      rate_limit  -> .rate holds a RateLimitInfo object
      error       -> .text holds a readable (English) error message; .error_key
                     is a stable l10n key and .error_detail an optional argument,
                     so the consumer can render the message in the user's locale.
    """

    kind: str
    text: str = ""
    tool_name: str = ""
    tool_input: dict | None = None
    usage: dict | None = None
    cost: float | None = None
    session_id: str | None = None
    rate: object | None = None
    error_key: str | None = None
    error_detail: str | None = None


# Map the SDK's AssistantMessage.error enum values to readable messages. These
# are the English fallbacks; the localized text lives in the i18n table under the
# matching "err.<type>" key (see _error_key), rendered by the consumer where the
# user's locale is known. Keep this engine module free of the i18n user cache.
_ERROR_MESSAGES = {
    "authentication_failed": (
        "Authentication error. Check your subscription login "
        "(claude setup-token) and that ANTHROPIC_API_KEY is unset."
    ),
    "billing_error": "Billing error. Check your subscription status.",
    "rate_limit": "Rate limit reached. Please try again later.",
    "invalid_request": "Invalid request to the model.",
    "server_error": "Server-side error. Please try again.",
    "unknown": "Unknown model error.",
}

# The l10n key for each known error type (consumed via i18n.t downstream).
_ERROR_KEYS = {
    "authentication_failed": "err.authentication_failed",
    "billing_error": "err.billing_error",
    "rate_limit": "err.rate_limit",
    "invalid_request": "err.invalid_request",
    "server_error": "err.server_error",
    "unknown": "err.unknown_model",
}


def _error_message(error: object) -> str:
    """Translate an AssistantMessage.error value into a readable string."""
    key = str(error) if error is not None else "unknown"
    return _ERROR_MESSAGES.get(key, f"Model error: {key}")


def _error_key(error: object) -> str:
    """The stable l10n key for an AssistantMessage.error value (for the consumer
    to localize). Unmapped types fall back to a generic 'model error' key whose
    text carries the raw type as {detail}."""
    key = str(error) if error is not None else "unknown"
    return _ERROR_KEYS.get(key, "err.model_error")


class ClaudeSession:
    """One SDK session bound to a single Telegram thread.

    The same instance is reused across queued prompts in a thread so the prompt
    cache and conversation context (via resume session_id) are preserved.
    """

    def __init__(
        self,
        mode: str,
        model: str,
        cwd: str | None,
        can_use_tool=None,
        resume_session_id: str | None = None,
        permission_mode: str = "default",
        big_memory: bool = False,
        effort: str | None = None,
        max_turns: int | None = None,
        add_dirs: list[str] | None = None,
        fork: bool = False,
        sandbox: bool = False,
        sandbox_uid: int = 65534,
        sandbox_allow_exec: bool = True,
    ) -> None:
        self.mode = mode
        self.model = model
        self.cwd = cwd
        self.can_use_tool = can_use_tool
        self.permission_mode = permission_mode
        # Big memory: opt-in 1M context window for CHAT mode (code mode already
        # runs with the 1M beta). Set per topic via /memory.
        self.big_memory = big_memory
        # Pro-command per-session options (#23): reasoning effort, agentic turn
        # cap, extra code dirs, and a one-shot fork (resume → branch a new id).
        self.effort = effort
        self.max_turns = max_turns
        self.add_dirs = list(add_dirs) if add_dirs else []
        self.fork = bool(fork)
        # Per-code-session sandbox (#104): when on, code mode launches the CLI via
        # the bubblewrap wrapper (deploy/sandbox-claude.sh) — unprivileged uid,
        # workdir-confined, subscription credential injected read-only.
        self.sandbox = bool(sandbox)
        self.sandbox_uid = int(sandbox_uid)
        self.sandbox_allow_exec = bool(sandbox_allow_exec)
        # session_id is updated from each ResultMessage and passed back as
        # options.resume so a freshly-built client continues the prior session.
        self.session_id: str | None = resume_session_id
        self.client: ClaudeSDKClient | None = None
        # Set by interrupt() so run() can tell a deliberate /stop apart from a
        # real failure: when interrupting, any exception out of receive_response()
        # is an expected end, not an error to surface. Reset at the start of run().
        self._interrupted = False

    def _build_env(self) -> dict[str, str]:
        """Copy the current env and remove API-key vars to force subscription auth."""
        env = dict(os.environ)
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
        return env

    def _sandbox_launcher(self) -> str:
        """Absolute path to the committed bubblewrap launcher (deploy/)."""
        return str(Path(__file__).resolve().parent / "deploy" / "sandbox-claude.sh")

    def _enable_sandbox(self, common: dict) -> None:
        """Route code mode through the bubblewrap launcher (#104): set cli_path and
        the SBX_* env the launcher reads. The launcher ``--clearenv``'s the inner
        CLI (so the bot's env, incl. TELEGRAM_BOT_TOKEN, never reaches sandboxed
        code) and gives it a private tmpfs HOME with the credential injected
        read-only."""
        env = dict(common.get("env") or {})
        env["SBX_UID"] = str(self.sandbox_uid)
        env["SBX_GID"] = str(self.sandbox_uid)
        env["SBX_EXEC"] = "1" if self.sandbox_allow_exec else "0"
        env["SBX_CLAUDE"] = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
        env["SBX_CREDS"] = os.path.expanduser("~/.claude/.credentials.json")
        env["SBX_STATE"] = f"{self.cwd}.sbxstate"  # persistent ~/.claude/projects (#115)
        common["env"] = env
        common["cli_path"] = self._sandbox_launcher()
        # No workdir chown: bwrap's user namespace maps the jail's uid to the
        # OUTER (root) uid for host filesystem ops, so the root-owned workdir is
        # writable inside; confinement comes from the bind mounts (only the workdir
        # is rw-bound — secrets / other sessions / the host are simply not mounted).

    def _build_options(self) -> ClaudeAgentOptions:
        """Construct ClaudeAgentOptions for the current mode/model/cwd."""
        env = self._build_env()

        common: dict = {
            "model": self.model,
            # Isolation: pass [] (NOT None) so the CLI loads NO user/project/local
            # settings and NO CLAUDE.md. In this SDK version None means "load all
            # filesystem sources" — the opposite of what we want.
            "setting_sources": [],
            "include_partial_messages": True,  # enable text-delta streaming
            "env": env,
        }
        if self.session_id:
            common["resume"] = self.session_id
            # One-shot fork: resume the prior session but branch to a NEW id so the
            # original is left untouched. Cleared after the first turn (sessions.py).
            if self.fork:
                common["fork_session"] = True
        # Reasoning effort + agentic turn cap apply to both modes (#23).
        if self.effort:
            common["effort"] = self.effort
        if self.max_turns:
            common["max_turns"] = self.max_turns

        if self.mode == "code":
            if self.sandbox:
                self._enable_sandbox(common)
            return ClaudeAgentOptions(
                cwd=self.cwd,
                permission_mode=self.permission_mode,
                can_use_tool=self.can_use_tool,
                # `tools` = the universe of callable tools; `allowed_tools` =
                # only the read-only auto-allow set. Dangerous tools are usable
                # but not auto-allowed, so the CLI evaluates them as "ask" and
                # our can_use_tool gate fires for each one before execution.
                tools=list(CODE_TOOLS),
                allowed_tools=list(CODE_AUTO_ALLOW_TOOLS),
                add_dirs=list(self.add_dirs),
                betas=["context-1m-2025-08-07"],
                **common,
            )

        # Default / chat mode: a pure conversation with NO tools.
        # `tools=[]` (empty list, NOT None) makes the CLI emit `--tools ""`,
        # which gives the model an EMPTY tool universe. Passing None would leave
        # the CLI's DEFAULT tool set enabled (WebSearch, etc.), so chat mode
        # would not actually be tool-free. allowed_tools=[] then auto-allows
        # nothing on top of that.
        chat_extra: dict = {}
        if self.big_memory:
            # Big-memory topics get the 1M context window in chat too.
            chat_extra["betas"] = ["context-1m-2025-08-07"]
        return ClaudeAgentOptions(
            system_prompt=CHAT_SYSTEM_PROMPT,
            tools=[],
            allowed_tools=[],
            permission_mode="default",
            **chat_extra,
            **common,
        )

    async def _ensure_client(self) -> None:
        """Lazily create and connect the underlying SDK client."""
        if self.client is None:
            # Code mode runs the agent IN self.cwd; the CLI refuses to start if the
            # directory does not exist ("Working directory does not exist"). Create
            # the per-session workdir up front. (Chat mode passes no cwd, so skip.)
            if self.mode == "code" and self.cwd:
                os.makedirs(self.cwd, exist_ok=True)
                if self.sandbox:
                    # Persistent per-session claude state dir for the jail (#115).
                    os.makedirs(f"{self.cwd}.sbxstate", exist_ok=True)
            self.client = ClaudeSDKClient(self._build_options())
            await self.client.connect()

    async def _send_query(self, prompt: str, attachments: list | None) -> None:
        """Send the user turn to the connected client.

        Without attachments we send the plain string (the common path). With
        attachments we send a multimodal user message — one text block (when the
        prompt is non-empty) plus the given Anthropic content blocks (image and/or
        document) — via query()'s async-iterable form. The per-message session_id
        is the SDK's streaming key ("default"); conversation continuity still comes
        from the `resume` option set at connect time, so attachment turns keep the
        thread's context.
        """
        if not attachments:
            await self.client.query(prompt)
            return

        content: list[dict] = []
        if prompt:
            content.append({"type": "text", "text": prompt})
        content.extend(attachments)

        async def _stream():
            yield {
                "type": "user",
                "message": {"role": "user", "content": content},
                "parent_tool_use_id": None,
                "session_id": "default",
            }

        await self.client.query(_stream())

    async def run(self, prompt: str, attachments: list | None = None):
        """Run one turn and yield normalized EngineEvent objects.

        Yields text_delta events as they stream, tool/status/rate_limit events
        as they occur, and finally exactly one result (or error) event.

        attachments, when given, is a list of Anthropic content-block dicts (image
        and/or document blocks) sent alongside the prompt text (multimodal input).
        It works in BOTH chat and code mode — content blocks are model input, not
        tools — so a tool-free chat session can still see pictures and PDFs.
        """
        # Fresh turn: clear any interrupt flag left over from a prior /stop.
        self._interrupted = False
        try:
            await self._ensure_client()
        except Exception as exc:  # connection / spawn failures
            yield EngineEvent(
                kind="error",
                text=f"Failed to start session: {exc}",
                error_key="err.start_failed",
                error_detail=str(exc),
            )
            return

        running_text = ""

        try:
            await self._send_query(prompt, attachments)

            async for msg in self.client.receive_response():
                # --- Incremental text deltas (preferred for live streaming) ---
                if isinstance(msg, StreamEvent):
                    event = msg.event or {}
                    if event.get("type") == "content_block_delta":
                        delta = event.get("delta") or {}
                        piece = delta.get("text")
                        if piece:
                            running_text += piece
                            yield EngineEvent(kind="text_delta", text=piece)
                    continue

                # --- Assistant message: text blocks + tool-use blocks ---
                if isinstance(msg, AssistantMessage):
                    if getattr(msg, "error", None):
                        yield EngineEvent(
                            kind="error",
                            text=_error_message(msg.error),
                            error_key=_error_key(msg.error),
                            error_detail=str(msg.error),
                        )
                        # An errored assistant message is terminal for this turn.
                        return

                    for block in msg.content or []:
                        if isinstance(block, TextBlock):
                            # Provide the full accumulated text as a fallback for
                            # consumers; deltas above are still preferred.
                            text = block.text or ""
                            if text and text not in running_text:
                                running_text += text
                            yield EngineEvent(kind="text_full", text=running_text)
                        elif isinstance(block, ToolUseBlock):
                            yield EngineEvent(
                                kind="tool",
                                tool_name=block.name or "",
                                tool_input=block.input or {},
                            )
                    continue

                # --- Subscription rate-limit notifications ---
                if isinstance(msg, RateLimitEvent):
                    yield EngineEvent(
                        kind="rate_limit",
                        rate=getattr(msg, "rate_limit_info", None),
                    )
                    continue

                # --- Terminal result for the turn ---
                if isinstance(msg, ResultMessage):
                    if getattr(msg, "session_id", None):
                        self.session_id = msg.session_id
                    final_text = msg.result if msg.result is not None else running_text
                    yield EngineEvent(
                        kind="result",
                        text=final_text or "",
                        usage=getattr(msg, "usage", None),
                        cost=getattr(msg, "total_cost_usd", None),
                        session_id=getattr(msg, "session_id", None),
                    )
                    return

                # Any other message type (SystemMessage, UserMessage, etc.) is
                # not surfaced to the Telegram layer; ignore silently.
        except Exception as exc:
            # A requested interrupt (/stop) can surface as an exception out of
            # receive_response(); that is a deliberate end, not a failure, so we
            # return quietly and let the partial text already streamed stand as
            # the final answer (no spurious "Execution error" line).
            if self._interrupted:
                return
            yield EngineEvent(
                kind="error",
                text=f"Execution error: {exc}",
                error_key="err.exec_error",
                error_detail=str(exc),
            )

    async def context_usage(self):
        """Return raw SDK context-window usage, or None if unavailable.

        Exposes ClaudeSDKClient.get_context_usage() for the handler layer.
        The return shape is an SDK object/dict; we return it raw and let
        handlers.py format it defensively (str()/getattr). Any failure (no
        connected client, SDK error) yields None so callers can fall back.
        """
        if self.client is None:
            return None
        try:
            return await self.client.get_context_usage()
        except Exception:
            return None

    async def interrupt(self) -> None:
        """Cancel the in-flight turn, if any (used by /stop).

        Sets _interrupted first so run() treats any exception the interrupt
        raises inside receive_response() as a clean, deliberate end rather than
        an error to surface (the already-streamed partial text stands as final).
        """
        self._interrupted = True
        if self.client:
            with contextlib.suppress(Exception):
                await self.client.interrupt()

    async def aclose(self) -> None:
        """Disconnect and drop the underlying client."""
        if self.client:
            with contextlib.suppress(Exception):
                await self.client.disconnect()
            self.client = None

    def set_model(self, model: str) -> None:
        """Update the model, applied on the next client build.

        We deliberately do NOT fire a detached client.set_model() task here: a
        bare create_task() can be garbage-collected before completion and would
        race an in-flight turn on the live client. Model changes go through the
        rebuild path (SessionManager.on_mode_or_model_or_cwd_change), which
        aclose()s the old client and builds a new one with the new model.
        """
        self.model = model
