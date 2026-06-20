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
import asyncio
import logging
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

logger = logging.getLogger(__name__)

# #137: signatures used to classify a failed-startup / failed-turn from the CLI's
# real stderr (captured via the ClaudeAgentOptions.stderr callback). Conservative
# phrasing only, so we never mis-flag an unrelated error.
_RESUME_LOST_RE = re.compile(r"No conversation found with session ID", re.I)
_LIMIT_RE = re.compile(
    r"usage limit|rate.?limit|reached your (usage )?limit|"
    r"5-?hour limit|7-?day limit|limit (?:will )?reset|resets? at",
    re.I,
)


def _classify_stderr(text: str) -> str | None:
    """Map captured CLI stderr to a known failure class, or None if unrecognized.

    'resume_lost' -> a stale --resume id (recoverable: retry without resume).
    'rate_limit'  -> the subscription window is exhausted (NOT recoverable here).
    """
    if not text:
        return None
    if _RESUME_LOST_RE.search(text):
        return "resume_lost"
    if _LIMIT_RE.search(text):
        return "rate_limit"
    return None


# #134: request the 1M-token context window via the [1m] model-id SUFFIX, NOT the
# `betas` param. Under the OAuth subscription `betas` are IGNORED ("Custom betas are
# only available for API key users. Ignoring provided betas."), but the suffix works
# and stays subscription-billed. Empirically (this subscription, 2026-06-16):
#   • Opus   + [1m] → OK, auto-included, no usage credits, service_tier "standard".
#   • Sonnet + [1m] → "API Error: Usage credits required for 1M context" (PAID; off here).
#   • Haiku         → no 1M variant at all.
# So [1m] is applied ONLY to models that get 1M WITHOUT paid credits — Opus by default.
# A deployer who has enabled usage credits (claude.ai/settings/usage) can widen the set
# via env BIG_MEMORY_1M_MODELS (comma-separated model-id substrings, e.g. "opus,sonnet").
_ONE_M_SUFFIX = "[1m]"
_ONE_M_MODELS = tuple(
    s.strip().lower()
    for s in os.environ.get("BIG_MEMORY_1M_MODELS", "opus").split(",")
    if s.strip()
)


def _one_m_model(model: str) -> str:
    """Append the [1m] 1M-context suffix to `model` when it is a 1M-capable model
    (matches _ONE_M_MODELS and isn't already suffixed); otherwise return it unchanged.
    Used for big_memory sessions so the 1M window is actually requested (#134)."""
    m = model or ""
    if not m or _ONE_M_SUFFIX in m:
        return m
    if any(tag in m.lower() for tag in _ONE_M_MODELS):
        return m + _ONE_M_SUFFIX
    return m

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

# #269: the table-format note (#243), the outbox file-delivery instructions (#187), and the
# per-session isolation/privacy note (#205/#208) were all FOLDED INTO the agent_context.md
# project document (loaded below) — so the agent's ENTIRE self-description lives in one
# editable place instead of several hardcoded prompt strings. Their content now appears in
# that doc's Files / "Your environment & privacy" / Rendering sections.
#
# #265/#269: tell the agent WHAT it is — a Telegram-bot frontend — and what it (and the
# user) can do, so it guides the user to the right mode/command instead of refusing or
# hallucinating. The text is maintained as a PROJECT DOCUMENT (agent_context.md) and loaded
# from there, so the bot's self-description can be edited without touching code. Appended to
# BOTH the chat and code system prompts (a restart picks up doc edits). A short built-in
# fallback keeps the bot working if the file is ever missing.
_AGENT_CONTEXT_FILE = Path(__file__).resolve().parent / "agent_context.md"
_BOT_CONTEXT_FALLBACK = (
    "\n\n## About you (this bot)\n"
    "You are running as a Telegram bot — a frontend to Claude / Claude Code. CHAT mode has "
    "read-only web tools but no terminal/files; CODE mode has the full Claude Code toolset "
    "in a sandbox. /code switches chat→code (and /chat back); /shell opens a jailed shell in "
    "a code session. Point the user at the right command instead of refusing or pretending; "
    "only describe features that actually exist."
)


def _load_bot_context() -> str:
    """Load the agent self-description from agent_context.md (#269), prefixed with the blank
    lines that separate it from the preceding prompt section. Falls back to a short built-in
    string if the file is missing/unreadable, so a bad deploy never strips the agent's
    self-awareness entirely."""
    try:
        text = _AGENT_CONTEXT_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return _BOT_CONTEXT_FALLBACK
    return ("\n\n" + text) if text else _BOT_CONTEXT_FALLBACK


BOT_CONTEXT_NOTE = _load_bot_context()

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
      thinking_delta -> .text holds an extended-thinking (reasoning) delta (#240c);
                     NOT part of the answer — for the live <tg-thinking> indicator only
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
    # #137: True when this error means the subscription window is exhausted, so the
    # consumer can flip the usage display to "limited" instead of leaving a stale
    # "OK" (the rate EVENTS keep saying allowed even after the account limit hits).
    limit_hit: bool = False


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


# #227a: unique marker a persistent-shell command emits when it finishes, carrying its exit
# code, so the host can detect command completion + rc on the PTY (output before it is clean).
_SHELL_SENTINEL = "__SBX_SH_DONE__"
# Terminal control noise an interactive PTY program emits (CSI sequences incl. bracketed-paste
# \x1b[?2004h/l and cursor moves; OSC title strings; TWO-char ESC escapes like ESC 7 / ESC 8 =
# save/restore-cursor, ESC =, ESC c; and lone CR/BEL/BS). Stripped so output is clean text.
# (Was: only \x1b[…CSI and \x1b]…OSC — it left the bare `7`/`8` of ESC 7 / ESC 8 visible, #227.)
_TERM_NOISE_RE = re.compile(
    r"\x1b\[[0-9;?]*[ -/]*[@-~]"          # CSI ... final
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC ... BEL|ST
    r"|\x1b[ -/]*[0-~]"                     # ESC (intermediate)* final — ESC 7/8/=/c/(B/#8/...
    r"|[\r\x07\x08]"                        # CR, BEL, backspace
)

# #246b: a full-screen / alt-screen TUI (an arrow-key picker like `gh auth login`) REDRAWS
# the whole screen on every keystroke, so the raw PTY stream piles up many full snapshots that
# _clean would otherwise concatenate into a garbled wall. When the program switched to the
# ALTERNATE screen (ESC[?1049h), keep only the LATEST frame — the text after the last
# screen-clear / cursor-home / alt-screen toggle. GATED on the alt-screen marker so ordinary
# multi-line output (and a bare `clear`, which uses ESC[2J but not ?1049h) is never touched.
_ALT_SCREEN_RE = re.compile(r"\x1b\[\?1049[hl]")
_FRAME_SPLIT_RE = re.compile(
    r"\x1b\[[0-3]?J"                  # erase display (J / 0J / 1J / 2J / 3J)
    r"|\x1b\[\?1049[hl]"             # alternate-screen enter / exit
    r"|\x1b\[(?:H|0?;?0?[Hf]|1;1[Hf])"  # cursor home (top-left)
)


def _latest_frame(text: str) -> str:
    """#246b: collapse a full-redraw alt-screen TUI to its latest frame. No-op unless the
    alternate screen was entered (ESC[?1049h). Returns the last frame that has visible text
    after noise-stripping (so an empty trailing clear doesn't blank the output)."""
    if not _ALT_SCREEN_RE.search(text):
        return text
    parts = _FRAME_SPLIT_RE.split(text)
    for seg in reversed(parts):
        if _TERM_NOISE_RE.sub("", seg).strip():
            return seg
    return text


class PersistentShell:
    """#227a: a long-lived login `bash` held on a PTY INSIDE the session's #119 jail. `cd`/env
    persist across run() calls (it is one shell). The bwrap process owns the jail; we own the
    PTY master on the host and drive the shell line-by-line.

    Non-interactive at this stage: run() sends the command followed by a sentinel-printf and
    reads the master until the sentinel (carrying the exit code). A command that blocks on input
    never reaches the printf, so run() times out and sends Ctrl-C to recover (true line-
    interactivity is #227b; #245 already refuses known-interactive commands fast)."""

    def __init__(self, proc, master_fd: int) -> None:
        self.proc = proc
        self.master = master_fd
        self._lock = asyncio.Lock()
        self._inited = False

    def alive(self) -> bool:
        return self.proc.returncode is None

    def _read_available(self) -> bytes:
        chunks: list[bytes] = []
        while True:
            try:
                d = os.read(self.master, 65536)
            except (BlockingIOError, InterruptedError):
                break
            except OSError:
                break
            if not d:
                break
            chunks.append(d)
        return b"".join(chunks)

    async def _init(self) -> None:
        # Quiet the shell so run() output is clean: no input echo, no prompt.
        os.write(self.master, b"stty -echo 2>/dev/null; export PS1='' PS2=''\n")
        await asyncio.sleep(0.3)
        self._read_available()  # drain the login banner + the echo of this line
        self._inited = True

    async def _drive(self, write: bytes, settle: float, timeout: float) -> tuple[int | None, str, str]:
        """Write `write` to the PTY, then read the master until one of:
          - the sentinel appears        -> ("done", rc, clean output)
          - output stalls for `settle`s after producing SOME output -> ("awaiting", None, …)
            (the command likely paused for interactive input — #227b)
          - the hard `timeout` elapses  -> ("timeout", 124, …) and Ctrl-C is sent to recover
        A SILENT command (no output yet) is NOT flagged awaiting — it keeps running to the
        sentinel/timeout, so a quiet `sleep`/compile isn't mistaken for an input prompt.
        Returns (rc_or_None, output, status)."""
        if write:
            os.write(self.master, write)
        buf = b""
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        last_out = loop.time()
        seen_output = False
        marker = (_SHELL_SENTINEL + ":").encode()
        idle_polls = 0  # #251: consecutive polls with no new output (drives backoff below)
        while True:
            d = self._read_available()
            if d:
                buf += d
                last_out = loop.time()
                seen_output = True
                idle_polls = 0  # #251: output flowing → poll fast again
                if marker in buf:
                    rc, out = self._parse(buf)
                    return (rc, out, "done")
            if not self.alive():
                # #227c: the shell process died (e.g. close() killed it to break a hang) —
                # return promptly instead of polling a dead PTY until the deadline.
                return (self.proc.returncode or 137, self._clean(buf), "done")
            now = loop.time()
            if now > deadline:
                with contextlib.suppress(OSError):
                    os.write(self.master, b"\x03")  # Ctrl-C to try to recover the shell
                return (124, self._clean(buf) + f"\n(timed out after {int(timeout)}s)", "timeout")
            if seen_output and (now - last_out) > settle:
                return (None, self._clean(buf), "awaiting")
            # #251: adaptive backoff — a quiet long-running command (compile, `sleep 300`) must
            # not spin the event loop at 25 Hz for minutes. Poll fast (~40 ms) while output flows
            # and for the first ~1 s of silence, then 0.2 s, then 0.5 s; any new output resets to
            # fast. settle (>=1.5 s) and the deadline are still caught within one slow poll.
            # was: await asyncio.sleep(0.04)  # replaced for #251
            idle_polls += 1
            delay = 0.5 if idle_polls > 50 else 0.2 if idle_polls > 25 else 0.04
            await asyncio.sleep(delay)

    async def run(self, command: str, settle: float = 3.0, timeout: float = 60.0):
        """Run one command. Returns (rc_or_None, output, status) — see _drive."""
        async with self._lock:
            if not self.alive():
                return (137, "(shell exited)", "done")
            if not self._inited:
                await self._init()
            self._read_available()  # drop anything stale before this command
            # ONE input line: cmd, then the sentinel-printf. Must be one line (not two) so an
            # interactive `read` inside cmd blocks for the USER's next line, not the printf.
            line = f"{command}; printf '\\n{_SHELL_SENTINEL}:%d\\n' \"$?\"\n"
            return await self._drive(line.encode("utf-8"), settle, timeout)

    async def send_input(self, text: str, settle: float = 1.5, timeout: float = 60.0):
        """#227b: send a line of INPUT (text + Enter) to the program currently awaiting it (no
        sentinel-printf — the pending one from the original command fires when it exits)."""
        return await self.send_raw((text + "\n").encode("utf-8"), settle, timeout)

    async def send_raw(self, data: bytes, settle: float = 1.5, timeout: float = 60.0):
        """#227b: write RAW bytes to the PTY (key sequences — arrows, Enter, Tab, Ctrl-C),
        no appended newline. Returns (rc_or_None, output, status)."""
        async with self._lock:
            if not self.alive():
                return (137, "(shell exited)", "done")
            # #279: drop output the program emitted while we were NOT reading (e.g. a fresh
            # prompt printed while shell mode was toggled off / the agent answered a message),
            # so the read after THIS input captures the program's RESPONSE — not a stale prompt
            # that would make the forwarded keystroke look ignored. `run()` drains the same way.
            self._read_available()
            return await self._drive(data, settle, timeout)

    async def peek(self, settle: float = 0.4) -> tuple[int | None, str, str]:
        """#279: read whatever the program has printed since we last read — WITHOUT sending
        any input — and report it. Used on /shell re-attach to surface output the program
        emitted while detached (e.g. it advanced to a new prompt). Quick: a short settle, no
        wait for a sentinel. Returns (None, output, "awaiting") — empty output if nothing new."""
        async with self._lock:
            if not self.alive():
                return (137, "(shell exited)", "done")
            await asyncio.sleep(min(0.3, max(0.05, settle / 2)))  # let in-flight bytes land
            return (None, self._clean(self._read_available()), "awaiting")

    async def interrupt(self) -> str:
        """#227c/#246: send Ctrl-C to the shell. The jailed bash now has a CONTROLLING TTY
        (see _start_shell), so the 0x03 byte is a REAL SIGINT to the foreground process group
        — a hung foreground command (e.g. a polling `gh auth login`) is actually interrupted,
        not just fed an input byte. Returns whatever drained afterwards."""
        async with self._lock:
            with contextlib.suppress(OSError):
                os.write(self.master, b"\x03")
            await asyncio.sleep(0.2)
            return self._clean(self._read_available())

    @staticmethod
    def _clean(buf: bytes) -> str:
        text = _latest_frame(buf.decode("utf-8", "replace"))  # #246b: collapse alt-screen redraws
        return _TERM_NOISE_RE.sub("", text).strip("\n")

    def _parse(self, buf: bytes) -> tuple[int, str]:
        text = buf.decode("utf-8", "replace")
        idx = text.rfind(_SHELL_SENTINEL + ":")
        rc = 0
        if idx >= 0:
            m = re.match(r"\s*(-?\d+)", text[idx + len(_SHELL_SENTINEL) + 1:])
            if m:
                rc = int(m.group(1))
            text = text[:idx]
        return (rc, _TERM_NOISE_RE.sub("", _latest_frame(text)).strip("\n"))  # #246b

    async def close(self) -> None:
        # #249: self.proc is the launcher, which exec-chains (setpriv→) into `bwrap
        # --unshare-pid` (deploy/sandbox-claude.sh) — same PID, so proc.kill() SIGKILLs
        # bwrap, which is PID 1 of the jail's PID namespace. The kernel then SIGKILLs
        # EVERY process in that namespace, including a setsid-DETACHED background process
        # (a server/build the shell started) that escaped the process group. So this
        # single kill reaps the whole jail — no separate cgroup/process-group sweep is
        # needed. (Verified empirically: a setsid'd bg process dies with the namespace.)
        with contextlib.suppress(Exception):
            if self.alive():
                self.proc.kill()
        with contextlib.suppress(Exception):
            await self.proc.wait()
        with contextlib.suppress(OSError):
            os.close(self.master)


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
        cred_broker_url: str | None = None,
        egress: bool = False,
        egress_proxy_url: str | None = None,
        sbx_mem_max: str | None = None,
        sbx_cpu_max: str | None = None,
        sbx_pids_max: int = 0,
        seccomp_path: str | None = None,
        per_session_uid: bool = False,
        uid_base: int = 700000,
        uid_range: int = 60000,
        auto_compact: bool = True,
        user_level: str | None = None,
    ) -> None:
        self.mode = mode
        # #276: the session OWNER's access level ("chat" | "code" | None=unknown). Drives the
        # dynamic "this session right now" note so the model knows whether the user can /code.
        self.user_level = user_level
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
        # session INJECTS the owner's ~/.claude/CLAUDE.md (+ memory) CONTENT into the
        # system prompt (_global_memory_block), keeping setting_sources=[] so
        # settings.json (permissions/env) is NEVER loaded (#130). Relaxes the
        # per-session isolation invariant for that user only; OFF by default.
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
        # #119b: when set, the jail gets a DUMMY token + ANTHROPIC_BASE_URL=this, so the
        # real OAuth token never enters the jail (the host broker injects it). None = off.
        self.cred_broker_url = cred_broker_url
        # #119c/#119e: egress allowlist + per-jail DoS limits. egress → the launcher joins
        # the firewalled cgroup + routes tools via the CONNECT proxy; the limit strings
        # (already formatted for memory.max / cpu.max / pids.max) populate the cgroup leaf;
        # seccomp_path is the compiled denylist BPF bound via bwrap --seccomp. All optional.
        self.egress = bool(egress)
        self.egress_proxy_url = egress_proxy_url
        self.sbx_mem_max = sbx_mem_max
        self.sbx_cpu_max = sbx_cpu_max
        self.sbx_pids_max = int(sbx_pids_max or 0)
        self.seccomp_path = seccomp_path
        # Per-session unprivileged HOST uid: each jail runs (via setpriv) as a distinct
        # non-root uid derived from the session id, so an escape is unprivileged AND can't
        # read other sessions' (differently-owned) files. Applies to ALL modes.
        self.per_session_uid = bool(per_session_uid)
        self.uid_base = int(uid_base)
        self.uid_range = max(1, int(uid_range))
        # #221: the registry-assigned host uid (claimed lazily in _ensure_client, then
        # cached here). None until claimed; _enable_sandbox falls back to the bare hash.
        self.host_uid: int | None = None
        # #168: SDK auto-compaction (ON by default = the CLI default). When False,
        # _build_env sets DISABLE_AUTO_COMPACT=1 (forwarded through the sandbox).
        self.auto_compact = bool(auto_compact)
        # session_id is updated from each ResultMessage and passed back as
        # options.resume so a freshly-built client continues the prior session.
        self.session_id: str | None = resume_session_id
        self.client: ClaudeSDKClient | None = None
        # #227a: the session's persistent jailed shell (lazily started by shell_run); held so
        # cd/env persist across messages and torn down with the session (aclose).
        self._shell: "PersistentShell | None" = None
        # #137: rolling buffer of the child CLI's stderr (filled by _on_stderr, wired
        # via ClaudeAgentOptions.stderr). The SDK only pipes the child's stderr when
        # this callback is set — otherwise a non-zero exit raised a ProcessError whose
        # detail was the literal "Check stderr output for details", and the REAL line
        # (e.g. "No conversation found with session ID …", or a limit message) leaked
        # to the bot's own stderr/log instead of reaching the user.
        self._stderr_lines: list[str] = []
        # Set by interrupt() so run() can tell a deliberate /stop apart from a
        # real failure: when interrupting, any exception out of receive_response()
        # is an expected end, not an error to surface. Reset at the start of run().
        self._interrupted = False

    def _on_stderr(self, line: str) -> None:
        """SDK stderr callback (#137). Append-only, no I/O / await — it runs on the
        SDK's reader-task loop. Keep only the last ~50 lines (the tail carries the
        actual error)."""
        self._stderr_lines.append(line)
        del self._stderr_lines[:-50]

    def _stderr_text(self) -> str:
        """The captured CLI stderr tail (#137), for surfacing the real error."""
        return "\n".join(self._stderr_lines[-8:]).strip()

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
        # #168: disable the CLI's auto-compaction when the (effective) toggle is off.
        # Verified: this flips ContextUsageResponse.isAutoCompactEnabled to False.
        if not self.auto_compact:
            env["DISABLE_AUTO_COMPACT"] = "1"
        return env

    def _sandbox_launcher(self) -> str:
        """Absolute path to the committed bubblewrap launcher (deploy/)."""
        return str(Path(__file__).resolve().parent / "deploy" / "sandbox-claude.sh")

    def _hash_uid(self) -> int:
        """The deterministic per-session host uid from the sid — the PREFERRED value the
        #221 registry hands out (and remaps only on collision). uid_base + sid % range."""
        sid = Path(self.cwd).parent.name
        try:
            n = int(sid, 16)            # the sid is a 6-hex-char digest (db.session_sid)
        except ValueError:
            n = sum(sid.encode()) or 1  # fallback for non-sid cwds (e.g. tests)
        return self.uid_base + (n % self.uid_range)

    async def _claim_host_uid(self) -> int:
        """#221: a stable, collision-free host uid via the db registry. The bare hash
        (_hash_uid) is the PREFERRED value; the registry probes to a free uid when two
        sids collide and remembers the assignment, so it stays stable across rebuilds.
        Falls back to the bare hash if the registry is unavailable (prior behaviour)."""
        preferred = self._hash_uid()
        sid = Path(self.cwd).parent.name
        try:
            import db
            return await db.claim_session_uid(
                sid, preferred, self.uid_base, self.uid_base + self.uid_range
            )
        except Exception:
            logger.warning("uid registry claim failed for sid=%s; using hash uid %d",
                           sid, preferred, exc_info=True)
            return preferred

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
        # The exec target. Under a per-session unprivileged uid the jail can't reach the
        # default ~/.local/bin/claude (/root is 0700), so use the world-readable staged
        # copy under /usr that bot.main maintains (see _stage_sandbox_claude).
        if self.per_session_uid:
            env["SBX_CLAUDE"] = "/usr/local/bin/claude"
        else:
            env["SBX_CLAUDE"] = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
        env["SBX_CREDS"] = os.path.expanduser("~/.claude/.credentials.json")
        env["SBX_STATE"] = str(Path(self.cwd).parent / "state")  # #181: <sid>/state (was {cwd}.sbxstate)
        # #119b: broker mode — the launcher binds a DUMMY credential and points the
        # inner CLI at the host broker (ANTHROPIC_BASE_URL), so the real token is never
        # in the jail. When unset, the launcher binds the real SBX_CREDS as before.
        if self.cred_broker_url:
            env["SBX_BROKER_URL"] = self.cred_broker_url
        # #119d: per-session user-supplied service creds — the launcher injects each
        # KEY=VALUE from this file as --setenv into THIS jail only (file is per-session,
        # root-owned 0600). Always pointed at <sid>/secrets.env; the launcher no-ops if
        # absent. The owner's own credentials never enter any jail.
        env["SBX_SECRETS_ENV"] = str(Path(self.cwd).parent / "secrets.env")
        # #119c egress allowlist + #119e cgroup DoS limits apply to CODE sessions ONLY —
        # that's the Bash/file-capable exfil surface the #119 threat model targets. Chat
        # carries only the read-only web tools (no Bash, no host-data to leak), so egress
        # there adds ~no security but WOULD break WebFetch (it fetches arbitrary URLs
        # client-side) by blocking everything off the allowlist; leave chat egress open.
        # SBX_USE_CGROUP gates the cgroup placement (needed for the firewall match AND the
        # limits). The broker, seccomp and per-session secrets below apply to ALL modes.
        if self.mode == "code":
            if self.egress and self.egress_proxy_url:
                env["SBX_EGRESS"] = "1"
                env["SBX_PROXY_URL"] = self.egress_proxy_url
            if self.sbx_mem_max:
                env["SBX_MEM_MAX"] = self.sbx_mem_max
            if self.sbx_cpu_max:
                env["SBX_CPU_MAX"] = self.sbx_cpu_max
            if self.sbx_pids_max:
                env["SBX_PIDS_MAX"] = str(self.sbx_pids_max)
            if self.egress or self.sbx_mem_max or self.sbx_cpu_max or self.sbx_pids_max:
                env["SBX_USE_CGROUP"] = "1"
        if self.seccomp_path and os.path.exists(self.seccomp_path):
            env["SBX_SECCOMP"] = self.seccomp_path
        # Per-session unprivileged HOST uid (ALL modes): a distinct non-root uid derived
        # from the session id. The launcher chowns the workdir to it and runs bwrap via
        # setpriv as that uid, so a jail escape is unprivileged and can't reach another
        # session's (differently-owned) files. Deterministic so the uid is stable across
        # rebuilds (the on-disk chown stays valid).
        if self.per_session_uid:
            # #221: prefer the registry-assigned uid (collision-free, claimed in
            # _ensure_client); fall back to the bare deterministic hash when it hasn't
            # been claimed yet (e.g. unit tests that build options directly).
            host_uid = self.host_uid if self.host_uid is not None else self._hash_uid()
            env["SBX_HOST_UID"] = str(host_uid)
            env["SBX_HOST_GID"] = str(host_uid)
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

    def _global_memory_text(self) -> str:
        """Read the owner's GLOBAL memory — ``~/.claude/CLAUDE.md`` plus any
        ``~/.claude/memory/*.md`` — as a single string for DIRECT system-prompt
        injection (#130). Returns "" when none exists or on any read error. This
        REPLACES widening ``setting_sources=["user"]`` so ``settings.json``
        (permissions / env) is never loaded. Read on each build so edits to the
        owner's memory take effect on the next rebuild."""
        base = os.path.expanduser("~/.claude")
        parts: list[str] = []
        cmd = os.path.join(base, "CLAUDE.md")
        try:
            if os.path.isfile(cmd):
                with open(cmd, encoding="utf-8") as fh:
                    parts.append(fh.read().strip())
        except OSError:
            pass
        mem_dir = os.path.join(base, "memory")
        try:
            if os.path.isdir(mem_dir):
                for name in sorted(os.listdir(mem_dir)):
                    if not name.endswith(".md"):
                        continue
                    try:
                        with open(os.path.join(mem_dir, name), encoding="utf-8") as fh:
                            parts.append(fh.read().strip())
                    except OSError:
                        pass
        except OSError:
            pass
        return "\n\n".join(p for p in parts if p)

    def _global_memory_block(self) -> str:
        """The owner's global memory wrapped as an injectable system-prompt section
        (#130), or "" when global memory is off / there is nothing to inject."""
        if not self.global_memory:
            return ""
        mem = self._global_memory_text()
        if not mem:
            return ""
        return (
            "\n\n# Owner global memory (from ~/.claude/CLAUDE.md)\n"
            "The deployer has shared these personal instructions and notes with this "
            "session — treat them as standing guidance:\n\n" + mem
        )

    async def run_shell(self, command: str, timeout: float = 60.0) -> tuple[int, str]:
        """#224: run ONE shell command in THIS session's jail (no LLM, no tokens) and
        return (returncode, combined stdout+stderr).

        Requires the sandbox — refuses otherwise, since shell mode runs arbitrary user
        commands and must stay confined (per-session uid + egress + seccomp + secrets).
        Reuses the SBX_* env that `_enable_sandbox` builds; the launcher branches on
        SBX_MODE=shell and execs `/bin/bash -lc "$SBX_SHELL_CMD"` instead of the CLI.
        """
        if not self.sandbox:
            return (126, "Shell mode requires the sandbox, which is disabled for this session.")
        if self.per_session_uid and self.host_uid is None:
            with contextlib.suppress(Exception):
                self.host_uid = await self._claim_host_uid()
        with contextlib.suppress(OSError):
            os.makedirs(self.cwd, exist_ok=True)
            os.makedirs(str(Path(self.cwd).parent / "state"), exist_ok=True)
        common: dict = {"env": dict(os.environ)}
        self._enable_sandbox(common)
        env = common["env"]
        env["SBX_MODE"] = "shell"
        env["SBX_SHELL_CMD"] = command
        launcher = common["cli_path"]
        proc = await asyncio.create_subprocess_exec(
            launcher,
            cwd=self.cwd,
            env=env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except (asyncio.TimeoutError, TimeoutError):
            with contextlib.suppress(Exception):
                proc.kill()
            with contextlib.suppress(Exception):
                await proc.wait()
            return (124, f"(timed out after {int(timeout)}s — process killed)")
        text = (out or b"").decode("utf-8", "replace")
        return (proc.returncode if proc.returncode is not None else -1, text)

    async def shell_run(self, command: str, timeout: float = 60.0):
        """#227a: run a command in this session's PERSISTENT jailed shell so cd/env persist
        across messages. Lazily starts the held PTY shell; raises on a spawn failure so the
        caller can fall back to the one-shot run_shell. Returns (rc_or_None, output, status)."""
        if not self.sandbox:
            return (126, "Shell mode requires the sandbox, which is disabled for this session.", "done")
        sh = self._shell
        if sh is None or not sh.alive():
            sh = await self._start_shell()
            self._shell = sh
        return await sh.run(command, timeout=timeout)

    async def shell_peek(self) -> tuple[int | None, str, str]:
        """#279: non-intrusive read of the persistent shell's pending output (no input sent)."""
        sh = self._shell
        if sh is None or not sh.alive():
            return (0, "", "done")
        return await sh.peek()

    async def shell_send_input(self, text: str, timeout: float = 60.0):
        """#227b: forward a line of input to the program awaiting it in the persistent shell.
        Returns (rc_or_None, output, status); ('','no shell','done') if none is running."""
        sh = self._shell
        if sh is None or not sh.alive():
            return (0, "", "done")
        return await sh.send_input(text, timeout=timeout)

    async def shell_send_keys(self, data: bytes, timeout: float = 60.0):
        """#227b: forward raw key bytes (arrows/Enter/Tab/Ctrl-C) to the awaiting program."""
        sh = self._shell
        if sh is None or not sh.alive():
            return (0, "", "done")
        return await sh.send_raw(data, timeout=timeout)

    async def shell_interrupt(self) -> str:
        """#227c/#246: send Ctrl-C to the persistent shell — a real SIGINT (controlling tty)."""
        sh = self._shell
        if sh is None or not sh.alive():
            return ""
        return await sh.interrupt()

    async def _start_shell(self) -> "PersistentShell":
        """#227a: spawn the held login-bash on a PTY inside this session's jail."""
        if self.per_session_uid and self.host_uid is None:
            with contextlib.suppress(Exception):
                self.host_uid = await self._claim_host_uid()
        with contextlib.suppress(OSError):
            os.makedirs(self.cwd, exist_ok=True)
            os.makedirs(str(Path(self.cwd).parent / "state"), exist_ok=True)
        common: dict = {"env": dict(os.environ)}
        self._enable_sandbox(common)
        env = common["env"]
        env["SBX_MODE"] = "shell_persist"      # launcher execs `bash -i` on the PTY
        launcher = common["cli_path"]
        master, slave = os.openpty()
        os.set_blocking(master, False)
        # #246: give the jailed bash a CONTROLLING TTY so Ctrl-C (the 0x03 byte) is a REAL
        # SIGINT to the foreground process group — not just an ignorable byte (the #227c caveat).
        # os.login_tty(slave) runs in the child (setsid + TIOCSCTTY + dup slave→0,1,2); pass_fds
        # keeps `slave` open across subprocess's fd-closing so login_tty can use it. bwrap is NOT
        # --new-session, so the controlling tty persists through setpriv→bwrap→bash, even across
        # --unshare-pid (verified e2e). login_tty's setsid makes the launcher a session leader,
        # so this replaces start_new_session=True with no change to the #179 reaper/cgroup invariant.
        # was: start_new_session=True  (replaced for #246 — login_tty does the setsid)
        def _ctty() -> None:
            os.login_tty(slave)
        try:
            proc = await asyncio.create_subprocess_exec(
                launcher, cwd=self.cwd, env=env,
                stdin=slave, stdout=slave, stderr=slave,
                preexec_fn=_ctty, pass_fds=(slave,),
            )
        except BaseException:
            # #248: on spawn failure the master fd would leak (the finally only
            # closes slave) — close it too, else a repeatedly-failing _start_shell
            # exhausts fds one master per attempt.
            with contextlib.suppress(OSError):
                os.close(master)
            raise
        finally:
            with contextlib.suppress(OSError):
                os.close(slave)  # the child holds its own dup; we keep only the master
        return PersistentShell(proc, master)

    async def _close_shell(self) -> None:
        """#227a: kill + forget the persistent shell (best-effort)."""
        sh, self._shell = self._shell, None
        if sh is not None:
            with contextlib.suppress(Exception):
                await sh.close()

    def has_live_shell(self) -> bool:
        """#274: True if this session holds a still-running persistent shell."""
        return self._shell is not None and self._shell.alive()

    def detach_shell(self):
        """#274: hand off the live persistent shell WITHOUT closing it, so it can survive
        a client rebuild/reap (the ~500 MB claude client is freed; the ~3 MB jailed shell —
        with the user's cd/env + any running command — is preserved). Returns it or None."""
        sh, self._shell = self._shell, None
        return sh

    def adopt_shell(self, sh) -> None:
        """#274: re-attach a previously-detached persistent shell (cd/env/running cmd intact)."""
        if sh is not None and self._shell is None:
            self._shell = sh

    def _session_state_note(self) -> str:
        """#276: a short, DYNAMIC note telling the model the CURRENT session's mode and what
        the user can do about it (the static doc only describes the modes in general). Appended
        to both system prompts so the model gives accurate guidance instead of guessing."""
        if self.mode == "code":
            return (
                "\n\n## This session right now\n"
                "This is a **CODE** session: you have the full Claude Code toolset (Bash, "
                "read/write/edit files) in a sandbox, and the user can enter a persistent jailed "
                "terminal with **/shell**. The user can switch this session back to plain chat with "
                "**/chat**."
            )
        if self.user_level == "code":
            return (
                "\n\n## This session right now\n"
                "This is a **CHAT** session: conversation plus read-only web tools only — no shell, "
                "files, or code execution. The user HAS code access: if they want to run commands or "
                "edit files, tell them to send **/code** to turn THIS session into a full Claude Code "
                "session (then **/shell** for a terminal), and **/chat** to switch back. Don't pretend "
                "to run anything here — point them to /code."
            )
        return (
            "\n\n## This session right now\n"
            "This is a **CHAT** session: conversation plus read-only web tools only — no shell, files, "
            "or code execution. The user's access level is **chat-only**, so they CANNOT upgrade to code "
            "themselves — do NOT tell them to use /code. Only the bot's owner can grant code access. If "
            "they need to run commands or edit files, explain that the owner must grant them code access "
            "first."
        )

    def _build_options(self) -> ClaudeAgentOptions:
        """Construct ClaudeAgentOptions for the current mode/model/cwd."""
        env = self._build_env()
        mem_block = self._global_memory_block()

        common: dict = {
            # #134: a big_memory session requests the 1M context window via the [1m]
            # model-id suffix (see _one_m_model) — for 1M-capable models only (Opus by
            # default; the `betas` param below was ignored under the subscription).
            # was: "model": self.model,
            "model": _one_m_model(self.model) if self.big_memory else self.model,
            # Isolation: pass [] (NOT None) so the CLI loads NO user/project/local
            # settings and NO CLAUDE.md. In this SDK version None means "load all
            # filesystem sources" — the opposite of what we want.
            #
            # #130 FIX: GLOBAL MEMORY no longer widens setting_sources to ["user"].
            # "user" ALSO loaded ~/.claude/settings.json — whose permissions.allow
            # could AUTO-allow tools the bot keeps out of allowed_tools (bypassing the
            # can_use_tool gate) and whose env could merge a settings ANTHROPIC_API_KEY
            # into the child (flipping billing, the #1 hard rule). Instead we keep
            # setting_sources=[] ALWAYS and INJECT the owner's CLAUDE.md / memory
            # CONTENT directly into the system prompt (_global_memory_block + the
            # chat/code branches below) — the memory reaches the model WITHOUT ever
            # loading settings.json. Also works under the sandbox (the jail's HOME has
            # no ~/.claude), where setting_sources=["user"] silently read nothing.
            "setting_sources": [],
            "include_partial_messages": True,  # enable text-delta streaming
            "env": env,
            # #137: capture the child CLI's stderr so a startup/turn failure surfaces
            # the REAL reason (stale resume id, limit, bwrap error) instead of the
            # SDK's generic "Check stderr output for details". was: no stderr key.
            "stderr": self._on_stderr,
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
            # #187: ALWAYS append the outbox file-delivery instruction (+ the owner's
            # CLAUDE.md/memory when present) as an ADDITIVE append to the default Claude
            # Code preset — keeps the full agent prompt intact (the #130 mechanism),
            # instead of loading via setting_sources=["user"] (+ settings.json). was:
            # only set system_prompt when mem_block was non-empty (#130).
            # #205: also state the per-session isolation so the agent can answer the
            # user accurately if asked about privacy / where their files live.
            # #269: outbox/isolation/table notes are now part of BOT_CONTEXT_NOTE (the doc).
            append = (BOT_CONTEXT_NOTE + self._session_state_note()
                      + (("\n\n" + mem_block) if mem_block else ""))
            code_extra["system_prompt"] = {
                "type": "preset", "preset": "claude_code", "append": append,
            }
            # #134: the 1M window is now requested via the [1m] model-id suffix in
            # common["model"] (see _one_m_model). The `betas` param below was a NO-OP
            # under the OAuth subscription ("Custom betas are only available for API
            # key users"), so it's commented out — kept for revert/history. was (#133):
            # if self.big_memory:
            #     code_extra["betas"] = ["context-1m-2025-08-07"]
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
        # #180: jail chat too (was code-only). Chat is tool-free but still a
        # subprocess — routing it through the bubblewrap launcher drops it to the
        # unprivileged uid, confines it to the workdir, and keeps its transcript in
        # the per-session <sid>/state dir instead of the host ~/.claude.
        if self.sandbox:
            self._enable_sandbox(common)
        chat_extra: dict = {}
        # #134: 1M is now requested via the [1m] model-id suffix (common["model"], see
        # _one_m_model); the `betas` param was ignored under the subscription. Commented
        # out — kept for revert/history. was:
        # if self.big_memory:
        #     chat_extra["betas"] = ["context-1m-2025-08-07"]
        return ClaudeAgentOptions(
            # #130: append the owner's CLAUDE.md/memory directly (mem_block is "" when
            # global memory is off or empty), instead of loading it via setting_sources.
            system_prompt=CHAT_SYSTEM_PROMPT + BOT_CONTEXT_NOTE + self._session_state_note() + mem_block,
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
                # #187: pre-create the outbox drop-dir so the agent can always write
                # into it (`cp file outbox/`). Code mode only — chat is tool-free, so it
                # never creates files; the host drains + clears it after each turn.
                if self.mode == "code":
                    os.makedirs(str(Path(self.cwd) / "outbox"), exist_ok=True)
                if self.sandbox:
                    # #181: per-session jail state dir (HOME → ~/.claude/projects), a
                    # SIBLING of the cwd under one <sid> parent: <sid>/work (cwd) +
                    # <sid>/state. #180: created for ALL modes now — chat is jailed too.
                    # was: code-only `{cwd}.sbxstate`.
                    os.makedirs(str(Path(self.cwd).parent / "state"), exist_ok=True)
                # #137: lock the workdir (+ state + the <sid> parent) to the owner only.
                # The sandboxed CLI writes as the mapped uid with a 0022 umask, so
                # outputs landed world-readable; 0700 keeps a session off-limits to
                # other local users.
                with contextlib.suppress(OSError):
                    os.chmod(self.cwd, 0o700)
                    if self.sandbox:
                        os.chmod(str(Path(self.cwd).parent / "state"), 0o700)
                        os.chmod(str(Path(self.cwd).parent), 0o700)  # the <sid> parent
            # was: assign self.client THEN connect() — replaced for #137
            #   self.client = ClaudeSDKClient(self._build_options())
            #   await self.client.connect()
            # If connect() (or even the constructor) raised, self.client was left
            # non-None but unconnected; the next turn's `self.client is None` check
            # was False, so it skipped reconnect and every later query()/
            # receive_response() hit an unconnected client → "Not connected. Call
            # connect() first." until a process restart. Build into a LOCAL, connect
            # it, and only publish to self.client AFTER connect() succeeds; tear the
            # half-built client down on any failure so the next turn reconnects clean.
            #
            # #137: a STALE --resume id ("No conversation found with session ID …",
            # which is what produced the reported exit-1 startup failure) is
            # recoverable — drop the dead id and retry ONCE with a fresh session, so
            # the user just keeps going instead of being wedged. Only retry on that
            # exact signature; never on a limit/auth/billing failure.
            # #221: claim a stable, collision-free host uid for this jail BEFORE building
            # options (the claim is async; _enable_sandbox/_build_options are sync). Cached
            # on self.host_uid so rebuilds reuse it; no-op for non-sandbox/non-uid sessions.
            if self.sandbox and self.per_session_uid and self.host_uid is None:
                self.host_uid = await self._claim_host_uid()
            for attempt in (1, 2):
                self._stderr_lines.clear()
                client = ClaudeSDKClient(self._build_options())
                try:
                    await client.connect()
                except BaseException as exc:
                    with contextlib.suppress(Exception):
                        await client.disconnect()
                    if (
                        attempt == 1
                        and self.session_id
                        and _classify_stderr(self._stderr_text()) == "resume_lost"
                    ):
                        logger.warning(
                            "resume id %s not found — retrying without resume",
                            self.session_id,
                        )
                        self.session_id = None
                        continue
                    raise exc
                self.client = client
                return

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
            # _ensure_client already tore down its half-built local client, but be
            # defensive in case a connected client survived a later failure path:
            # drop it so the NEXT turn rebuilds + reconnects instead of reusing a
            # dead handle (#137 — the "Not connected" loop).
            await self._drop_client()
            # #137: prefer the REAL captured CLI stderr over the SDK's generic
            # "Command failed … Check stderr output for details", and classify it so
            # the user sees a meaningful, localized message. was: error_detail=str(exc).
            detail = self._stderr_text() or str(exc)
            if detail != str(exc):
                logger.warning("session start failed: %s", detail)
            kind = _classify_stderr(detail)
            if kind == "rate_limit":
                yield EngineEvent(
                    kind="error",
                    text="Subscription limit reached. Please try again later.",
                    error_key="err.rate_limit",
                    error_detail=detail,
                    limit_hit=True,
                )
            else:
                yield EngineEvent(
                    kind="error",
                    text=f"Failed to start session: {detail}",
                    error_key="err.start_failed",
                    error_detail=detail,
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
                        else:
                            # #240c: extended-thinking deltas arrive as the SAME event with a
                            # `thinking_delta` (delta.thinking) instead of text. Surface them so
                            # the consumer can stream the reasoning into the <tg-thinking> block.
                            # NOT added to running_text — reasoning is not the answer.
                            think = delta.get("thinking")
                            if think:
                                yield EngineEvent(kind="thinking_delta", text=think)
                    continue

                # --- Assistant message: text blocks + tool-use blocks ---
                if isinstance(msg, AssistantMessage):
                    if getattr(msg, "error", None):
                        # Auth/billing errors arrive HERE as an in-band
                        # AssistantMessage.error (e.g. "authentication_failed"), NOT
                        # as a connect/stream exception — so, unlike the other two
                        # error paths, this one never dropped the client. A long-lived
                        # `claude` subprocess holding a now-stale OAuth token (the
                        # access token expired mid-run, or the owner re-logged in and
                        # rewrote ~/.claude/.credentials.json) would then repeat the
                        # 401 on EVERY following turn until a manual bot restart. Drop
                        # the client for the credential-class errors so the next turn
                        # rebuilds a fresh subprocess that re-reads the refreshed
                        # credentials and self-heals — no restart needed. (The proper
                        # central fix is the #119 broker: it owns token injection +
                        # OAuth refresh so a single subprocess never goes stale.)
                        if str(msg.error) in ("authentication_failed", "billing_error"):
                            await self._drop_client()
                        yield EngineEvent(
                            kind="error",
                            text=_error_message(msg.error),
                            error_key=_error_key(msg.error),
                            error_detail=str(msg.error),
                            # #137: a mid-turn rate_limit means the window is spent —
                            # let the consumer flip the usage display to "limited".
                            limit_hit=(str(msg.error) == "rate_limit"),
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
            # The transport may be wedged after a query()/receive_response()
            # failure (e.g. the CLI subprocess died mid-turn). Drop the client so
            # the next turn reconnects cleanly rather than replaying the error on a
            # dead handle (#137 — "Not connected. Call connect() first.").
            await self._drop_client()
            # #137: surface the real CLI stderr + classify (limit vs generic), same
            # as the connect-time path. was: error_detail=str(exc) only.
            detail = self._stderr_text() or str(exc)
            if detail != str(exc):
                logger.warning("turn failed: %s", detail)
            if _classify_stderr(detail) == "rate_limit":
                yield EngineEvent(
                    kind="error",
                    text="Subscription limit reached. Please try again later.",
                    error_key="err.rate_limit",
                    error_detail=detail,
                    limit_hit=True,
                )
            else:
                yield EngineEvent(
                    kind="error",
                    text=f"Execution error: {detail}",
                    error_key="err.exec_error",
                    error_detail=detail,
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

    async def _drop_client(self) -> None:
        """Disconnect and forget the current client (best-effort).

        Shared teardown for failure paths in run(): after a connect/query/stream
        failure the handle may be unusable, so we disconnect (suppressing errors)
        and set self.client = None so _ensure_client rebuilds + reconnects on the
        next turn. Per-thread rec.lock (sessions.py) serializes turns for a given
        session, so this never races a concurrent run() on the same client.
        """
        client, self.client = self.client, None
        if client:
            with contextlib.suppress(Exception):
                await client.disconnect()

    async def aclose(self) -> None:
        """Disconnect and drop the underlying client."""
        # was: inline disconnect + self.client = None — replaced for #137
        await self._drop_client()
        await self._close_shell()  # #227a: tear down the persistent jailed shell too

    def set_model(self, model: str) -> None:
        """Update the model, applied on the next client build.

        We deliberately do NOT fire a detached client.set_model() task here: a
        bare create_task() can be garbage-collected before completion and would
        race an in-flight turn on the live client. Model changes go through the
        rebuild path (SessionManager.on_mode_or_model_or_cwd_change), which
        aclose()s the old client and builds a new one with the new model.
        """
        self.model = model
