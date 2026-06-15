"""Engine layer: wraps ClaudeSDKClient for a single thread/session.

This is the ONLY module that imports the Agent SDK. It normalizes the raw SDK
message stream into a flat sequence of EngineEvent objects that the Telegram
layer (sessions.py / streamer.py) can consume without any SDK knowledge.

Subscription auth: we never set ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN — the
spawned `claude` CLI uses the logged-in Pro/Max subscription credentials when
no API key is present. We therefore strip those vars from the child env.
"""

import os
import re
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

# Short, friendly system prompt for chat mode. Chat now ships the read-only web
# research tools (see _build_options), so the prompt tells the model it CAN browse
# — otherwise it falls back to "I have no internet access" out of habit.
CHAT_SYSTEM_PROMPT = (
    "You are a friendly, helpful assistant. Answer clearly and to the point. "
    "Use Markdown formatting when it helps. "
    "You have live web access: use the WebSearch tool to find current information "
    "and the WebFetch tool to read specific pages whenever the user asks about "
    "recent events, current docs, prices, news, or any fact worth verifying. "
    "Never claim you lack internet access or cannot browse — you can. "
    "This is a CHAT session: you have web tools but NO terminal, file access, or code "
    "execution. If the user wants to run commands, execute code, or read/write files, "
    "tell them this session can be upgraded to a code session with the /code command — "
    "do NOT attempt those actions yourself. "
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

# The chat-mode tool universe: the READ-ONLY web research tools (chat has no cwd,
# so no Bash/file tools). These make chat behave like the Claude apps. The Tools
# settings page (#129) toggles which of these are enabled per session; the default
# (tools_enabled=None) is "all of them on".
CHAT_TOOLS = [
    "WebSearch",
    "WebFetch",
]


# Prompt keyword triggers the bundled CLI honours on the user's MESSAGE TEXT (not
# just the interactive REPL), so they fire on the SDK path too: "ultrathink"
# escalates reasoning effort for the turn (ultrathink_effort), and "ultracode" opts
# the turn into multi-agent Workflow orchestration. Either lets a user silently
# bypass the bot's per-user effort gate and burn the owner's ONE shared
# subscription, so we DEFUSE them in the prompt by SPLITTING the word with a space:
# that breaks the CLI's \bword\b match WITHOUT blocking or removing the message — it
# still goes through, the keyword is just inert. Effort is controlled
# only via /effort (gated); Workflows are ALSO disabled outright in the child env
# (CLAUDE_CODE_DISABLE_WORKFLOWS) — belt and suspenders.
#
# These are the built-in DEFAULTS — not hardcoded inline. A deployer can neutralize
# MORE keywords (without touching code) via the BLOCKED_PROMPT_KEYWORDS env var
# (config.extra_blocked_keywords), which is appended to this list. See the README.
DEFAULT_KEYWORD_TRIGGERS: tuple[str, ...] = ("ultrathink", "ultracode")

def build_trigger_re(keywords):
    """Compile a case-insensitive word-boundary alternation over `keywords`, or
    return None when the list is empty (nothing to defuse)."""
    parts = [re.escape(k.strip()) for k in (keywords or []) if k and str(k).strip()]
    if not parts:
        return None
    return re.compile(r"\b(" + "|".join(parts) + r")\b", re.IGNORECASE)


def defuse_triggers(text: str, trigger_re) -> str:
    """Split each matched trigger word with a space so the bundled CLI can't act on
    it (see DEFAULT_KEYWORD_TRIGGERS). Non-destructive — the message still goes
    through and the word stays readable; it just no longer matches the CLI's
    whole-word keyword. No-op without a regex or text."""
    if not trigger_re or not text:
        return text

    def _space(m):
        w = m.group(0)
        mid = len(w) // 2 or 1
        return w[:mid] + " " + w[mid:]

    return trigger_re.sub(_space, text)


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
        tools_enabled: list[str] | None = None,
        tool_cap: list[str] | None = None,
        global_memory: bool = False,
        extra_blocked_keywords: list[str] | None = None,
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
        # Per-session ENABLED TOOLS (the Tools settings page, #129). None = the mode's
        # full default universe (chat → CHAT_TOOLS web research tools; code →
        # CODE_TOOLS); a list = exactly those, intersected with the universe in
        # _resolve_tools. Supersedes the earlier web_search bool — chat is web-capable
        # by default (relaxes the old "chat is tool-free" rule #24) and the page can
        # turn any tool off; code mode's dangerous tools still hit the approval gate.
        self.tools_enabled = list(tools_enabled) if tools_enabled is not None else None
        # Per-USER tool cap (owner-set, #131): the tools this session's OWNER is
        # allowed to use at all. None = uncapped. _resolve_tools intersects the
        # session's enabled set with this, so the owner can restrict a shared user's
        # tools regardless of what that user toggles per session.
        self.tool_cap = list(tool_cap) if tool_cap is not None else None
        # Per-user GLOBAL MEMORY (owner-granted opt-out of isolation): when on, this
        # session loads setting_sources=["user"] (~/.claude settings + the user
        # CLAUDE.md / memory) instead of []. Relaxes the per-session isolation
        # invariant for that user only; OFF by default.
        self.global_memory = bool(global_memory)
        # Prompt keyword triggers to neutralize: the built-in DEFAULT_KEYWORD_TRIGGERS
        # plus any deployer extras (BLOCKED_PROMPT_KEYWORDS). Compiled once per session.
        self._trigger_re = build_trigger_re(
            list(DEFAULT_KEYWORD_TRIGGERS) + list(extra_blocked_keywords or [])
        )
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
        """Copy the current env, strip API-key vars (force subscription auth), and
        disable the harness Workflows feature.

        CLAUDE_CODE_DISABLE_WORKFLOWS=1 turns off multi-agent orchestration and its
        "ultracode" prompt-keyword trigger at the source: the bundled CLI otherwise
        lets ANY user opt a turn into multi-agent Workflow orchestration just by
        typing "ultracode" — a token bomb on the owner's ONE shared subscription.
        The bot is an Agent-SDK frontend and never wants that tool. (The keyword is
        also defused in the prompt itself; see defuse_triggers.)"""
        env = dict(os.environ)
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
        env["CLAUDE_CODE_DISABLE_WORKFLOWS"] = "1"
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

    def _resolve_tools(self, universe: list[str]) -> list[str]:
        """The enabled subset of a mode's tool universe for this session. None (the
        default) = the whole universe; a stored list = only the tools the session has
        switched on (intersection, so a stale/foreign name can never widen the set).
        The Tools settings page (#129) edits the stored list."""
        if self.tools_enabled is None:
            result = list(universe)
        else:
            enabled = set(self.tools_enabled)
            result = [t for t in universe if t in enabled]
        # Per-user owner cap (#131): never widen beyond what the owner allows. A
        # capped user's session can enable only tools in BOTH its toggles and the cap.
        if self.tool_cap is not None:
            cap = set(self.tool_cap)
            result = [t for t in result if t in cap]
        return result

    def _build_options(self) -> ClaudeAgentOptions:
        """Construct ClaudeAgentOptions for the current mode/model/cwd."""
        env = self._build_env()

        common: dict = {
            "model": self.model,
            # Isolation: pass [] (NOT None) so the CLI loads NO user/project/local
            # settings and NO CLAUDE.md. In this SDK version None means "load all
            # filesystem sources" — the opposite of what we want. When the owner
            # grants a user GLOBAL MEMORY, load the "user" source instead so the
            # owner's ~/.claude (CLAUDE.md / memory) is in scope — a deliberate,
            # per-user relaxation of the isolation invariant.
            #
            # BLAST RADIUS (#130, audit): "user" also loads ~/.claude/settings.json,
            # whose permissions.allow rules can AUTO-allow tools the bot keeps out of
            # allowed_tools (bypassing the can_use_tool gate) and whose env can be
            # merged into the child (a settings ANTHROPIC_API_KEY would survive the
            # _build_env pop and flip billing). Owner-gated + off by default, and the
            # owner's settings.json has none today — but the proper fix (inject
            # CLAUDE.md directly instead of widening setting_sources) is #130. Until
            # then, only grant to fully-trusted users; the card warns.
            "setting_sources": ["user"] if self.global_memory else [],
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
            code_tools = self._resolve_tools(CODE_TOOLS)
            code_extra: dict = {}
            if self.big_memory:
                # #133: big_memory is the unified 1M-context toggle for BOTH modes now
                # (chat applies it below) — was unconditional for code. NOTE #134: the
                # beta is IGNORED under the OAuth subscription, so this is currently a
                # no-op; kept so it's correct if/when subscription betas are allowed.
                code_extra["betas"] = ["context-1m-2025-08-07"]
            return ClaudeAgentOptions(
                cwd=self.cwd,
                permission_mode=self.permission_mode,
                can_use_tool=self.can_use_tool,
                # `tools` = the (per-session enabled) callable universe; `allowed_tools`
                # = only the read-only auto-allow subset of those. Dangerous enabled
                # tools are usable but not auto-allowed, so the CLI evaluates them as
                # "ask" and our can_use_tool gate fires for each before execution.
                tools=code_tools,
                allowed_tools=[t for t in code_tools if t in CODE_AUTO_ALLOW_TOOLS],
                add_dirs=list(self.add_dirs),
                **code_extra,
                **common,
            )

        # Chat mode: a conversation that ships ONLY the read-only web research
        # tools (WebSearch / WebFetch) so it can look up current info like
        # claude.ai — no Bash, no file edits. `tools` is the EXACT universe the
        # model may call: an explicit list (NOT None — None would let the CLI
        # enable its full default toolset; [] would make it tool-free). The same
        # tools go in `allowed_tools` so they are AUTO-allowed (no approval UI —
        # chat has no can_use_tool gate, matching the app). A stored
        # tools_enabled=[] (via the Tools page) makes a truly tool-free chat.
        chat_tools = self._resolve_tools(CHAT_TOOLS)
        chat_extra: dict = {}
        if self.big_memory:
            # Big-memory topics get the 1M context window in chat too.
            chat_extra["betas"] = ["context-1m-2025-08-07"]
        return ClaudeAgentOptions(
            system_prompt=CHAT_SYSTEM_PROMPT,
            # Chat now runs in the per-session workdir too (#133), so its conversation
            # transcript lives in the SAME project as code mode — that's what lets a
            # session upgrade chat→code (or back) and keep one continuous conversation.
            # Chat has no file tools, so the cwd is only transcript storage here.
            cwd=self.cwd,
            tools=list(chat_tools),
            allowed_tools=list(chat_tools),
            permission_mode="default",
            **chat_extra,
            **common,
        )

    async def _ensure_client(self) -> None:
        """Lazily create and connect the underlying SDK client."""
        if self.client is None:
            # Both modes run the agent IN self.cwd (chat too, #133 — that's where the
            # conversation transcript lives, so chat↔code resume the SAME session). The
            # CLI refuses to start if the directory does not exist, so create it up front.
            if self.cwd:
                os.makedirs(self.cwd, exist_ok=True)
                if self.mode == "code" and self.sandbox:
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
        # Defuse harness keyword triggers (ultrathink / ultracode / deployer extras)
        # so a user's message can't silently escalate effort or spin up multi-agent
        # orchestration. The DB transcript logs the ORIGINAL text (done upstream in
        # sessions.py); only the CLI-bound copy is defused.
        prompt = defuse_triggers(prompt, self._trigger_re)
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
