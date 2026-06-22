"""Per-thread orchestration: session + serial worker + task queue.

Each forum topic (thread_id, with 0 meaning the General topic) gets its own
isolated record holding exactly one engine.ClaudeSession, one asyncio.Queue of
pending prompts, one current worker asyncio.Task, the live Streamer, an activity
timestamp, the latest subscription RateLimitInfo, and a per-thread asyncio.Lock.

Nothing — no ClaudeSession, Streamer, queue, or session_id — is ever shared
across thread_ids. Messages that arrive while a run is in progress are QUEUED
and executed in the SAME session afterwards, preserving conversation context and
the prompt cache (the task-chaining feature). /stop interrupts the in-flight run,
cancels the worker, and clears the queue.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from aiogram.types import BufferedInputFile

from app.storage import archive
from app.storage import db
from app import i18n
from app.telegram import markup
from app.core import token_refresh
from app.storage import usage
from app.access import settings_schema
from app.core.engine import ClaudeSession
from app.telegram.streamer import Streamer, resolve_speed  # #294: tool_phase_label now used via streamer.set_tool_phase
from app.access.permissions import PermissionGate

logger = logging.getLogger(__name__)  # #325: drain progress → the journal

# The Anthropic prompt cache stays warm for ~5 minutes after the last request.
_CACHE_WINDOW_SECONDS = 300.0


class FairAdmission:
    """#326: a FAIR concurrency gate for turn admission. At most ``slots`` turns run at once;
    when full, waiting turns are admitted ROUND-ROBIN by key (the user / chat_id), so one user's
    burst across many sessions can't occupy every slot and starve another user — which a plain
    ``asyncio.Semaphore`` allows (it wakes blocked acquirers FIFO by arrival). Pure single-threaded
    asyncio; cancellation-safe (a cancelled waiter is removed; a slot handed to a since-cancelled
    waiter is passed on, never leaked). Drop-in for the Semaphore's ``locked()`` + acquire/release."""

    def __init__(self, slots: int) -> None:
        self._slots = max(1, int(slots))
        self._in_use = 0
        self._waiters: dict = {}        # key -> deque[asyncio.Future] (FIFO within one user)
        self._order: deque = deque()    # keys that HAVE waiters, in round-robin order (each once)

    def locked(self) -> bool:
        """True when every slot is taken (a new acquire would have to wait)."""
        return self._in_use >= self._slots

    @property
    def active(self) -> int:
        return self._in_use

    async def acquire(self, key) -> None:
        """Take a slot, waiting (round-robin by key) if all are busy."""
        if self._in_use < self._slots:
            self._in_use += 1
            return
        fut = asyncio.get_running_loop().create_future()
        q = self._waiters.get(key)
        if q is None:
            q = deque()
            self._waiters[key] = q
        q.append(fut)
        if len(q) == 1:                 # this key's FIRST waiter → join the rotation
            self._order.append(key)
        try:
            await fut
        except asyncio.CancelledError:
            # Cancelled while WAITING → drop our future. Cancelled just AFTER being handed the
            # slot → pass it on so the slot isn't leaked.
            if not fut.done():
                with contextlib.suppress(ValueError):
                    q.remove(fut)
            elif not fut.cancelled():
                self.release()
            raise

    def release(self) -> None:
        """Release a held slot — hand it to the next waiter ROUND-ROBIN by key, else free it."""
        while self._order:
            key = self._order.popleft()
            q = self._waiters.get(key)
            if not q:
                self._waiters.pop(key, None)
                continue
            fut = q.popleft()
            if q:                       # key still has waiters → back of the rotation
                self._order.append(key)
            else:
                self._waiters.pop(key, None)
            if not fut.done():          # hand the slot over (in_use stays the same)
                fut.set_result(None)
                return
            # waiter was cancelled in flight → keep looking for a live one
        self._in_use -= 1               # nobody waiting → the slot is now free
        if self._in_use < 0:
            self._in_use = 0


# #187: outbox file send-back. The agent drops files in <cwd>/outbox/; after each turn
# the host delivers them to the chat (images as photos, the rest as documents) and
# clears them. Per-file size caps mirror the inbound attachment limits (handlers.py:
# 5 MB image / 20 MB doc); the count cap stops a runaway agent from spamming the chat.
_OUTBOX_DIRNAME = "outbox"
_OUTBOX_IMG_BYTES = 5 * 1024 * 1024
# was 20 MB (mirroring the inbound #37 PDF cap) — raised to match /export's cap and the
# Telegram bot document SEND limit (~50 MB) so the agent can archive the whole workdir
# into outbox/ as an /export alternative (#187 follow-up: owner asked 2026-06-17).
_OUTBOX_DOC_BYTES = 49 * 1024 * 1024
_OUTBOX_MAX_FILES = 10
_OUTBOX_IMG_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
# #167: only show the live context size in the working plate once it crosses this
# (small contexts aren't interesting and the early turns sit well below it).
_CTX_STATUS_MIN = 50_000

# #260: longest auto-name we adopt (Telegram session-label readability; manual
# /rename is uncapped — the user owns that).
_AI_TITLE_MAX = 64


def _read_ai_title(cwd: str | None, session_id: str | None) -> str | None:
    """#260: the auto-title Claude Code writes into the session transcript as
    ``{"type":"ai-title","aiTitle":…}`` — the same name shown in the browser. Returns
    the LAST one (it is rewritten as the topic evolves) or None.

    The transcript lives at ``<sid>/state/<encoded-cwd>/<session_id>.jsonl`` where the
    jail HOME is the sibling ``state`` dir (~/.claude/projects) and encoded-cwd is the
    cwd with every '/' turned into '-'. Cheap: a line at a time, JSON-parsing only the
    rare ai-title lines, keeping the last match."""
    if not cwd or not session_id:
        return None
    try:
        path = Path(cwd).parent / "state" / cwd.replace("/", "-") / f"{session_id}.jsonl"
        if not path.is_file():
            return None
        title = None
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                # Prefilter — skip the JSON parse unless this is an ai-title line.
                if '"ai-title"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if obj.get("type") == "ai-title" and obj.get("aiTitle"):
                    title = str(obj["aiTitle"]).strip()
        return title[:_AI_TITLE_MAX] if title else None
    except OSError:
        return None


def _ctx_total(info) -> int:
    """Extract the total-tokens-in-context number from a get_context_usage() result
    (a dict or object). 0 when unavailable."""
    if info is None:
        return 0
    for key in ("totalTokens", "used_tokens", "used"):
        v = info.get(key) if isinstance(info, dict) else getattr(info, key, None)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                pass
    return 0


# #172: the /test sample — 3 paragraphs + a 5×5 table + an x86 disasm snippet.
_DEMO_SAMPLE = """# 🧪 Streaming generation demo

This is the **first** paragraph: the bot generates text and the formatting (bold, `code`, _italic_) shows up RIGHT AWAY — like the GIF from Durov's post, instead of turning formatted only at the very end.

Second paragraph: lists stream already marked up too.

- first item
- second item
- third item

Third paragraph — below is a wider table and an x86 disassembly snippet (as when reversing a DLL). Watch it fill in ROW BY ROW as the reply streams, not snap in at the end.

| Address | Opcode | Mnemonic | Operands | Comment |
|:-------|:--------|:-----------|:-----------|:-------------|
| 0x1000 | 55 | push | ebp | prologue |
| 0x1001 | 8B EC | mov | ebp, esp | set up stack frame |
| 0x1003 | 83 EC 40 | sub | esp, 40h | reserve locals |
| 0x1006 | FF 75 0C | push | [ebp+0Ch] | arg: lpProcName |
| 0x1009 | FF 75 08 | push | [ebp+08h] | arg: hModule |
| 0x100C | FF 15 ... | call | ds:GetProcAddress | resolve import |
| 0x1012 | 85 C0 | test | eax, eax | null check |
| 0x1014 | 74 09 | jz | loc_load_fail | bail if not found |
| 0x1016 | 8B E5 | mov | esp, ebp | tear down frame |
| 0x1018 | 5D | pop | ebp | restore ebp |
| 0x1019 | C2 08 00 | retn | 8 | return, stdcall |

This paragraph streams AFTER the table — so by the time you read it the whole table is already rendered above, proving the table appears mid-stream and does not wait for the end of the message.

```asm
; --- excerpt: kernel32.dll!GetProcAddress thunk ---
push    ebp
mov     ebp, esp
sub     esp, 40h
mov     eax, [ebp+0Ch]          ; lpProcName
push    eax
mov     ecx, [ebp+08h]          ; hModule
push    ecx
call    ds:[__imp_GetProcAddress]
test    eax, eax
jz      short loc_load_fail
mov     esp, ebp
pop     ebp
retn    8
```

Finally an inline **SVG diagram** (#295): in a chat session the bot rasterizes this to a PNG and sends it as a photo. Example — a nightstand built from a washing-machine body, using the round porthole as the cabinet door:

```svg
<svg xmlns="http://www.w3.org/2000/svg" width="600" height="660" viewBox="0 0 600 660" font-family="sans-serif">
  <rect width="600" height="660" fill="#ffffff"/>
  <text x="300" y="34" font-size="20" font-weight="bold" text-anchor="middle" fill="#222">Nightstand from a washing-machine body</text>
  <text x="300" y="55" font-size="13" text-anchor="middle" fill="#666">sketch — front view</text>
  <rect x="110" y="86" width="320" height="24" rx="4" fill="#c9a36a" stroke="#8a6a3a" stroke-width="2"/>
  <rect x="130" y="110" width="280" height="420" rx="16" fill="#e9edf0" stroke="#49555f" stroke-width="3"/>
  <circle cx="270" cy="320" r="112" fill="#9aa7b0" stroke="#49555f" stroke-width="3"/>
  <circle cx="270" cy="320" r="84" fill="#cfe0ea" stroke="#7f8b94" stroke-width="2"/>
  <circle cx="368" cy="320" r="8" fill="#49555f"/>
  <rect x="160" y="530" width="30" height="42" fill="#3a4048"/>
  <rect x="380" y="530" width="30" height="42" fill="#3a4048"/>
  <g stroke="#9aa3ab" stroke-width="1">
    <line x1="430" y1="98" x2="448" y2="98"/><line x1="410" y1="180" x2="448" y2="180"/>
    <line x1="382" y1="300" x2="448" y2="272"/><line x1="410" y1="551" x2="448" y2="551"/>
  </g>
  <g font-size="13" fill="#3a4048">
    <text x="452" y="102">countertop</text><text x="452" y="184">washer shell</text>
    <text x="452" y="268">porthole &#8594; door</text>
    <text x="452" y="286" font-size="11" fill="#6a747c">&#216; &#8776; 300 mm</text>
    <text x="452" y="555">legs</text>
  </g>
  <g stroke="#c0392b" stroke-width="1.5">
    <line x1="84" y1="86" x2="84" y2="572"/><line x1="78" y1="86" x2="90" y2="86"/><line x1="78" y1="572" x2="90" y2="572"/>
    <line x1="130" y1="598" x2="410" y2="598"/><line x1="130" y1="592" x2="130" y2="604"/><line x1="410" y1="592" x2="410" y2="604"/>
  </g>
  <text x="66" y="330" font-size="13" fill="#c0392b" text-anchor="middle" transform="rotate(-90 66 330)">&#8776; 720 mm</text>
  <text x="270" y="618" font-size="13" fill="#c0392b" text-anchor="middle">&#8776; 600 mm</text>
</svg>
```"""
# #135: how often to poll the account /api/oauth/usage endpoint for the real % used.
# The 5h/7d windows move slowly, so 5 min keeps the footer/pinned fresh cheaply.
_USAGE_POLL_INTERVAL = 300.0
# #179: how often the idle-client reaper sweeps (seconds). Cheap — just compares
# timestamps + MemAvailable and aclose()s idle live clients over the TTL / cap.
_REAPER_INTERVAL = 60.0
# #178: how often the archive-retention purge sweeps (seconds). Deleted-session
# bundles are slow-moving, so once a day is plenty; it also runs once at startup.
_ARCHIVE_PURGE_INTERVAL = 86400.0
# #188: how often the schedule runner sweeps for due recurring prompts (seconds).
_SCHEDULE_INTERVAL = 30.0

# #236: cap on prompts WAITING behind a running turn (per session). A burst of
# follow-ups past this is rejected so a session can't accumulate an unbounded
# backlog; the running turn itself does not count. A small, fixed default.
# handle_text() return codes for the caller's queued/full UX (see #236):
MAX_QUEUED_MESSAGES = 5
SUBMIT_STARTED = 0      # ran immediately — the worker was idle
SUBMIT_QUEUE_FULL = -1  # rejected — too many prompts already waiting
# any value > 0 == queued behind a running turn, at that many waiting

# #245 → #227b: line-interactive commands (gh auth login, sudo, REPLs, `read`, password
# prompts) now WORK — the persistent shell forwards the next message as their input. Only
# FULL-SCREEN TUIs can't render in a chat bubble (capture is snapshot-and-send), so just those
# are refused. Heuristic on the FIRST command word (chains/pipes past it aren't inspected).
_SHELL_TUI_CMDS = {
    "vim", "vi", "nvim", "nano", "emacs", "pico", "less", "more", "man", "top", "htop",
    "btop", "watch", "tmux", "screen", "vimdiff",
}


def _is_fullscreen_tui_cmd(cmd: str) -> bool:
    """#245/#227b: True if the command is a full-screen TUI that can't render in a chat."""
    parts = cmd.split()
    if not parts:
        return False
    base = parts[0].rsplit("/", 1)[-1].lower()
    return base in _SHELL_TUI_CMDS


# #227b: while a program awaits input, these tokens let the user press keys that can't be typed
# in a chat (arrow-key list pickers like `gh auth login`, Enter to confirm, Ctrl-C). A message
# made ENTIRELY of these tokens is sent as the raw key bytes; anything else is sent as a line of
# text (+ Enter). Several tokens in one message chain, e.g. ".down .down .enter". The prefix is
# "." (NOT ":" — Telegram pops up emoji search on ":"); the inline keypad (shell_keypad) is the
# primary way to press keys, these tokens are the typed fallback.
_SHELL_KEYS = {
    ".enter": b"\r", ".return": b"\r", ".up": b"\x1b[A", ".down": b"\x1b[B",
    ".left": b"\x1b[D", ".right": b"\x1b[C", ".tab": b"\t", ".esc": b"\x1b",
    ".space": b" ", ".bs": b"\x7f", ".ctrl-c": b"\x03", ".c-c": b"\x03",
    ".pgup": b"\x1b[5~", ".pgdn": b"\x1b[6~", ".home": b"\x1b[H", ".end": b"\x1b[F",
}
# Inline-keypad buttons → the same key bytes, keyed by a short callback token (#227b UI).
_SHELL_CB_KEYS = {
    "up": b"\x1b[A", "down": b"\x1b[B", "left": b"\x1b[D", "right": b"\x1b[C",
    "enter": b"\r", "esc": b"\x1b", "tab": b"\t", "space": b" ", "bs": b"\x7f",
    "ctrlc": b"\x03", "pgup": b"\x1b[5~", "pgdn": b"\x1b[6~", "home": b"\x1b[H", "end": b"\x1b[F",
}


def shell_keypad(more: bool = False):
    """#227b: inline keypad for the interactive shell (Terminus-style key row). Each button
    sends one keystroke via the `shk:<key>` callback; ``more`` flips to the extra keys."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    b = InlineKeyboardButton
    if more:
        rows = [
            [b(text="␣ Space", callback_data="shk:space"), b(text="⌫ Bksp", callback_data="shk:bs"),
             b(text="« keys", callback_data="shk:less")],
            [b(text="⇞ PgUp", callback_data="shk:pgup"), b(text="⇟ PgDn", callback_data="shk:pgdn")],
            [b(text="⤒ Home", callback_data="shk:home"), b(text="⤓ End", callback_data="shk:end")],
        ]
    else:
        rows = [
            [b(text="⎋ Esc", callback_data="shk:esc"), b(text="↑", callback_data="shk:up"),
             b(text="⏎ Enter", callback_data="shk:enter")],
            [b(text="←", callback_data="shk:left"), b(text="↓", callback_data="shk:down"),
             b(text="→", callback_data="shk:right")],
            [b(text="⇥ Tab", callback_data="shk:tab"), b(text="^C", callback_data="shk:ctrlc"),
             b(text="⋯ more", callback_data="shk:more")],
        ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _normalize_shell_cmd(cmd: str) -> str | None:
    """#267: phone keyboards auto-capitalize the first word, so a user typing `ls` / `cat x`
    sends `Ls` / `Cat x` and bash returns "command not found". Return the command with ONLY
    its first TOKEN (the command name) lowercased, or None if nothing would change. Arguments,
    paths and filenames are left untouched (they stay case-sensitive). Used as a retry ONLY
    after the original command returns 127 (not-found), so a real command is never altered and
    a case-sensitive name can't be confused — nothing ran on a 127."""
    if not cmd or not cmd[0].isascii() or not cmd[0].isupper():
        return None
    parts = cmd.split(None, 1)
    head = parts[0].lower()
    if head == parts[0]:
        return None
    return head + (" " + parts[1] if len(parts) > 1 else "")


def _shell_input_keys(text: str) -> bytes | None:
    """#227b: parse a key-token message into raw bytes, or None if it isn't all key tokens."""
    toks = text.split()
    if not toks:
        return None
    out = b""
    for t in toks:
        k = _SHELL_KEYS.get(t.lower())
        if k is None:
            return None
        out += k
    return out


@dataclass
class _ThreadRecord:
    """In-memory orchestration state for one isolated thread."""

    session: ClaudeSession | None = None
    # Snapshot of the config the live session was built for, so we can detect
    # when /mode, /model or /cwd require a rebuild.
    mode: str | None = None
    model: str | None = None
    cwd: str | None = None
    permission_mode: str | None = None
    big_memory: bool | None = None
    # Per-user GLOBAL MEMORY resolved for this session's owner; a change (owner
    # toggles it) triggers a rebuild so setting_sources flips.
    global_memory: bool | None = None
    # Pro-command options the live session was built for (#23); a change rebuilds.
    effort: str | None = None
    max_turns: int | None = None
    add_dirs: tuple = ()
    fork: bool = False
    # Per-session enabled tools the live session was built for (#129); a change
    # rebuilds. A tuple (or None = the mode's default universe) for cheap comparison.
    tools_enabled: tuple | None = None
    # Per-USER tool cap (owner-set, #131) the live session was built for; a change
    # (owner edits the user's cap) rebuilds. Tuple, or None = uncapped.
    tool_cap: tuple | None = None

    # Queue items are (qid, text, attachments) tuples — qid is a per-thread
    # monotonic id (so a single queued follow-up can be cancelled by id, #13);
    # attachments is None or a list of Anthropic content-block dicts.
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    next_qid: int = 1
    worker: asyncio.Task | None = None
    streamer: Streamer | None = None
    last_activity: float = field(default_factory=time.monotonic)
    # #182: per-user idle-TTL (seconds) resolved onto the record at build — None →
    # global default; 0 → never reap (owner set ∞). The reaper reads this per record.
    idle_ttl: float | None = None
    rate: object | None = None  # latest RateLimitInfo seen for this thread
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # Per-thread display flags toggled via commands; default to today's
    # behavior (live streaming). last_prompt holds the most recent submitted
    # prompt for this thread (used by /retry).
    stream_enabled: bool = True
    # #224: shell-mode overlay (route text → jailed command). Mirrors the persisted
    # ThreadState.shell_mode; re-synced on rebuild like stream_enabled.
    shell_mode: bool = False
    # #229: live task-list card toggle (code-only). Re-synced from the effective settings
    # on every _ensure (no rebuild needed — it's a display option). Default OFF.
    todo_card: bool = False
    # #260: current session label + whether auto-naming is still on. Mirror the persisted
    # ThreadState (re-synced every _ensure); the turn-end auto-namer compares against name
    # to write only on change and skips entirely once name_auto is cleared by /rename.
    name: str | None = None
    name_auto: bool = True
    # #227b: True when the persistent shell paused for interactive input — the NEXT message
    # is forwarded to the running program instead of being run as a new command.
    shell_awaiting: bool = False
    # #279: the message currently bearing the inline keypad + its rendered body, so /shell
    # OFF can strip the now-stale keypad and /shell ON can restore it where input paused.
    shell_kb_chat: int | None = None
    shell_kb_msg: int | None = None
    shell_last_render: str | None = None
    # Most recent (text, attachments) submitted for this thread (used by /retry).
    last_prompt: tuple | None = None
    # #167/#168: effective forced-on toggles the live session was built for, plus the
    # last-known context size (captured at turn end → shown in the next working plate).
    auto_compact: bool = True
    ctx_status: bool = True
    last_context_tokens: int = 0
    # #166: the live warm-cache countdown message + its ticking task (cancelled when
    # the next turn resets the window).
    hot_cache_msg_id: int | None = None
    hot_cache_task: asyncio.Task | None = None


def _coerce_perm(mode: str | None) -> str:
    """#278: resolve a session's permission mode to a current value. The legacy/unset
    "default" (pre-#212 = prompt for EVERY tool, incl. file edits) is no longer a
    selectable mode, so it maps to the #212 "acceptEdits" baseline (file edits + ordinary
    in-jail Bash auto-run; the #119 jail is the containment). Other modes pass through."""
    return "acceptEdits" if (not mode or mode == "default") else mode


def _send_thread_id(thread_id: int) -> int | None:
    """Map a session key to a Telegram message_thread_id.

    Only POSITIVE keys are real forum topics. General (0) and negative DM-session
    keys both map to None (no message_thread_id — they post to the bare chat).
    """
    return thread_id if thread_id > 0 else None


class SessionManager:
    """Owns one isolated worker pipeline per forum topic."""

    def __init__(self, bot, settings, gate: PermissionGate, allowlist=None) -> None:
        self.bot = bot
        self.settings = settings
        self.gate = gate
        # Allowlist (optional — omitted in some tests): resolves per-user
        # build-affecting prefs, currently GLOBAL MEMORY for a session's owner.
        # None → every session stays isolated (setting_sources=[]).
        self.allowlist = allowlist
        self._records: dict[int, _ThreadRecord] = {}

        # Account-wide subscription rate-limit windows, keyed by rate_limit_type.
        self.rate_by_type: dict[str, object] = {}
        # Usage display: one of "off", "footer", "pinned", "both".
        self.usage_mode: str = "footer"
        # Global rendering toggle (/codesplit, owner): send each fenced code block
        # as its own message (default — easy mobile copy) vs inline. Persisted.
        self.split_code_messages: bool = True
        # #175: global ON/OFF for the "Working…" + Stop control plate. The owner can
        # disable it to A/B test whether it makes generation visibly jump. Persisted.
        self.working_plate: bool = True
        # Reveal pacing for the dormant write-head (groups). Fixed at "normal":
        # the caret + its /settings speed page were retired (#59, #60), so this is
        # no longer user-configurable. DM streaming is native drafts (Telegram-
        # paced) and uses no caret, so this only affects the frozen group path.
        self.caret_speed: str = "normal"
        # The chat where the bot is talking (used for the pinned usage message).
        self._main_chat_id: int | None = None
        # (chat_id, message_id) of the pinned usage message, if any.
        self._pinned: tuple[int, int] | None = None
        # Fingerprint of the last rate snapshot we persisted + pinned, so we can
        # skip the DB write and pinned-message edit when a rate event repeats
        # data we already recorded (see _run_one's rate_limit branch).
        self._last_rate_sig: tuple | None = None
        # #137: True while we are showing a SYNTHESIZED "limited" five_hour window
        # (set when a turn fails on the subscription limit — the rate EVENTS keep
        # reporting "allowed", so we fabricate the limited state). Cleared on the
        # next successful turn so the honest display self-heals.
        self._synth_limit: bool = False
        # #135: background task polling the account /api/oauth/usage endpoint for the
        # REAL per-window % (the SDK rate-events only send it near a limit).
        self._usage_task: asyncio.Task | None = None
        # #179/#326: concurrency / RAM management. the fair _turn_gate caps SIMULTANEOUS active turns
        # (the generation spike); _reaper_task periodically aclose()s idle live clients
        # (each ~400–600 MB) so N idle sessions don't pin N processes until restart.
        # History lives on disk (transcript) → `resume` rebuilds it; nothing is lost.
        # Resolve caps with getattr fallbacks so a minimal settings stub (tests) still
        # constructs; the real Settings always carries them (config.load_settings).
        self._max_live: int = int(getattr(settings, "max_live_clients", 4) or 4)
        # was `..., 900) or 900` — aligned to the 6-min config default so 6 min is the
        # single default everywhere (this fallback only bites a settings stub lacking the attr).
        self._idle_ttl: float = float(getattr(settings, "idle_ttl_sec", 360) or 360)
        # #261: idle → fresh-session window (seconds); 0 = off. Per-user override → idle_reset_min.
        self._idle_reset: float = float(getattr(settings, "idle_reset_sec", 1800) or 0)
        self._min_free_mb: int = int(getattr(settings, "min_free_mb", 400) or 400)
        # #274: persistent shells preserved across a client reap, keyed by thread_id →
        # (shell, monotonic_stash_ts). Reaped on their own (much longer) shell TTL, on
        # session reset/delete, or at shutdown. 0 = keep until delete.
        self._detached_shells: dict[int, tuple] = {}
        self._shell_ttl: float = float(getattr(settings, "shell_ttl_sec", 86400) or 0)
        # #326: FAIR admission (round-robin by user) instead of a plain Semaphore, so one user's
        # burst of sessions can't occupy every slot and starve others.
        # was: self._turn_sem = asyncio.Semaphore(max_concurrent_turns)
        self._turn_gate: FairAdmission = FairAdmission(
            int(getattr(settings, "max_concurrent_turns", 4) or 4)
        )
        # #325: graceful drain — on shutdown we stop STARTING new turns and wait for the
        # in-flight ones to finish (so a restart doesn't kill a turn mid-generation / tear its
        # transcript). `_active_turns` counts running _run_one()s; `_idle_event` is set when
        # none are; `_draining` makes each per-thread worker stop pulling new queued turns.
        self._draining: bool = False
        self._active_turns: int = 0
        self._idle_event: asyncio.Event = asyncio.Event()
        self._idle_event.set()
        self._reaper_task: asyncio.Task | None = None
        # #178: background task purging expired archive bundles (retention).
        self._archive_purge_task: asyncio.Task | None = None
        # #188: background task firing due recurring schedules.
        self._schedule_task: asyncio.Task | None = None
        # #191: background task refreshing the subscription OAuth token before it
        # expires (the on-disk token has a hard ~8h life; nothing else rotates it).
        self._token_refresh_task: asyncio.Task | None = None

    # ------------------------------------------------------------------ records

    def _record(self, thread_id: int) -> _ThreadRecord:
        """Return (creating if needed) the per-thread record. Never shared."""
        rec = self._records.get(thread_id)
        if rec is None:
            rec = _ThreadRecord()
            self._records[thread_id] = rec
        return rec

    def _default_cwd(self, thread_id: int) -> str:
        """Per-thread working directory: BASE_WORKDIR/<sid> (#140).

        Named by the stable PUBLIC session id (session_sid) rather than the raw
        thread_id so the on-disk name matches the id shown in /sessions / exports
        and never leaks the internal numbering.
        """
        # was: return str(Path(self.settings.base_workdir) / str(thread_id))
        #      — replaced for #140 (sid-named workdirs)
        # #181: nested layout — cwd is <sid>/work (agent's writable dir); the jail
        # state/transcript live in the SIBLING <sid>/state (not bound into the jail).
        # #332: dir named by the PUBLIC ULID (was db.session_sid — the legacy 6-hex).
        return str(Path(self.settings.base_workdir) / db.session_pubid(thread_id) / "work")

    # --------------------------------------------------------------- session mgmt

    def _resolve_global_memory(self, state: db.ThreadState) -> bool:
        """Whether THIS session should load global (~/.claude) memory — a per-USER
        owner-granted opt-out of isolation. Resolved from the session OWNER (the DM
        creator, == chat_id for DM rows). False when no allowlist is wired."""
        if not self.allowlist:
            return False
        owner_uid = state.created_by if state.created_by else state.chat_id
        try:
            return bool(self.allowlist.global_memory_of(owner_uid, None))
        except Exception:
            return False

    def _resolve_sandbox(self, state: db.ThreadState) -> bool:
        """Whether THIS session's code `claude` runs in the bubblewrap jail (#138).

        Routed through the unified settings registry so the confusing global-vs-
        session model has ONE source of truth and the negative per-session override
        (no_sandbox) inversion lives inside the adapter, not here. The registry walk
        SESSION→USER→GLOBAL is exactly equivalent to the old expression
        ``settings.sandbox_code and not state.no_sandbox`` (see the unit test).
        USER scope is unused at the session layer (no preloaded user-defaults), so
        it falls through to GLOBAL == settings.sandbox_code unless the session set
        no_sandbox (→ False).
        """
        ctx = settings_schema.make_ctx(state=state, settings=self.settings)
        value, _scope = settings_schema.resolve(settings_schema.get("sandbox"), ctx)
        return bool(value)

    def _resolve_tool_cap(self, state: db.ThreadState):
        """The per-user TOOL CAP (owner-set) for this session's OWNER, or None =
        uncapped (#131). Resolved from the allowlist like global memory."""
        if not self.allowlist:
            return None
        owner_uid = state.created_by if state.created_by else state.chat_id
        try:
            return self.allowlist.tool_cap_of(owner_uid, None)
        except Exception:
            return None

    async def _resolve_idle_ttl(self, state: db.ThreadState) -> float:
        """Per-user idle-TTL (seconds) for the session OWNER (#182). Reads the
        per-uid KV ``idle_ttl_min`` (minutes): None → global default; ≤0 → never
        reap (owner set ∞); N → N*60. Stored on the record for the reaper to read."""
        owner_uid = state.created_by if state.created_by else state.chat_id
        raw = None
        if owner_uid is not None:
            with contextlib.suppress(Exception):
                raw = await db.get_user_default(owner_uid, "idle_ttl_min")
        if raw is None:
            return float(self._idle_ttl)
        try:
            minutes = int(raw)
        except (TypeError, ValueError):
            return float(self._idle_ttl)
        return 0.0 if minutes <= 0 else float(minutes * 60)

    async def idle_reset_seconds(self, owner_uid: int | None) -> float:
        """#261/#266: the idle→new-session window (seconds) for a session OWNER. Reads the
        per-uid KV ``idle_reset_min`` (minutes): None → the global default (admin-set, kv
        ``idle_reset_sec``, mirrored on ``self._idle_reset``); ≤0 → never rotate; N → N*60.
        The handler reads this to decide whether the next message starts a new session."""
        raw = None
        if owner_uid is not None:
            with contextlib.suppress(Exception):
                raw = await db.get_user_default(owner_uid, "idle_reset_min")
        if raw is None:
            return float(self._idle_reset)
        try:
            minutes = int(raw)
        except (TypeError, ValueError):
            return float(self._idle_reset)
        return 0.0 if minutes <= 0 else float(minutes * 60)

    async def rotate_in_place(self, thread_id: int) -> None:
        """#266 fallback: clear a session's conversation context WITHOUT creating a new
        entry — NULL the resume ids (keeping the workdir, transcript, and message log) and
        drop the live client so the next message rebuilds fresh. Used only when an idle
        rotation can't mint a new session (the user is at their session cap with nothing
        disposable to evict), so we never silently delete a session that has content."""
        with contextlib.suppress(Exception):
            await db.rotate_session_for_idle(thread_id)
        rec = self._records.get(thread_id)
        if rec is not None and rec.session is not None:
            async with rec.lock:
                if rec.session is not None:
                    old = rec.session
                    rec.session = None
                    # #289: preserve a live jailed shell across the in-place rotation too
                    # (same as the reaper path) — a running command + cd/env survive the
                    # context reset and re-attach on the next rebuild. was: aclose() only,
                    # which killed the shell on rotate-in-place.
                    if getattr(old, "has_live_shell", None) and old.has_live_shell():
                        sh = old.detach_shell()
                        if sh is not None:
                            self._detached_shells[thread_id] = (sh, time.monotonic())
                    with contextlib.suppress(Exception):
                        await old.aclose()

    def _raw_settings(self, state: db.ThreadState) -> dict:
        """The stored per-session values, used as the fallback when no allowlist is
        wired (e.g. unit tests) — keeps behaviour identical to reading ``state``."""
        return {
            "model": state.model, "effort": state.effort,
            "permission_mode": _coerce_perm(state.permission_mode),  # #278
            "max_turns": state.max_turns, "big_memory": state.big_memory,
        }

    async def _effective_settings(self, state: db.ThreadState) -> dict:
        """Resolve the EFFECTIVE setting values for this session's OWNER through the
        access model (#151 / 151c), so soft-revoke binds at CONSUMPTION — not just in
        the /settings hub. An option the owner set to Read-only/Hidden (or never
        delegated) falls back to the GLOBAL default even if a stale per-session or
        personal override is stored; only a DELEGATED option counts the user's own
        value. Also enforces the capability gates (151d): ``max`` effort requires the
        per-user grant, ``full-access`` (bypassPermissions) is owner-only. Falls back
        to the raw stored values when no allowlist is wired (unit tests)."""
        if not self.allowlist:
            return self._raw_settings(state)
        owner_uid = state.created_by if state.created_by else state.chat_id
        is_owner = owner_uid is not None and owner_uid == getattr(self.settings, "owner_id", None)
        if is_owner:
            role = settings_schema.Role.OWNER
        elif self.allowlist.level_of(owner_uid, None) == "code":
            role = settings_schema.Role.CODE
        else:
            role = settings_schema.Role.CHAT
        access_base: dict = {}
        with contextlib.suppress(Exception):
            access_base = await db.get_access_overrides()
        access_exc: dict = {}
        with contextlib.suppress(Exception):
            access_exc = self.allowlist.access_of(owner_uid, None)
        user_defaults: dict = {}
        for skey in ("model", "effort", "permission_mode", "max_turns", "memory",
                     "auto_compact", "ctx_status", "todo_card"):  # #167/#168/#229
            with contextlib.suppress(Exception):
                user_defaults[skey] = await db.get_user_default(owner_uid, skey)
        ctx = settings_schema.make_ctx(
            state=state, user_id=owner_uid, role=role, settings=self.settings,
            allowlist=self.allowlist, user_defaults=user_defaults,
            access_base=access_base, access_exceptions=access_exc)

        def eff(key):
            v, _ = settings_schema.resolve_effective(settings_schema.get(key), ctx)
            return v

        out = {
            "model": eff("model") or self.settings.default_model,
            "effort": eff("effort"),
            # was `or "default"` — #212 new baseline (jail-backed); see settings_schema.
            # #278: a stored legacy "default" (pre-#212 ask-for-EVERY-tool) is no longer a
            # selectable mode → coerce it to the acceptEdits baseline so file edits/creation
            # auto-run without a prompt (belt-and-suspenders alongside the db.py migration).
            "permission_mode": _coerce_perm(eff("permission_mode")),
            "max_turns": eff("max_turns"),
            "big_memory": bool(eff("memory")),
            # #167/#168: forced-on (default True) unless the owner delegated a disable.
            "auto_compact": bool(eff("auto_compact")),
            "ctx_status": bool(eff("ctx_status")),
            "todo_card": bool(eff("todo_card")),  # #229
        }
        # 151d — capability gates applied to the EFFECTIVE values (mirror the per-turn
        # gate in handlers._access_block, so a revoked grant takes effect at run time).
        # #185: dropped the `is_owner or` bypass so an owner self-revoke (allow_max_effort
        # =False) downgrades the owner's run too; the getter still defaults the owner to True.
        # was: if out["effort"] == "max" and not (is_owner or self.allowlist.allow_max_effort_of(owner_uid, None)):
        if out["effort"] == "max" and not self.allowlist.allow_max_effort_of(owner_uid, None):
            out["effort"] = "xhigh"
        if out["permission_mode"] == "bypassPermissions" and not is_owner:
            # Soft-revoked full-access reverts to the normal non-owner baseline,
            # which is acceptEdits since #212 (was "default") — same as a fresh user.
            out["permission_mode"] = "acceptEdits"
        return out

    def _owner_level(self, state: db.ThreadState) -> str:
        """#276: the session owner's access level — "code" (owner, or a code-grant user)
        or "chat". Used to tell the model whether the user can self-upgrade via /code."""
        owner_uid = state.created_by if state.created_by else state.chat_id
        if owner_uid is not None and owner_uid == getattr(self.settings, "owner_id", None):
            return "code"
        if self.allowlist is not None:
            with contextlib.suppress(Exception):
                if self.allowlist.level_of(owner_uid, None) == "code":
                    return "code"
        return "chat"

    def _build_session(self, state: db.ThreadState, eff: dict | None = None) -> ClaudeSession:
        """Construct a fresh ClaudeSession for a thread from its stored state, using
        the EFFECTIVE (access-resolved) setting values in ``eff`` (#151/151c) for
        model / permission_mode / big_memory / effort / max_turns. Falls back to the
        raw stored values when ``eff`` is None (no allowlist wired).

        Code mode gets the per-thread permission callback and resumes the stored
        code_session_id (so a rebuilt client continues the prior session). Chat
        mode runs tool-free and does not resume a code session.
        """
        eff = eff or self._raw_settings(state)
        send_tid = _send_thread_id(state.thread_id)
        if state.mode == "code":
            # Pass send_tid (where to post) AND the unique session key (for gate
            # bookkeeping/cancellation that must not collide across DM/General).
            # The gate uses the EFFECTIVE permission_mode (a soft-revoked full-access
            # reverts to asking).
            can_use_tool = self.gate.make_callback(
                state.chat_id, send_tid, state.thread_id, eff["permission_mode"],
                cwd=state.cwd,  # #204: relativize tool-path previews to the workdir
            )
            resume_id = state.code_session_id
        else:
            can_use_tool = None
            # Chat sessions are DURABLE: always resume the persisted chat session
            # id (saved every turn), so context survives a bot restart / a /stop —
            # this matches the mental model that a named, navigable session keeps
            # its history. big_memory is now ONLY the 1M-context-window toggle, not
            # what decides whether we resume. Use /reset to start fresh.
            resume_id = state.chat_session_id

        return ClaudeSession(
            mode=state.mode,
            model=eff["model"],
            cwd=state.cwd,
            can_use_tool=can_use_tool,
            resume_session_id=resume_id,
            permission_mode=eff["permission_mode"],
            big_memory=eff["big_memory"],
            global_memory=self._resolve_global_memory(state),
            tools_enabled=state.tools_enabled,
            tool_cap=self._resolve_tool_cap(state),
            effort=eff["effort"],
            max_turns=eff["max_turns"],
            add_dirs=state.add_dirs,
            fork=state.fork_pending,
            # was: sandbox=self.settings.sandbox_code and not state.no_sandbox
            #      — routed through the unified settings registry for #138 so the
            #      global-vs-session sandbox model has one source of truth.
            sandbox=self._resolve_sandbox(state),
            sandbox_uid=self.settings.sandbox_uid,
            sandbox_allow_exec=self.settings.sandbox_allow_exec,
            # #119b: when the credential broker is on, the jail gets a dummy token +
            # ANTHROPIC_BASE_URL pointing at the host broker (the real token stays out).
            cred_broker_url=(f"http://127.0.0.1:{self.settings.cred_broker_port}"
                             if getattr(self.settings, "cred_broker", False) else None),
            # #119c/#119e: egress allowlist + per-jail DoS limits + seccomp. getattr-guarded
            # so a minimal test Settings stub still constructs. cpu% → cpu.max "quota period"
            # (100% = one core); mem MB → memory.max bytes.
            egress=getattr(self.settings, "sandbox_egress", False),
            egress_proxy_url=(f"http://127.0.0.1:{self.settings.egress_proxy_port}"
                              if getattr(self.settings, "sandbox_egress", False) else None),
            sbx_mem_max=(str(self.settings.sandbox_mem_mb * 1024 * 1024)
                         if getattr(self.settings, "sandbox_mem_mb", 0) else None),
            sbx_cpu_max=(f"{self.settings.sandbox_cpu_percent * 1000} 100000"
                         if getattr(self.settings, "sandbox_cpu_percent", 0) else None),
            sbx_pids_max=getattr(self.settings, "sandbox_pids_max", 0),
            seccomp_path=((getattr(self.settings, "sandbox_seccomp_path", "") or None)
                          if getattr(self.settings, "sandbox_seccomp", False) else None),
            per_session_uid=getattr(self.settings, "sandbox_per_session_uid", False),
            uid_base=getattr(self.settings, "sandbox_uid_base", 700000),
            uid_range=getattr(self.settings, "sandbox_uid_range", 60000),
            extra_blocked_keywords=getattr(self.settings, "extra_blocked_keywords", None),
            auto_compact=eff.get("auto_compact", True),  # #168
            user_level=self._owner_level(state),  # #276: drives the "this session" prompt note
        )

    async def _get_session(
        self, rec: _ThreadRecord, state: db.ThreadState
    ) -> ClaudeSession:
        """Return the live session, rebuilding it if config drifted or absent.

        A rebuild aclose()s the old client first so we never leak a connection,
        and never share an SDK client across distinct configs.
        """
        gmem = self._resolve_global_memory(state)
        tkey = tuple(state.tools_enabled) if state.tools_enabled is not None else None
        cap = self._resolve_tool_cap(state)
        capkey = tuple(cap) if cap is not None else None
        # #151/151c: compare against the EFFECTIVE (access-resolved) values, not the
        # raw stored ones — so an owner access/global change (or a revoked grant)
        # triggers a rebuild and applies from the next message.
        eff = await self._effective_settings(state)
        rec.idle_ttl = await self._resolve_idle_ttl(state)  # #182: per-user idle-TTL
        rec.todo_card = bool(eff.get("todo_card", False))   # #229: display toggle, no rebuild
        rec.name = state.name                                # #260: for the auto-namer
        rec.name_auto = state.name_auto                      # #260: stop once /rename pins
        needs_rebuild = (
            rec.session is None
            or rec.mode != state.mode
            or rec.model != eff["model"]
            or rec.cwd != state.cwd
            or rec.permission_mode != eff["permission_mode"]
            or rec.big_memory != eff["big_memory"]
            or rec.global_memory != gmem
            or rec.tools_enabled != tkey
            or rec.tool_cap != capkey
            or rec.effort != eff["effort"]
            or rec.max_turns != eff["max_turns"]
            or rec.add_dirs != tuple(state.add_dirs)
            or rec.fork != state.fork_pending
            or rec.auto_compact != eff.get("auto_compact", True)  # #168: env changes
        )
        if needs_rebuild:
            # NEVER aclose/rebuild the client while a turn is running on it: that
            # disconnects it mid-answer and kills the in-flight turn. If a worker
            # is busy, keep the current session — the running turn and any queued
            # prompts finish under the current settings — and let the rebuild
            # happen on the next message once the worker is idle. (A first-ever
            # build, where rec.session is None, still proceeds: there is no live
            # turn to protect.)
            worker = rec.worker
            busy = worker is not None and not worker.done()
            if busy and rec.session is not None:
                return rec.session
            # #274: keep a live persistent shell alive across this rebuild too (config
            # drift, e.g. a model change, otherwise killed it via aclose).
            pending_shell = None
            if rec.session is not None:
                old = rec.session
                rec.session = None
                if getattr(old, "has_live_shell", None) and old.has_live_shell():
                    pending_shell = old.detach_shell()
                with contextlib.suppress(Exception):
                    await old.aclose()
            rec.session = self._build_session(state, eff)
            # Re-attach a shell preserved from this rebuild OR stashed earlier by the reaper.
            # #289: this carries the live shell even across a code→chat mode switch. That is
            # DELIBERATE — a chat session never drives or closes the shell, but keeping it
            # preserves the user's cd/env + any running command for a switch back to code,
            # and it is still reaped on aclose / shell TTL / session delete (no leak).
            self._reattach_shell(rec.session, state.thread_id, pending_shell)
            rec.mode = state.mode
            rec.model = eff["model"]
            rec.cwd = state.cwd
            rec.permission_mode = eff["permission_mode"]
            rec.big_memory = eff["big_memory"]
            rec.global_memory = gmem
            rec.tools_enabled = tkey
            rec.tool_cap = capkey
            rec.effort = eff["effort"]
            rec.max_turns = eff["max_turns"]
            rec.add_dirs = tuple(state.add_dirs)
            rec.fork = state.fork_pending
            rec.auto_compact = eff.get("auto_compact", True)   # #168
            rec.ctx_status = eff.get("ctx_status", True)       # #167
            # Restore the persisted /stream preference (survives restart).
            rec.stream_enabled = state.stream_enabled
            rec.shell_mode = state.shell_mode  # #224: re-sync the shell overlay flag
        return rec.session

    # ------------------------------------------------------------------ entry

    async def handle_text(
        self,
        chat_id: int,
        thread_id: int,
        text: str,
        attachments: list | None = None,
    ) -> int:
        """Queue a prompt (optionally with attachments) and ensure the worker runs.

        thread_id is the real storage key (0 for General). attachments, when given,
        is a list of Anthropic content-block dicts (image/document) sent with the
        turn. If no run is in progress the worker starts and the prompt runs now;
        if a run is in progress the prompt is enqueued and executes next in the SAME
        session (task chaining).

        #236: returns a status for the caller's queued/full UX —
        ``SUBMIT_STARTED`` (0) when it runs immediately, a positive count of prompts
        now WAITING when it was queued behind a running turn, or ``SUBMIT_QUEUE_FULL``
        (-1) when the per-session backlog cap is hit and the prompt was NOT enqueued.
        """
        # Remember the chat we are talking in so the pinned usage message can be
        # created/updated there. Persist only on change (best effort).
        if self._main_chat_id != chat_id:
            self._main_chat_id = chat_id
            with contextlib.suppress(Exception):
                await db.set_kv("main_chat_id", str(chat_id))

        default_cwd = self._default_cwd(thread_id)
        state = await db.ensure_thread(
            thread_id, chat_id, self.settings.default_model, default_cwd
        )

        # #68: resolve the record, acquire its lock, then RE-CHECK it is still the
        # live one. reset() pops the record from _records while holding its lock; a
        # handle_text that resolved `rec` before that pop but blocked on the lock
        # would otherwise build a session + spawn a worker on the orphaned record
        # (invisible to stop/reset/status). If it was popped, retry with the fresh
        # record so the prompt runs on a live rec rather than being lost.
        while True:
            rec = self._record(thread_id)
            async with rec.lock:
                if self._records.get(thread_id) is not rec:
                    continue  # reset() popped it while we waited — retry
                # #236: is a turn currently running on this session? If so this prompt
                # waits behind it (task chaining); enforce the backlog cap and report
                # the queued depth so the caller can ack. The running turn already
                # pulled its item off the queue, so qsize() == prompts still waiting.
                busy = rec.worker is not None and not rec.worker.done()
                if busy and rec.queue.qsize() >= MAX_QUEUED_MESSAGES:
                    return SUBMIT_QUEUE_FULL
                # #266: idle handling moved UP to the handler (_session_key_for_turn),
                # which starts a brand-new session on a long idle gap instead of resetting
                # this one in place — so the old conversation is preserved in /sessions.
                # Build/refresh the session up front so config changes apply before
                # the prompt is enqueued and consumed by the worker.
                await self._get_session(rec, state)
                qid = rec.next_qid
                rec.next_qid += 1
                await rec.queue.put((qid, text, attachments))
                # Remember the latest submitted prompt (+attachments) for this thread.
                rec.last_prompt = (text, attachments)
                if rec.worker is None or rec.worker.done():
                    rec.worker = asyncio.create_task(
                        self._worker(thread_id, chat_id)
                    )
                # #236: 0 when it runs now (idle worker), else the waiting count.
                return rec.queue.qsize() if busy else SUBMIT_STARTED

    # ------------------------------------------------------------------ worker

    async def _worker(self, thread_id: int, chat_id: int) -> None:
        """Drain the thread's queue serially, streaming each turn.

        Exactly one turn runs at a time per thread. On /stop the worker task is
        cancelled; we surface a stopped notice and let the finally block clear
        the current-task handle so the next message starts a fresh worker.
        """
        rec = self._record(thread_id)
        send_tid = _send_thread_id(thread_id)
        try:
            while True:
                # #325: graceful drain — let the in-flight turn (the loop body below) run to
                # completion, but start NO new queued turns once draining (shutdown).
                if self._draining:
                    break
                try:
                    _qid, prompt, attachments = rec.queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

                interval, step = resolve_speed(self.caret_speed)
                # DM sessions (negative keys) stream via native drafts — the single
                # streaming standard. The General topic (0) and forum topics (>0)
                # have no drafts (TEXTDRAFT_PEER_INVALID) and Telegram caps edits at
                # ~1/sec, so the write-head path below is DORMANT (kept only for the
                # frozen supergroup mode). There is no separate "drafts" toggle:
                # whether to stream at all is the per-session stream_enabled flag.
                # Stream DM replies via rich message DRAFTS (the smooth native typewriter),
                # by design — this is the streaming standard. (Telegram may currently render
                # them as whole messages client-side until it restores bot draft previews;
                # we keep drafts regardless — write-head is a worse fallback we don't use.)
                use_drafts = thread_id < 0
                # #166: a new turn resets the warm-cache window → drop the previous
                # turn's ticking countdown and its message.
                self._cancel_hot_cache(rec, chat_id)
                # #164: working-plate note (own limit ≥50% / owner account). Only the
                # DM draft path shows the Stop-control plate, so compute it there only.
                working_note = ""
                if use_drafts:
                    working_note = await self._working_note(
                        chat_id, i18n.cached_lang(chat_id), rec
                    )
                streamer = Streamer(
                    self.bot,
                    chat_id,
                    send_tid,
                    frame_interval=interval,
                    base_step=step,
                    use_drafts=use_drafts,
                    split_code_messages=self.split_code_messages,
                    working_note=working_note,
                    controllable=self.working_plate,   # #175: global plate on/off
                )
                rec.streamer = streamer
                try:
                    # #179: global concurrency admission — relieve memory if low and
                    # cap simultaneous active turns so parallel sessions can't OOM the
                    # box; a contended slot tells the user the turn is queued. The
                    # per-thread queue still serializes THIS thread's own turns.
                    await self._admit_turn(thread_id, chat_id, send_tid)
                    # #326: FAIR admission — round-robin by user (chat_id) so a multi-session
                    # burst can't starve another user; the per-thread queue still serializes THIS
                    # thread's turns. Paired with the release() in the finally below.
                    await self._turn_gate.acquire(chat_id)
                    # #325: track in-flight turns so a graceful drain can wait them out.
                    self._active_turns += 1
                    self._idle_event.clear()
                    try:
                        await self._run_one(
                            rec, thread_id, prompt, attachments, streamer
                        )
                    finally:
                        self._active_turns -= 1
                        if self._active_turns <= 0:
                            self._active_turns = 0
                            self._idle_event.set()
                        self._turn_gate.release()  # #326
                    # #187: deliver any files the agent staged in outbox/ this turn.
                    # OUTSIDE the turn-sem (uploads shouldn't hold a concurrency slot) but
                    # INSIDE the per-thread loop, so it's serialized before the next queued
                    # turn. Skipped if _run_one raised (the turn didn't finish cleanly).
                    with contextlib.suppress(Exception):
                        await self._deliver_outbox(rec, chat_id, send_tid)
                finally:
                    rec.streamer = None
                    rec.queue.task_done()
        except asyncio.CancelledError:
            # The worker is only cancelled by reset()/aclose() now — graceful
            # /stop interrupts instead of cancelling. Both paths already surface
            # their own message (reset() via its "/reset" reply; shutdown needs
            # none), so we tear down SILENTLY here rather than emit a duplicate
            # "Execution stopped." notice.
            raise
        finally:
            # Only release our own handle (a newer worker may already exist).
            if rec.worker is asyncio.current_task():
                rec.worker = None

    async def _split_live_blocks(
        self, rec: _ThreadRecord, streamer: Streamer, running_text: str
    ) -> tuple[str, bool]:
        """Code mode: when a fenced code block has fully closed mid-stream, commit
        it (and any prose before it) as its own copyable message(s) LIVE and keep
        streaming the tail (#93).

        Returns (running_text, flushed): running_text trimmed to the remainder when
        a block was flushed, and flushed marking that earlier text is already
        posted (so the final flush only sends what's new). Only fires in code mode,
        and only when the buffer actually holds a fence, so an ordinary prose delta
        costs nothing.
        """
        if rec.mode != "code":
            return running_text, False
        # Cheap gate: a CLOSED fenced block needs a matching open+close pair, so
        # skip the (DOTALL-backtracking) scan unless ≥2 fence markers of one kind
        # are present. While a single long block is still OPEN (one marker) this
        # avoids re-running the regex over the whole growing buffer on every delta
        # (#93 audit: O(n²) cliff on a big unclosed block).
        if running_text.count("```") < 2 and running_text.count("~~~") < 2:
            return running_text, False
        prefix, remainder = markup.split_closed_blocks(running_text)
        if not prefix.strip():
            return running_text, False
        with contextlib.suppress(Exception):
            await streamer.flush_segment(prefix)
        await streamer.update(remainder)
        return remainder, True

    async def _run_shell_command(
        self, rec: "_ThreadRecord", thread_id: int, prompt: str, streamer: Streamer
    ) -> None:
        """#224/#227: execute `prompt` in the session's PERSISTENT jailed shell and post the
        output. No model, no tokens. cd/env persist (#227a); a command that pauses for input
        flips the session to await-input (#227b) so the next message is forwarded to it."""
        session = rec.session
        lang = i18n.cached_lang(streamer.chat_id)
        cmd = (prompt or "").strip()
        if session is None or not cmd:
            return
        rec.last_activity = time.monotonic()
        awaiting = rec.shell_awaiting
        # #245/#227b: refuse only FULL-SCREEN TUIs (can't render in chat). Line-interactive
        # commands now work via the await-input flow. Skip the guard while forwarding input.
        if not awaiting and _is_fullscreen_tui_cmd(cmd):
            with contextlib.suppress(Exception):
                await db.log_message(thread_id, "user", cmd)
            with contextlib.suppress(Exception):
                await streamer.finish(i18n.t("shell.interactive", lang), notify=True)
            return
        with contextlib.suppress(Exception):
            await db.log_message(thread_id, "user", cmd)
        status = "done"
        try:
            if awaiting:
                # #227b: forward this message to the program awaiting input. A message of pure
                # key tokens (".down .enter") goes as raw key bytes (arrow pickers, Enter, Ctrl-C);
                # anything else as a line of text + Enter.
                keys = _shell_input_keys(cmd)
                if keys is not None:
                    rc, out, status = await session.shell_send_keys(keys)
                else:
                    rc, out, status = await session.shell_send_input(cmd)
            else:
                # #227a: persistent shell (cd/env persist across messages).
                rc, out, status = await session.shell_run(cmd)
                # #267: auto-capitalized command (phone keyboard) → 127. Retry lowercased.
                if rc == 127:
                    alt = _normalize_shell_cmd(cmd)
                    if alt:
                        rc, out, status = await session.shell_run(alt)
        except Exception:
            # Persistent shell unavailable (spawn/PTY error) → fall back to the #224 one-shot.
            rec.shell_awaiting = False
            if awaiting:
                # #250: `cmd` was INPUT for a program that was awaiting it (a password, a menu
                # choice) — NOT a shell command. The persistent shell died mid-await, so running
                # it via the one-shot jail would EXECUTE the input as a command. Drop it with a
                # notice instead.
                with contextlib.suppress(Exception):
                    await streamer.finish(i18n.t("shell.ended", lang), notify=True)
                return
            try:
                rc, out = await session.run_shell(cmd)
                # #267: auto-capitalized command (phone keyboard) → 127. Retry lowercased.
                if rc == 127:
                    alt = _normalize_shell_cmd(cmd)
                    if alt:
                        rc, out = await session.run_shell(alt)
            except Exception as exc:  # never let a shell failure kill the worker
                rc, out = (-1, f"shell error: {exc}")
        rec.shell_awaiting = (status == "awaiting")  # #227b: next message → forwarded as input
        rendered = self._render_shell(out, rc, status, lang)
        kb = shell_keypad() if rec.shell_awaiting else None  # #227b: inline key keypad
        with contextlib.suppress(Exception):
            await streamer.finish(rendered, notify=True, reply_markup=kb)
        # #279: remember the live keypad message (to strip on detach / restore on re-attach).
        if rec.shell_awaiting:
            rec.shell_kb_chat = streamer.chat_id
            rec.shell_kb_msg = streamer.message_id
            rec.shell_last_render = rendered
        else:
            rec.shell_kb_chat = rec.shell_kb_msg = rec.shell_last_render = None

    @staticmethod
    def _render_shell(out: str, rc, status: str, lang: str) -> str:
        """#227: render a shell result as a monospace block + a status hint."""
        body = (out or "").replace("\r\n", "\n").rstrip("\n")
        cap = 60_000  # output cap (chars) — a runaway command can't flood the chat
        if len(body) > cap:
            body = body[:cap] + "\n... (truncated)"
        rendered = "```\n" + (body or "(no output)") + "\n```"
        if status == "awaiting":
            rendered += "\n" + i18n.t("shell.awaiting", lang)
        elif status != "timeout" and rc == 127:  # not found → likely accidental /shell
            rendered += "\n" + i18n.t("shell.accidental", lang)
        return rendered

    async def shell_key(self, thread_id: int, key_token: str, lang: str = "en"):
        """#227b: a keypad button press — send the keystroke to the persistent shell and
        return (rendered_output, still_awaiting) so the caller can edit the message."""
        rec = self._records.get(thread_id)
        data = _SHELL_CB_KEYS.get(key_token)
        if rec is None or rec.session is None or data is None:
            return (None, bool(rec and rec.shell_awaiting))
        rec.last_activity = time.monotonic()
        try:
            rc, out, status = await rec.session.shell_send_keys(data)
        except Exception as exc:
            rec.shell_awaiting = False
            return (self._render_shell(f"shell error: {exc}", -1, "done", lang), False)
        rec.shell_awaiting = (status == "awaiting")
        return (self._render_shell(out, rc, status, lang), rec.shell_awaiting)

    async def _run_one(
        self,
        rec: _ThreadRecord,
        thread_id: int,
        prompt: str,
        attachments: list | None,
        streamer: Streamer,
    ) -> None:
        """Execute a single prompt turn (optionally with attachments)."""
        session = rec.session
        if session is None:
            # Should not happen (handle_text builds it), but stay safe.
            await self._notify(
                streamer.chat_id,
                streamer.thread_id,
                i18n.t("session.not_initialized", i18n.cached_lang(streamer.chat_id)),
            )
            return

        # #224: shell-mode overlay — route the message to a one-shot jailed command
        # instead of the model (code sessions only; no tokens).
        if rec.shell_mode and rec.mode == "code":
            await self._run_shell_command(rec, thread_id, prompt, streamer)
            return

        # When streaming is off we never call streamer.start()/update(): no live
        # placeholder and no edits — the single reply is sent by finish() at the
        # end (the Streamer has message_id=None, so finish() posts a fresh message).
        stream = rec.stream_enabled

        # Log the user's prompt (feeds /recap + /history); best-effort.
        with contextlib.suppress(Exception):
            await db.log_message(thread_id, "user", prompt)

        if stream:
            await streamer.start()
        running_text = ""
        final_text = ""
        had_result = False
        # Code mode emits text in bursts between tool calls; we commit each burst
        # as its own message (segment_break) so progress stays visible. segmented
        # tells the final flush that earlier text is already posted.
        segmented = False

        try:
            async for ev in session.run(prompt, attachments=attachments):
                kind = ev.kind
                if kind == "text_delta":
                    running_text += ev.text
                    if stream:
                        await streamer.update(running_text)
                        running_text, _flushed = await self._split_live_blocks(
                            rec, streamer, running_text
                        )
                        segmented = segmented or _flushed
                elif kind == "text_full":
                    # text_full carries the engine's CUMULATIVE turn text. Once we
                    # have committed earlier segments (a live code-block split or a
                    # tool boundary), running_text is the delta-built REMAINDER, so
                    # adopting the cumulative snapshot would resurrect already-posted
                    # text and re-flush it as a duplicate (#93 audit). With
                    # include_partial_messages the deltas are authoritative, so the
                    # snapshot is redundant here — only use it BEFORE any segmenting
                    # (where it is also the no-delta fallback the comment intends).
                    if not segmented:
                        if len(ev.text) >= len(running_text):
                            running_text = ev.text
                        if stream:
                            await streamer.update(running_text)
                            running_text, _flushed = await self._split_live_blocks(
                                rec, streamer, running_text
                            )
                            segmented = segmented or _flushed
                elif kind == "thinking_delta":
                    # #240c: stream the model's extended-thinking (reasoning) into the live
                    # <tg-thinking> draft block; cleared automatically once real answer content
                    # starts. Only meaningful on the DM draft path (the streamer no-ops it
                    # otherwise). Cheap/sync — the draft loop renders it on its next tick.
                    if stream:
                        # #259: think-AFTER-write. If the model already produced answer text and
                        # now reasons again (interleaved thinking, no tool in between), finalize
                        # that text as its own bubble and open a fresh one — _begin_next_segment
                        # re-shows the <tg-thinking> placeholder, so the new reasoning is visible
                        # (a non-empty body would otherwise keep _reasoning cleared every frame).
                        # The empty-running_text guard fires only on the FIRST delta after text.
                        if running_text.strip():
                            with contextlib.suppress(Exception):
                                await streamer.segment_break()
                            running_text = ""
                            segmented = True
                        streamer.add_reasoning(ev.text)
                elif kind == "tool_start":
                    # #319: a tool is STARTING (esp. a server-side WebSearch, which can run for
                    # many seconds before its result lands). Surface its phase in the
                    # <tg-thinking> block NOW so the user sees "🌐 Searching the web…" DURING the
                    # call — the assembled `tool` event below only fires AFTER it completes.
                    # Phase only: no source / no segment-break (those wait for the real `tool`).
                    if stream:
                        with contextlib.suppress(Exception):
                            streamer.set_tool_phase(ev.tool_name, ev.tool_input)
                elif kind == "tool":
                    # #320: commit any text the model produced BEFORE this tool as its OWN
                    # message — in BOTH modes now (was code-only). A model that comments before
                    # searching ("…let me look it up. Meanwhile I'll search …") then answers
                    # produces text → tool → text; the FINAL result excludes that pre-tool text,
                    # so in chat it used to be shown and then CLOBBERED by the final answer (and
                    # it sat in the draft buffer, so the search animation never showed). Now it
                    # is kept as its own bubble and the draft frees up for the search anim.
                    # No-op when there's no pre-tool text (the common "just search then answer").
                    # was (#240b/#262): `stream and rec.mode == "code" and running_text.strip()`.
                    if stream and running_text.strip():
                        with contextlib.suppress(Exception):
                            await streamer.segment_break()
                        running_text = ""
                        segmented = True
                    # #240b/#262: show the live tool phase in the <tg-thinking> block for
                    # ALL modes — "🌐 Searching the web…" / "📖 Reading a page…" in chat,
                    # "⚙️ Running pytest…" / "📖 Reading sessions.py…" in code — so the user
                    # sees WHICH tool is working, not a bare "thinking". Renders only on the
                    # DM draft path (a no-op elsewhere).
                    if stream:
                        with contextlib.suppress(Exception):
                            # #294: localized to the user's language (streamer owns the lang).
                            streamer.set_tool_phase(ev.tool_name, ev.tool_input)
                    # #229: live task-list card from the agent's TodoWrite events — a SEPARATE
                    # rich message edited in place (off the draft path). Code-only, opt-in.
                    if rec.mode == "code" and rec.todo_card and ev.tool_name == "TodoWrite":
                        todos = (ev.tool_input or {}).get("todos") or []
                        with contextlib.suppress(Exception):
                            await streamer.update_todo_card(
                                todos, i18n.cached_lang(streamer.chat_id)
                            )
                    # #321: web-search "Sources" card DISABLED — the search feedback is the
                    # animated 🔎 thinking tag ALONE (owner: more native, less message-clutter;
                    # this card listed the QUERIES, mislabelled as "sources", while the model
                    # cites real sources itself in the answer). The card machinery
                    # (streamer.add_web_source / finalize_sources / sources_card_markdown) is kept
                    # intact for revert — re-enable by uncommenting this block. was (#318):
                    #   if stream and ev.tool_name in ("WebFetch", "WebSearch"):
                    #       _ti = ev.tool_input or {}
                    #       _src = _ti.get("url") if ev.tool_name == "WebFetch" else _ti.get("query")
                    #       if _src:
                    #           with contextlib.suppress(Exception):
                    #               await streamer.add_web_source(
                    #                   "fetch" if ev.tool_name == "WebFetch" else "search",
                    #                   _src, i18n.cached_lang(streamer.chat_id),
                    #               )
                elif kind == "session":
                    # #324: persist the session id the MOMENT the engine first reports it (the
                    # init message), not only at the terminal result — so a turn killed mid-flight
                    # (restart/crash/reap before the result) still leaves a RESUMABLE id and the
                    # session keeps its context, instead of starting a fresh one with no memory.
                    if ev.session_id:
                        if rec.mode == "code":
                            with contextlib.suppress(Exception):
                                await db.set_code_session(thread_id, ev.session_id)
                        elif rec.mode == "chat":
                            with contextlib.suppress(Exception):
                                await db.set_chat_session(thread_id, ev.session_id)
                elif kind == "rate_limit":
                    rec.rate = ev.rate
                    # Accumulate per-window account-wide rate state. Persisting to
                    # the DB and editing the pinned message on EVERY rate event is
                    # wasteful (events repeat with identical data within a turn),
                    # so only do it when the snapshot actually changed.
                    rl_type = getattr(ev.rate, "rate_limit_type", None)
                    if rl_type:
                        self.rate_by_type[str(rl_type)] = ev.rate
                        sig = self._rate_signature()
                        if sig != self._last_rate_sig:
                            self._last_rate_sig = sig
                            with contextlib.suppress(Exception):
                                await self._persist_rate()
                            with contextlib.suppress(Exception):
                                await db.append_rate_history(
                                    str(rl_type),
                                    getattr(ev.rate, "utilization", None),
                                    str(getattr(ev.rate, "status", "") or ""),
                                )
                            with contextlib.suppress(Exception):
                                await self.update_pinned()
                elif kind == "error":
                    _elang = i18n.cached_lang(streamer.chat_id)
                    if getattr(ev, "error_key", None):
                        msg = i18n.t(ev.error_key, _elang, detail=ev.error_detail or "")
                    else:
                        msg = ev.text or i18n.t("session.unknown_error", _elang)
                    if not running_text:
                        running_text = f"⚠️ {msg}"
                    # #137: a turn that fails on the subscription limit never emits a
                    # rate_limit EVENT (those keep saying "allowed"), so the usage
                    # display would stay a misleading "5h OK". Fabricate a 'rejected'
                    # five_hour window so the footer/pin honestly read "5h ⛔ limited"
                    # until the next successful turn clears it (below).
                    if getattr(ev, "limit_hit", False):
                        prev = self.rate_by_type.get("five_hour")
                        self.rate_by_type["five_hour"] = SimpleNamespace(
                            status="rejected",
                            resets_at=getattr(prev, "resets_at", None),
                            rate_limit_type="five_hour",
                            utilization=getattr(prev, "utilization", None),
                        )
                        self._synth_limit = True
                        self._last_rate_sig = self._rate_signature()
                        with contextlib.suppress(Exception):
                            await self._persist_rate()
                        with contextlib.suppress(Exception):
                            await db.append_rate_history("five_hour", None, "rejected")
                        with contextlib.suppress(Exception):
                            await self.update_pinned()
                elif kind == "result":
                    had_result = True
                    # #137: a successful turn proves the window isn't blocking — drop
                    # any fabricated "limited" five_hour we set on a prior failure so
                    # the honest display self-heals (real rate events repopulate it).
                    if self._synth_limit:
                        self._synth_limit = False
                        self.rate_by_type.pop("five_hour", None)
                        self._last_rate_sig = self._rate_signature()
                        with contextlib.suppress(Exception):
                            await self._persist_rate()
                        with contextlib.suppress(Exception):
                            await self.update_pinned()
                    # When we have already posted segments, the only NEW text is the
                    # current (last) burst in running_text — do NOT reuse ev.text,
                    # which for a multi-tool turn can repeat earlier segments.
                    final_text = running_text if segmented else (ev.text or running_text)
                    # Persist usage + the resumable session id for this mode. #165:
                    # also store the turn's model + last-known context size so the
                    # weighted usage-units metric can be computed from each row's own
                    # data (context_tokens is the most recent measured value — captured
                    # at the end of the prior turn — and is informational; the units
                    # formula itself bills cache_read, which already reflects context).
                    with contextlib.suppress(Exception):
                        await db.add_usage(
                            thread_id, ev.usage, ev.cost,
                            model=getattr(rec, "model", None),
                            context_tokens=int(getattr(rec, "last_context_tokens", 0) or 0),
                        )
                    # #261: stamp durable last-activity (wall clock) so the next message
                    # can detect a long idle gap and rotate to a fresh session.
                    with contextlib.suppress(Exception):
                        await db.set_last_active(thread_id, time.time())
                    if ev.session_id:
                        if rec.mode == "code":
                            with contextlib.suppress(Exception):
                                await db.set_code_session(thread_id, ev.session_id)
                        elif rec.mode == "chat":
                            # Persist the chat session id every turn so the session
                            # is durable: the next build resumes it (across restart
                            # / stop). big_memory only toggles the 1M window now.
                            with contextlib.suppress(Exception):
                                await db.set_chat_session(thread_id, ev.session_id)
                        # #260: adopt Claude Code's own auto-title (the name shown in
                        # the browser) as our session label — until the user pins one
                        # with /rename (manual=False is a no-op once name_auto is 0).
                        # Only when it actually changed, to avoid a write every turn.
                        if getattr(rec, "name_auto", True):
                            with contextlib.suppress(Exception):
                                # #285: the transcript JSONL grows unbounded; scan it off the
                                # event loop so a long session's turn-end doesn't stall others.
                                title = await asyncio.to_thread(
                                    _read_ai_title, getattr(rec, "cwd", None), ev.session_id
                                )
                                if title and title != getattr(rec, "name", None):
                                    await db.set_session_name(
                                        thread_id, title, manual=False
                                    )
                                    rec.name = title
                        # One-shot fork done: the branched id is now persisted, so
                        # clear the flag — subsequent turns continue this branch (#23).
                        if rec.fork:
                            rec.fork = False
                            with contextlib.suppress(Exception):
                                await db.set_fork_pending(thread_id, False)
        except asyncio.CancelledError:
            # Propagate cancellation so the worker can report the stop; ensure
            # the in-flight SDK turn is interrupted first, and tear down the
            # streamer's background typing task so it is not orphaned (finish()
            # — which normally stops typing — is skipped on the cancel path).
            with contextlib.suppress(Exception):
                await session.interrupt()
            with contextlib.suppress(Exception):
                streamer.cancel()
            raise
        except Exception as exc:  # defensive: never let one turn crash the worker
            err = i18n.t("session.internal_error", i18n.cached_lang(streamer.chat_id), exc=exc)
            if not final_text and not running_text:
                final_text = err
        finally:
            rec.last_activity = time.monotonic()

        # Final flush. Fall back to the streamed running text if no result text.
        flush_text = final_text if (had_result or final_text) else running_text
        # #164: the account footer is the owner's GLOBAL usage — show it only to the
        # owner (chat_id == owner_id). Delegated users get their own /limits instead.
        footer = self.usage_footer(i18n.cached_lang(streamer.chat_id), chat_id=streamer.chat_id)
        if segmented and not flush_text.strip():
            # Every burst was already committed and the turn ended on a tool with
            # no trailing text — nothing new to post. Stop the stream (the empty
            # "Thinking…" draft self-expires) instead of posting a bare "…".
            with contextlib.suppress(Exception):
                streamer.cancel()
        else:
            # The final answer pings the user; intermediate segments stayed silent.
            with contextlib.suppress(Exception):
                await streamer.finish(flush_text, footer=footer, notify=True)
            # Log the assistant's reply (feeds /recap + /history); best-effort.
            with contextlib.suppress(Exception):
                await db.log_message(thread_id, "assistant", flush_text)
            # #164/#166: optional warm-cache reminder, ticking down (per-session toggle).
            with contextlib.suppress(Exception):
                await self._maybe_hot_cache_note(thread_id, streamer, rec)
            # #167: capture the context size now (the turn is done → the SDK client is
            # idle, so this control request is safe) for the NEXT turn's working plate.
            with contextlib.suppress(Exception):
                tot = _ctx_total(await session.context_usage())
                if tot:
                    rec.last_context_tokens = tot

    # ------------------------------------------------------------------ control

    async def stop(self, thread_id: int) -> bool:
        """Gracefully interrupt the current turn — like the web ⏹ button.

        Stops token generation (so subscription usage is not burned) but KEEPS
        the session and its conversation context intact. Crucially we do NOT
        cancel the worker and do NOT disconnect the client:

        - `client.interrupt()` makes the SDK end `receive_response()` for the
          current turn, so the worker finishes that turn NORMALLY. Its `finish()`
          flushes whatever text was generated so far, so the Telegram chat always
          reflects what the model now remembers — no view/memory desync, even if a
          little text was produced after the tap.
        - Keeping the in-sync client means the next message continues the same
          conversation (context preserved) and avoids the mid-stream-abandon
          desync that previously produced DOUBLED replies.

        The queue is cleared so chained prompts do not run after the stop, and any
        pending permission prompt is denied so a gated turn can unwind. Returns
        True if there was something to stop, else False. (For a hard clear that
        drops the context too, use reset().)
        """
        rec = self._records.get(thread_id)
        if rec is None:
            return False

        async with rec.lock:
            worker = rec.worker
            running = worker is not None and not worker.done()
            if not running and rec.queue.empty():
                return False

            # Drop queued chained prompts so nothing new runs after the stop.
            _drain_queue(rec.queue)

            # Deny any pending permission prompt so a gated turn unblocks and the
            # SDK callback returns (no leaked Future / stale inline buttons). The
            # gate keys prompts by the SEND thread id (None for General).
            with contextlib.suppress(Exception):
                await self.gate.cancel_thread(thread_id)

            # Interrupt the in-flight turn (best effort). The worker keeps running
            # and finishes the turn gracefully, showing the partial text; the
            # session and its context stay alive for the next message.
            if rec.session is not None:
                with contextlib.suppress(Exception):
                    await rec.session.interrupt()
        return True

    async def reset(self, thread_id: int) -> None:
        """Hard reset: discard the run, drop the SDK client, clear the session.

        Unlike /stop (which interrupts but KEEPS context), /reset fully clears the
        topic: it forcefully cancels the worker, disconnects the client, drops the
        in-memory record, and clears the persisted code session id, so the next
        message starts a brand-new session (mode/model/cwd are kept in the DB).
        """
        rec = self._records.get(thread_id)
        if rec is not None:
            # Hold the lock across the WHOLE teardown AND the dict removal so a
            # concurrent handle_text() (same rec.lock) either fully precedes this
            # critical section — its session is the one we aclose() here — or
            # fully follows the pop, in which case _record() builds a fresh record.
            async with rec.lock:
                # Deny pending permission prompts and clear queued prompts.
                with contextlib.suppress(Exception):
                    await self.gate.cancel_thread(thread_id)
                _drain_queue(rec.queue)

                # Forcefully cancel the worker — reset discards the turn entirely
                # (no graceful finish), so we cancel rather than interrupt-and-wait.
                worker = rec.worker
                if worker is not None and not worker.done():
                    worker.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await worker
                if rec.worker is worker:
                    rec.worker = None

                # Disconnect the client, then drop the record under the lock.
                if rec.session is not None:
                    old = rec.session
                    rec.session = None
                    with contextlib.suppress(Exception):
                        await old.aclose()
                self._records.pop(thread_id, None)

        # #274: a hard reset/delete tears the shell down for good (unlike the idle reaper,
        # which preserves it) — close any reaper-stashed shell for this thread too.
        await self._drop_detached_shell(thread_id)
        with contextlib.suppress(Exception):
            await db.reset_thread(thread_id)

    async def on_mode_or_model_or_cwd_change(self, thread_id: int) -> bool:
        """Drop the live client so the next message rebuilds with new settings.

        Used by /mode, /model, /cwd and /permissions handlers after they persist
        the change. The new settings are already in the DB; _get_session compares
        the DB state to the in-memory snapshot and rebuilds on the next message,
        so this method only does the EAGER cleanup when it is safe:

        - Idle thread → aclose() the old client now (free the connection) and
          clear the snapshot so the next message builds fresh.
        - Busy thread → do NOTHING (closing the client would kill the in-flight
          turn) and return True. The running turn + any queued prompts finish
          under the current settings; _get_session performs the deferred rebuild
          once the worker goes idle.

        Returns True when the change was DEFERRED because a turn is running, so
        the caller can tell the user it applies after the current run.
        """
        rec = self._records.get(thread_id)
        if rec is None:
            return False
        async with rec.lock:
            worker = rec.worker
            busy = worker is not None and not worker.done()
            if busy:
                return True
            if rec.session is not None:
                old = rec.session
                rec.session = None
                with contextlib.suppress(Exception):
                    await old.aclose()
            # Force a rebuild on next handle_text by clearing the config snapshot.
            rec.mode = None
            rec.model = None
            rec.cwd = None
            rec.permission_mode = None
            rec.big_memory = None
        return False

    # ----------------------------------------------------------- queue / retry

    def queue_info(self, thread_id: int) -> dict:
        """Peek at the pending queue without consuming it.

        Returns {"count": <pending>, "items": [<first ~3 prompts, ~60 chars>]}.
        Peeking reads the underlying deque defensively; if that internal is not
        available we still report an accurate count with an empty items list.
        """
        rec = self._records.get(thread_id)
        if rec is None:
            return {"count": 0, "items": []}

        count = rec.queue.qsize()
        if count <= 0:
            return {"count": 0, "items": []}

        items: list[str] = []
        try:
            for item in list(rec.queue._queue)[:3]:  # type: ignore[attr-defined]
                _qid, raw, atts = _unpack_queue_item(item)
                text = str(raw).replace("\n", " ").strip()
                if len(text) > 60:
                    text = text[:59] + "…"
                icon = _attachment_icon(atts)
                if icon:
                    text = f"{icon} {text}".strip()
                items.append(text or icon)
        except Exception:
            items = []
        return {"count": count, "items": items}

    def queue_items(self, thread_id: int) -> list[dict]:
        """Return the pending queue as [{id, text}] (oldest-first) for /queue's
        per-item cancel view. Empty list when nothing is queued."""
        rec = self._records.get(thread_id)
        if rec is None or rec.queue.qsize() <= 0:
            return []
        out: list[dict] = []
        try:
            for item in list(rec.queue._queue):  # type: ignore[attr-defined]
                qid, raw, atts = _unpack_queue_item(item)
                text = str(raw).replace("\n", " ").strip()
                if len(text) > 50:
                    text = text[:49] + "…"
                icon = _attachment_icon(atts)
                out.append({"id": qid, "text": (f"{icon} {text}".strip() or icon)})
        except Exception:
            return []
        return out

    async def cancel_queued(self, thread_id: int, qid: int) -> str | None:
        """Remove ONE pending prompt by its queue id, leaving the rest in order.
        Returns a short preview of the removed prompt, or None if not found.
        Runs under rec.lock so it never races a concurrent enqueue/drain."""
        rec = self._records.get(thread_id)
        if rec is None:
            return None
        removed: str | None = None
        async with rec.lock:
            kept: list = []
            while True:
                try:
                    item = rec.queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                iqid, raw, _atts = _unpack_queue_item(item)
                if removed is None and iqid == qid:
                    removed = str(raw).replace("\n", " ").strip()[:60]
                else:
                    kept.append(item)
            for item in kept:
                rec.queue.put_nowait(item)
        return removed

    async def clear_queue(self, thread_id: int) -> int:
        """Drop every pending prompt WITHOUT cancelling the running worker.

        Returns how many prompts were discarded. Runs under rec.lock so it does
        not race a concurrent handle_text() enqueue.
        """
        rec = self._records.get(thread_id)
        if rec is None:
            return 0
        async with rec.lock:
            dropped = rec.queue.qsize()
            _drain_queue(rec.queue)
        return dropped

    async def retry(self, chat_id: int, thread_id: int) -> bool:
        """Re-submit the most recent prompt for this thread.

        Returns True if there was a prompt to retry, else False.

        Uses the last-submitted prompt as observed at call time: we snapshot
        last_prompt synchronously (before any await) so we re-run a consistent
        value even if a concurrent handle_text() updates it afterwards. This is
        a deliberate stale-read — retry runs exactly once and never loops.
        """
        rec = self._records.get(thread_id)
        if rec is None or not rec.last_prompt:
            return False
        text, attachments = rec.last_prompt
        await self.handle_text(chat_id, thread_id, text, attachments=attachments)
        return True

    async def context_usage(self, thread_id: int):
        """Return the live session's context usage, or None if unavailable."""
        rec = self._records.get(thread_id)
        if rec is None or rec.session is None:
            return None
        try:
            return await rec.session.context_usage()
        except Exception:
            return None

    async def set_stream(self, thread_id: int, on: bool) -> None:
        """Toggle live streaming (placeholder + edits) for this thread.

        Uses _record() (creates on miss) on purpose: toggling a display
        preference before the first message must persist so it applies to the
        session that message starts. The read-only API (queue_info/status/etc.)
        uses _records.get() because it has nothing to remember. A record created
        here is plain state (no session/worker), torn down by /reset like any
        other.
        """
        rec = self._record(thread_id)
        rec.stream_enabled = bool(on)
        # Persist so the preference survives a restart (#28).
        with contextlib.suppress(Exception):
            await db.set_stream_enabled(thread_id, on)

    async def set_shell_mode(self, thread_id: int, on: bool) -> None:
        """#224: toggle the shell-mode overlay for a code session (text → jailed
        command). Mirrors set_stream: update the live record + persist."""
        rec = self._record(thread_id)
        # #227c: toggling shell mode is a DETACH, like leaving a tmux session — the persistent
        # shell (and ANY command still running in it: a server, a long build, a program awaiting
        # input) stays ALIVE in the background, and the agent (LLM) takes over. /shell on later
        # re-attaches with cd/env + the running command intact; `shell_awaiting` is preserved so a
        # paused program still receives the next message's input. The shell is only torn down on
        # session delete/evict (aclose) or the #179 idle reaper. To interrupt a running command,
        # use the ^C key; a truly stuck one is reaped when the session goes idle.
        rec.shell_mode = bool(on)
        with contextlib.suppress(Exception):
            await db.set_shell_mode(thread_id, on)

    def shell_kb_ref(self, thread_id: int) -> tuple[int, int] | None:
        """#279: (chat_id, message_id) of the message currently bearing the shell keypad,
        or None. Used by /shell OFF to strip the now-stale keypad from it."""
        rec = self._records.get(thread_id)
        if rec is None or not rec.shell_kb_chat or not rec.shell_kb_msg:
            return None
        return (rec.shell_kb_chat, rec.shell_kb_msg)

    def shell_resume_render(self, thread_id: int) -> str | None:
        """#279: the last awaiting-input render (the prompt screen) IF the shell is still
        paused for input, else None — so /shell ON can restore the keypad where it paused."""
        rec = self._records.get(thread_id)
        if rec is None or not rec.shell_awaiting:
            return None
        return rec.shell_last_render

    async def shell_refresh(self, thread_id: int, lang: str = "en") -> str | None:
        """#279: on /shell re-attach, surface any output the program printed WHILE DETACHED
        (it may have advanced past the prompt we stored). Drains the shell's pending output
        without sending input; if there's something new, re-renders + stores it. Returns the
        live render, or None to fall back to the stored resume render."""
        rec = self._records.get(thread_id)
        if rec is None:
            return None
        # #289: hold rec.lock across the snapshot read + peek so a concurrent rebuild can't
        # swap rec.session under us between the guard and the await (was an unlocked read).
        async with rec.lock:
            if rec.session is None or not rec.shell_awaiting:
                return None
            try:
                rc, out, status = await rec.session.shell_peek()
            except Exception:
                return None
            if out and out.strip():
                rendered = self._render_shell(out, rc, "awaiting", lang)
                rec.shell_last_render = rendered
                return rendered
        return None

    def set_shell_kb(self, thread_id: int, chat: int | None, msg: int | None,
                     render: str | None = None) -> None:
        """#279: point the keypad tracker at a message (chat, msg) — pass None,None to forget
        the message REF (e.g. on detach, after stripping its keypad) while KEEPING the paused
        render + awaiting flag so /shell ON can restore. `render` updates the stored body only
        when given (never cleared here — the restore gate is `shell_awaiting`)."""
        rec = self._records.get(thread_id)
        if rec is None:
            return
        rec.shell_kb_chat = chat
        rec.shell_kb_msg = msg
        if render is not None:
            rec.shell_last_render = render

    # ------------------------------------------------------------------ usage

    async def load_persisted(self) -> None:
        """Restore usage settings + the last rate snapshot from the DB.

        Tolerates missing or malformed values: anything unreadable falls back to
        a sane default so startup never fails on a stale/garbled key.
        """
        # Usage display mode.
        with contextlib.suppress(Exception):
            mode = await db.get_kv("usage_mode")
            if mode in {"off", "footer", "pinned", "both"}:
                self.usage_mode = mode
            else:
                self.usage_mode = "footer"

        # Code-block message-splitting toggle (/codesplit). Default ON; only an
        # explicit "0"/"off" disables it.
        with contextlib.suppress(Exception):
            raw = await db.get_kv("split_code_messages")
            if raw is not None:
                self.split_code_messages = str(raw).lower() not in ("0", "off", "false", "")

        # #175: working-plate toggle. Default ON; only an explicit "0"/"off" disables.
        with contextlib.suppress(Exception):
            raw = await db.get_kv("working_plate")
            if raw is not None:
                self.working_plate = str(raw).lower() not in ("0", "off", "false", "")

        # #261: global idle→fresh-session window (seconds). Owner-set in Admin (runtime),
        # falling back to the .env/config default. 0 = off. Per-user idle_reset_min still
        # overrides this for a given owner (see idle_reset_seconds).
        with contextlib.suppress(Exception):
            raw = await db.get_kv("idle_reset_sec")
            if raw is not None:
                self._idle_reset = max(0.0, float(int(raw)))

        # Main chat id.
        with contextlib.suppress(Exception):
            raw = await db.get_kv("main_chat_id")
            if raw:
                self._main_chat_id = int(raw)

        # Pinned usage message "chat:msg".
        with contextlib.suppress(Exception):
            raw = await db.get_kv("pinned_msg")
            if raw and ":" in raw:
                chat_s, msg_s = raw.split(":", 1)
                self._pinned = (int(chat_s), int(msg_s))

        # Rate snapshot: {type: {status, resets_at, rate_limit_type, util...}}.
        with contextlib.suppress(Exception):
            raw = await db.get_kv("rate_snapshot")
            if raw:
                data = json.loads(raw)
                rebuilt: dict[str, object] = {}
                for rl_type, entry in data.items():
                    if not isinstance(entry, dict):
                        continue
                    rebuilt[str(rl_type)] = SimpleNamespace(
                        status=entry.get("status"),
                        resets_at=entry.get("resets_at"),
                        rate_limit_type=entry.get("rate_limit_type"),
                        utilization=entry.get("utilization"),
                    )
                self.rate_by_type = rebuilt

    async def set_usage_mode(self, mode: str) -> None:
        """Set + persist the usage display mode, refreshing the pin if needed."""
        if mode not in {"off", "footer", "pinned", "both"}:
            raise ValueError(f"invalid usage mode: {mode!r}")
        self.usage_mode = mode
        await db.set_kv("usage_mode", mode)
        if mode in {"pinned", "both"}:
            await self.update_pinned()

    async def set_split_code_messages(self, on: bool) -> None:
        """Set + persist whether each fenced code block is sent as its own message
        (the /codesplit toggle). Takes effect on the next reply (read at Streamer
        build time), so no restart is needed."""
        self.split_code_messages = bool(on)
        await db.set_kv("split_code_messages", "1" if on else "0")

    async def set_working_plate(self, on: bool) -> None:
        """Set + persist the global "Working…"/Stop plate toggle (#175). Takes effect on
        the next turn (read at Streamer build time)."""
        self.working_plate = bool(on)
        await db.set_kv("working_plate", "1" if on else "0")

    async def set_idle_reset_sec(self, sec: int) -> None:
        """#261: set + persist the GLOBAL idle→fresh-session window (seconds; 0 = off).
        Owner-set in Admin; takes effect on the next message (no restart). A per-user
        idle_reset_min still overrides it for that owner."""
        self._idle_reset = max(0.0, float(sec))
        await db.set_kv("idle_reset_sec", str(int(self._idle_reset)))

    def usage_footer(self, lang: str = "en", chat_id: int | None = None) -> str:
        """Footer line appended to a finished reply when footer display is on.

        #164: the account/subscription windows are the OWNER's GLOBAL numbers, so
        the footer is shown ONLY to the owner — a delegated user must never see the
        deployer's account-wide usage. Users get their OWN limits via /limits and
        the working-plate note instead. (chat_id omitted → unchanged behaviour.)"""
        if self.usage_mode not in {"footer", "both"}:
            return ""
        owner_id = getattr(self.settings, "owner_id", None)
        if owner_id is not None and chat_id is not None and chat_id != owner_id:
            return ""
        # #169: owner wants 5h and 7d on TWO separate lines.
        return usage.footer_line(self.rate_by_type, lang, sep="\n")

    async def stream_demo(self, chat_id: int, thread_id: int | None = None) -> None:
        """#172 (/test): simulate a STREAMED generation of a sample reply (paragraphs,
        a wide table, an asm snippet, and an SVG diagram, #295) so the owner can watch the
        live rich-draft formatting build up — instead of plain text snapping to rich at the
        end. The SVG renders to a PNG photo at finish. Drives a standalone Streamer; not a
        real session. Best-effort."""
        # controllable=False → no mid-stream Stop message (kept the draft from
        # "regenerating"); finish(notify=False) → the persisted message is SILENT.
        streamer = Streamer(self.bot, chat_id, thread_id,
                            use_drafts=chat_id > 0, controllable=False)
        await streamer.start()
        sample = _DEMO_SAMPLE
        step = max(8, len(sample) // 40)   # ~40 growth steps
        try:
            for i in range(step, len(sample) + step, step):
                await streamer.update(sample[:i])
                await asyncio.sleep(0.15)
            await streamer.finish(sample, notify=False)
        except Exception:
            with contextlib.suppress(Exception):
                streamer.cancel()

    async def _working_note(self, chat_id: int, lang: str, rec=None) -> str:
        """Extra line(s) for the 'Working…' plate: the OWNER sees account usage (5h/7d
        on 2 lines), a delegated user sees their OWN limit once a window is ≥50% used
        (#164), plus the live CONTEXT SIZE once it is big enough (#167 — forced on
        unless the owner delegated a disable). Cheap + best-effort; '' on any failure."""
        lines: list[str] = []
        try:
            owner_id = getattr(self.settings, "owner_id", None)
            if owner_id is not None and chat_id == owner_id:
                fl = usage.footer_line(self.rate_by_type, lang, sep="\n")  # #169: 2 lines
                if fl:
                    lines.append(fl)
            elif self.allowlist:
                caps = self.allowlist.rate_of(chat_id, None)
                day_cap, week_cap = caps.get("day"), caps.get("week")
                if day_cap or week_cap:
                    bd = await db.get_user_breakdown(chat_id)
                    best = None  # (fraction, kind_key)
                    if day_cap:
                        frac = bd["day"] / day_cap
                        if frac >= 0.5:
                            best = (frac, "stream.kind_day")
                    if week_cap:
                        frac = bd["week"] / week_cap
                        if frac >= 0.5 and (best is None or frac > best[0]):
                            best = (frac, "stream.kind_week")
                    if best is not None:
                        pct = min(100, int(best[0] * 100))
                        lines.append(i18n.t("stream.usage_line", lang, pct=pct,
                                            kind=i18n.t(best[1], lang)))
            # #167: live context size (captured at the previous turn's end), once it
            # crosses the threshold, when the toggle is on (default).
            if rec is not None and getattr(rec, "ctx_status", True):
                ctx = int(getattr(rec, "last_context_tokens", 0) or 0)
                if ctx >= _CTX_STATUS_MIN:
                    lines.append(i18n.t("stream.context", lang, n=f"{ctx / 1000:.0f}k"))
        except Exception:
            return "\n".join(lines)
        return "\n".join(lines)

    async def _maybe_hot_cache_note(self, thread_id: int, streamer, rec=None) -> None:
        """Post a warm-cache reminder after a reply when the session toggle is on
        (#164), then tick it DOWN every minute (#166) until the 5-min window expires.
        The next turn cancels it (the window resets). Best-effort throughout."""
        st = await db.get_thread(thread_id)
        if st is None or not getattr(st, "hot_cache_timer", False):
            return
        lang = i18n.cached_lang(streamer.chat_id)
        mins = int(_CACHE_WINDOW_SECONDS // 60)
        kwargs: dict = {}
        if streamer.thread_id is not None:
            kwargs["message_thread_id"] = streamer.thread_id
        msg = None
        with contextlib.suppress(Exception):
            msg = await self.bot.send_message(
                streamer.chat_id,
                i18n.t("hotcache.note", lang, mins=mins),
                parse_mode="HTML",
                disable_notification=True,
                **kwargs,
            )
        if msg is None or rec is None:
            return
        rec.hot_cache_msg_id = getattr(msg, "message_id", None)
        if rec.hot_cache_msg_id is not None:
            rec.hot_cache_task = asyncio.create_task(
                self._hot_cache_tick(rec.last_activity, streamer.chat_id,
                                     rec.hot_cache_msg_id, lang))

    async def _hot_cache_tick(self, start: float, chat_id: int, msg_id: int, lang: str) -> None:
        """#166: edit the warm-cache note down to 0 once a minute, then mark it cold.
        Cancelled by the next turn (which reset the window). All edits best-effort."""
        try:
            while True:
                await asyncio.sleep(60)
                left = int(_CACHE_WINDOW_SECONDS - (time.monotonic() - start))
                if left <= 0:
                    with contextlib.suppress(Exception):
                        await self.bot.edit_message_text(
                            i18n.t("hotcache.cold", lang), chat_id=chat_id,
                            message_id=msg_id, parse_mode="HTML")
                    return
                mins = max(1, (left + 59) // 60)
                with contextlib.suppress(Exception):
                    await self.bot.edit_message_text(
                        i18n.t("hotcache.note", lang, mins=mins), chat_id=chat_id,
                        message_id=msg_id, parse_mode="HTML")
        except asyncio.CancelledError:
            return

    def _cancel_hot_cache(self, rec, chat_id: int) -> None:
        """#166: drop the previous turn's warm-cache countdown + its message (the new
        turn resets the 5-min window). Fire-and-forget delete."""
        if rec.hot_cache_task is not None:
            rec.hot_cache_task.cancel()
            rec.hot_cache_task = None
        if rec.hot_cache_msg_id is not None:
            mid = rec.hot_cache_msg_id
            rec.hot_cache_msg_id = None
            with contextlib.suppress(Exception):
                asyncio.create_task(self.bot.delete_message(chat_id, mid))

    def _rate_signature(self) -> tuple:
        """A cheap, comparable fingerprint of the current rate snapshot.

        Lets _run_one skip redundant DB writes + pinned-message edits when a rate
        event repeats data we already recorded. Sorted by window key so the order
        the events arrive in does not affect equality.
        """
        sig: list = []
        for key in sorted(self.rate_by_type):
            info = self.rate_by_type[key]
            sig.append(
                (
                    key,
                    getattr(info, "status", None),
                    getattr(info, "utilization", None),
                    getattr(info, "resets_at", None),
                )
            )
        return tuple(sig)

    async def _persist_rate(self) -> None:
        """Persist the current per-window rate snapshot as JSON (best effort)."""
        with contextlib.suppress(Exception):
            data = {
                rl_type: {
                    "status": getattr(info, "status", None),
                    "resets_at": getattr(info, "resets_at", None),
                    "rate_limit_type": getattr(info, "rate_limit_type", None),
                    "utilization": getattr(info, "utilization", None),
                }
                for rl_type, info in self.rate_by_type.items()
            }
            await db.set_kv("rate_snapshot", json.dumps(data))

    async def update_pinned(self) -> None:
        """Create or refresh the pinned usage message in the General topic.

        No-op unless usage_mode includes "pinned" and we know the main chat. All
        Telegram errors are swallowed (the bot may lack pin rights).
        """
        if self.usage_mode not in {"pinned", "both"} or self._main_chat_id is None:
            return
        text = usage.pinned_text(self.rate_by_type, i18n.cached_lang(self._main_chat_id or 0))
        if not text:
            return

        chat_id = self._main_chat_id

        # Try to edit the existing pinned message in place.
        if self._pinned:
            pin_chat, pin_msg = self._pinned
            try:
                await self.bot.edit_message_text(
                    text,
                    chat_id=pin_chat,
                    message_id=pin_msg,
                    parse_mode="HTML",
                )
                return
            except Exception:
                # Fall through to create a fresh message below.
                pass

        # Create a new message in the General topic (no message_thread_id) and
        # best-effort pin it. Swallow everything: missing pin rights are normal.
        try:
            msg = await self.bot.send_message(chat_id, text, parse_mode="HTML")
        except Exception:
            return
        with contextlib.suppress(Exception):
            await self.bot.pin_chat_message(
                chat_id, msg.message_id, disable_notification=True
            )
        self._pinned = (chat_id, msg.message_id)
        with contextlib.suppress(Exception):
            await db.set_kv("pinned_msg", f"{chat_id}:{msg.message_id}")

    # ----------------------------------------------------- account usage (#135)

    async def refresh_account_usage(self) -> bool:
        """Refresh ``rate_by_type`` from the account /api/oauth/usage endpoint (#135)
        — the REAL per-window % the SDK rate-events only send near a limit. Merges the
        account windows in, then persists the snapshot + re-renders the pinned message
        when it changed. Returns True if anything changed. Best-effort: a fetch failure
        leaves the prior snapshot untouched (no exception escapes)."""
        data = await usage.fetch_account_usage()
        if not data:
            return False
        for key, info in data.items():
            self.rate_by_type[str(key)] = info
        sig = self._rate_signature()
        if sig == self._last_rate_sig:
            return False
        self._last_rate_sig = sig
        with contextlib.suppress(Exception):
            await self._persist_rate()
        with contextlib.suppress(Exception):
            await self.update_pinned()
        return True

    async def _usage_poll_loop(self) -> None:
        """Refresh the account usage on startup and every ``_USAGE_POLL_INTERVAL``,
        so the footer / pinned / status stay accurate even when the bot is idle (no
        turn → no SDK rate event). One small GET per cycle; all errors swallowed."""
        while True:
            with contextlib.suppress(Exception):
                await self.refresh_account_usage()
            try:
                await asyncio.sleep(_USAGE_POLL_INTERVAL)
            except asyncio.CancelledError:
                break

    def start_usage_poller(self) -> None:
        """Start the account-usage poller (idempotent). Called once at startup."""
        if self._usage_task is None or self._usage_task.done():
            self._usage_task = asyncio.create_task(self._usage_poll_loop())

    # ----------------------------------------------- concurrency / RAM (#179)

    @staticmethod
    def _mem_available_mb() -> int:
        """MemAvailable from /proc/meminfo, in MiB. On any error return a huge
        number so we NEVER falsely throttle (fail-open)."""
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        return int(line.split()[1]) // 1024
        except Exception:
            pass
        return 1 << 30

    def _live_thread_ids(self, *, idle_only: bool = False) -> list[int]:
        """Thread ids whose claude client is currently LIVE. With idle_only, drop
        the ones whose worker is mid-turn (we never evict a running turn)."""
        out: list[int] = []
        for tid in list(self._records.keys()):
            rec = self._records.get(tid)
            if rec is None or rec.session is None:
                continue
            if idle_only:
                busy = rec.worker is not None and not rec.worker.done()
                if busy:
                    continue
            out.append(tid)
        return out

    async def _evict_session(self, thread_id: int) -> bool:
        """aclose() one thread's IDLE client and clear its config snapshot so the
        NEXT message rebuilds and `resume`s from the on-disk transcript (no history
        loss). No-op if the thread is busy or already has no live client. Mirrors the
        idle path of on_mode_or_model_or_cwd_change so locking stays consistent."""
        rec = self._records.get(thread_id)
        if rec is None:
            return False
        async with rec.lock:
            worker = rec.worker
            busy = worker is not None and not worker.done()
            if busy or rec.session is None:
                return False
            old = rec.session
            rec.session = None
            # #274: preserve a live jailed shell across the reap (it's ~3 MB vs the ~500 MB
            # client we're freeing, and holds the user's cd/env + any running command). It
            # gets its own much longer TTL and is re-attached on the next rebuild.
            if getattr(old, "has_live_shell", None) and old.has_live_shell():
                sh = old.detach_shell()
                if sh is not None:
                    self._detached_shells[thread_id] = (sh, time.monotonic())
            with contextlib.suppress(Exception):
                await old.aclose()
            # Clear the snapshot → _get_session rebuilds fresh on the next message.
            rec.mode = None
            rec.model = None
            rec.cwd = None
            rec.permission_mode = None
            rec.big_memory = None
        return True

    def _reattach_shell(self, session, thread_id: int, pending_shell=None) -> None:
        """#274: give a freshly-built session a persistent shell preserved from a rebuild
        (`pending_shell`) or one stashed by the reaper for this thread. A dead shell is
        dropped, not adopted."""
        sh = pending_shell
        entry = self._detached_shells.pop(thread_id, None)
        if sh is None and entry is not None:
            sh = entry[0]
        elif entry is not None:
            # Drift-path shell wins; the stashed one is stale → discard it.
            with contextlib.suppress(Exception):
                self._loop_close_shell(entry[0])
        if sh is None:
            return
        if getattr(sh, "alive", lambda: False)():
            session.adopt_shell(sh)
        else:
            with contextlib.suppress(Exception):
                self._loop_close_shell(sh)

    def _loop_close_shell(self, sh) -> None:
        """Best-effort fire-and-forget close of a shell from a sync context."""
        with contextlib.suppress(Exception):
            asyncio.create_task(sh.close())

    async def _drop_detached_shell(self, thread_id: int) -> None:
        """#274: close + forget a reaper-stashed shell (on hard reset / session delete)."""
        entry = self._detached_shells.pop(thread_id, None)
        if entry is not None:
            with contextlib.suppress(Exception):
                await entry[0].close()

    async def _reap_detached_shells(self, now: float) -> None:
        """#274: close persistent shells stashed by the reaper that have outlived the shell
        TTL (or already died). 0 = never (kept until session delete)."""
        for tid, (sh, ts) in list(self._detached_shells.items()):
            dead = not getattr(sh, "alive", lambda: False)()
            expired = self._shell_ttl > 0 and (now - ts) >= self._shell_ttl
            if dead or expired:
                self._detached_shells.pop(tid, None)
                with contextlib.suppress(Exception):
                    await sh.close()

    async def _relieve_memory(self, *, exclude: int | None = None, max_evict: int = 8) -> int:
        """Free RAM by evicting IDLE live clients, least-recently-active first, until
        MemAvailable is back above the floor (or we run out / hit max_evict). Called
        before a turn grabs more memory. Returns how many were evicted."""
        floor = self._min_free_mb
        idle = [
            (self._records[t].last_activity, t)
            for t in self._live_thread_ids(idle_only=True)
            if t != exclude
        ]
        idle.sort()  # oldest activity first (LRU)
        freed = 0
        for _, tid in idle:
            if freed >= max_evict:
                break
            if await self._evict_session(tid):
                freed += 1
            if self._mem_available_mb() >= floor:
                break
        return freed

    async def _admit_turn(self, thread_id: int, chat_id: int, send_tid: int | None) -> None:
        """Gate a turn before it runs: (1) if MemAvailable is below the floor, evict
        idle clients to make room (defer-on-pressure); (2) if every concurrency slot
        is taken the turn will block on the fair turn-gate — tell the user it is queued."""
        if self._mem_available_mb() < self._min_free_mb:
            await self._relieve_memory(exclude=thread_id)
        if self._turn_gate.locked():
            with contextlib.suppress(Exception):
                await self._notify(
                    chat_id, send_tid, i18n.t("busy.queued", i18n.cached_lang(chat_id))
                )

    async def _reap_once(self) -> None:
        """One reaper sweep: evict clients idle longer than idle_ttl_sec, then, if
        still over max_live_clients, evict the least-recently-active idle ones down
        to the cap. Busy threads (mid-turn) are never touched."""
        now = time.monotonic()
        for tid in self._live_thread_ids(idle_only=True):
            rec = self._records.get(tid)
            if rec is None:
                continue
            # #182: per-user idle-TTL resolved onto the record (seconds). None →
            # global default; ≤0 → never reap (owner set ∞ — the RAM cap below still
            # applies as the hard safety, so ∞ never risks an OOM).
            ttl = rec.idle_ttl if rec.idle_ttl is not None else self._idle_ttl
            if ttl > 0 and now - rec.last_activity >= ttl:
                await self._evict_session(tid)
        # Count ALL live (idle+busy) against the cap, but only ever evict idle ones.
        live_total = len(self._live_thread_ids())
        cap = self._max_live
        if live_total > cap:
            idle = [
                (self._records[t].last_activity, t)
                for t in self._live_thread_ids(idle_only=True)
            ]
            idle.sort()
            for _, tid in idle[: live_total - cap]:
                await self._evict_session(tid)
        # #274: independently age out persistent shells preserved past the client reap.
        await self._reap_detached_shells(now)

    async def _reaper_loop(self) -> None:
        """Periodic idle-client reaper (#179). Sleeps _REAPER_INTERVAL between sweeps;
        all errors swallowed so it never dies."""
        while True:
            try:
                await asyncio.sleep(_REAPER_INTERVAL)
            except asyncio.CancelledError:
                break
            with contextlib.suppress(Exception):
                await self._reap_once()

    def start_reaper(self) -> None:
        """Start the idle-client reaper (idempotent). Called once at startup."""
        if self._reaper_task is None or self._reaper_task.done():
            self._reaper_task = asyncio.create_task(self._reaper_loop())

    # --------------------------------------------------- schedule runner (#188)

    async def _fire_schedule(self, row: dict) -> None:
        """Run one due schedule: advance next_run FIRST (so a slow/failing run can't
        re-fire in a tight loop), post a small notice, then submit the prompt into its
        session via the normal queue. All best-effort — errors are stamped, not raised."""
        from app.core import schedules  # local import: pure module, avoids a top-level cycle risk
        sid = int(row["id"])
        now = time.time()
        # NOTE: last_status reflects DISPATCH, not turn outcome — "running" once submitted,
        # "ok" once handle_text returns (it only ENQUEUES the turn; a later turn error is not
        # captured here). "ok" therefore means "dispatched", not "succeeded" (#258).
        status = "ok"
        try:
            spec = json.loads(row["spec"])
            nxt = schedules.next_run_after(spec, now)
        except Exception:
            # Corrupt spec → disable it rather than spin; surfaces in /schedules.
            await db.set_schedule_enabled(sid, False)
            await db.update_schedule_run(sid, now, now, "bad-spec")
            return
        # #254: orphan guard. If the session was deleted, do NOT let handle_text/ensure_thread
        # resurrect it (the db cascade should prevent this, but disable any legacy orphan).
        if await db.get_thread(int(row["thread_id"])) is None:
            await db.set_schedule_enabled(sid, False)
            await db.update_schedule_run(sid, now, now, "orphaned")
            return
        # #255: re-check the owner is still allowlisted — a schedule created while allowed must
        # not keep firing (and consuming the subscription) after the owner is removed/expires.
        owner_uid = int(row["owner_uid"]) if row.get("owner_uid") is not None else 0
        if self.allowlist and not self.allowlist.is_allowed(owner_uid, None):
            await db.set_schedule_enabled(sid, False)
            await db.update_schedule_run(sid, now, now, "revoked")
            return
        # Memory gate (this host has NO swap): a fire spawns a claude jail. If MemAvailable is
        # below the floor, evict idle clients; if still tight, DEFER — leave next_run UNTOUCHED
        # so the next ~30s sweep retries, rather than advancing past the slot or risking an OOM
        # kill. Best-effort and silent (no run notice on a deferral).
        if self._mem_available_mb() < self._min_free_mb:
            await self._relieve_memory()
            if self._mem_available_mb() < self._min_free_mb:
                return
        await db.update_schedule_run(sid, nxt, now, "running")
        try:
            lang = i18n.cached_lang(int(row["chat_id"]))
            with contextlib.suppress(Exception):
                await self.bot.send_message(
                    int(row["chat_id"]),
                    i18n.t("schedule.run_notice", lang,
                           prompt=markup.escape_html((row["prompt"] or "")[:80])),
                    parse_mode="HTML",
                )
            await self.handle_text(int(row["chat_id"]), int(row["thread_id"]), row["prompt"])
        except Exception:
            status = "error"
        with contextlib.suppress(Exception):
            await db.update_schedule_run(sid, nxt, now, status)

    async def _schedule_loop(self) -> None:
        """Fire due recurring schedules (#188). Sweeps every _SCHEDULE_INTERVAL; all
        errors swallowed so the loop never dies. Each due row is fired sequentially so a
        burst can't spawn many concurrent turns (the per-session queue serializes too)."""
        while True:
            try:
                await asyncio.sleep(_SCHEDULE_INTERVAL)
            except asyncio.CancelledError:
                break
            with contextlib.suppress(Exception):
                due = await db.due_schedules(time.time())
                for row in due:
                    with contextlib.suppress(Exception):
                        await self._fire_schedule(row)

    def start_scheduler(self) -> None:
        """Start the recurring-schedule runner (idempotent). Called once at startup."""
        if self._schedule_task is None or self._schedule_task.done():
            self._schedule_task = asyncio.create_task(self._schedule_loop())

    # ------------------------------------------------- archive retention (#178)

    async def _resolve_archive_retention_days(self) -> int:
        """The effective archive-retention period in days: the owner's runtime value
        (kv ``archive_retention_days``, set from /settings → Admin) if present, else
        the startup default (``settings.archive_retention_days``, env-overridable).
        0 = keep forever."""
        raw = await db.get_kv("archive_retention_days")
        if raw is not None:
            try:
                return max(0, int(raw))
            except (TypeError, ValueError):
                pass
        return max(0, int(getattr(self.settings, "archive_retention_days", 180) or 0))

    async def _archive_purge_loop(self) -> None:
        """Periodically delete deleted-session archive bundles older than the
        configured retention (#178). Runs once at startup, then every
        ``_ARCHIVE_PURGE_INTERVAL``. The purge runs in a thread (file I/O) and all
        errors are swallowed so the loop never dies."""
        while True:
            with contextlib.suppress(Exception):
                days = await self._resolve_archive_retention_days()
                if days > 0:
                    await asyncio.to_thread(
                        archive.purge_expired, self.settings.base_workdir, days
                    )
            try:
                await asyncio.sleep(_ARCHIVE_PURGE_INTERVAL)
            except asyncio.CancelledError:
                break

    def start_archive_purger(self) -> None:
        """Start the archive-retention purger (idempotent). Called once at startup."""
        if self._archive_purge_task is None or self._archive_purge_task.done():
            self._archive_purge_task = asyncio.create_task(self._archive_purge_loop())

    # ------------------------------------------------- OAuth token refresh (#191)

    def start_token_refresher(self) -> None:
        """Start the proactive OAuth token refresher (idempotent). Keeps the on-disk
        subscription token fresh so a turn after a long idle gap never 401s on an
        expired token (see token_refresh). Best-effort + fail-soft — disable with
        ``OAUTH_REFRESH=0`` in .env if ever needed."""
        if os.environ.get("OAUTH_REFRESH", "1").strip() in ("0", "false", "off", "no"):
            return
        if self._token_refresh_task is None or self._token_refresh_task.done():
            self._token_refresh_task = asyncio.create_task(token_refresh.refresh_loop())

    # ------------------------------------------------------------------ status

    def status(self, thread_id: int) -> dict:
        """Return a snapshot for /status without touching the DB.

        cache_seconds_left is the remaining prompt-cache warm window; busy means
        a turn is currently running; queued is the number of pending prompts.
        """
        rec = self._records.get(thread_id)
        if rec is None:
            return {
                "mode": None,
                "model": None,
                "cwd": None,
                "busy": False,
                "queued": 0,
                "cache_seconds_left": 0,
                "rate": None,
                "stream": True,
                "last_prompt": False,
            }

        busy = rec.worker is not None and not rec.worker.done()
        queued = rec.queue.qsize()
        elapsed = time.monotonic() - rec.last_activity
        cache_left = max(0, int(_CACHE_WINDOW_SECONDS - elapsed))
        return {
            "mode": rec.mode,
            "model": rec.model,
            "cwd": rec.cwd,
            "busy": busy,
            "queued": queued,
            "cache_seconds_left": cache_left,
            "rate": rec.rate,
            "stream": rec.stream_enabled,
            "last_prompt": bool(rec.last_prompt),
        }

    # ------------------------------------------------------------------ helpers

    async def _deliver_outbox(
        self, rec: "_ThreadRecord", chat_id: int, send_tid: int | None
    ) -> None:
        """#187: after a turn, deliver any files the agent staged in <cwd>/outbox/ to
        the chat as native attachments (images → photo, else document), then delete the
        staging copies. Per-file size caps + a per-turn count cap; too-big files are
        dropped with one aggregated note. Best-effort: a send failure leaves that file
        in place so the next turn's drain retries it."""
        session = rec.session
        cwd = getattr(session, "cwd", None) if session is not None else None
        if not cwd:
            return
        outbox = Path(cwd) / _OUTBOX_DIRNAME
        try:
            if not outbox.is_dir():
                return
            files = sorted(
                (p for p in outbox.iterdir() if p.is_file()),
                key=lambda p: p.stat().st_mtime,
            )
        except OSError:
            return
        if not files:
            return
        lang = i18n.cached_lang(chat_id)
        kwargs: dict = {"message_thread_id": send_tid} if send_tid is not None else {}
        too_big: list[str] = []
        # Bound the work AND the noise to the count cap; anything beyond it stays in
        # outbox/ and is delivered after the next turn.
        for path in files[:_OUTBOX_MAX_FILES]:
            try:
                size = path.stat().st_size
            except OSError:
                continue
            is_img = path.suffix.lower() in _OUTBOX_IMG_EXTS
            limit = _OUTBOX_IMG_BYTES if is_img else _OUTBOX_DOC_BYTES
            if size > limit:
                too_big.append(path.name)
                with contextlib.suppress(OSError):
                    path.unlink()          # a staging copy we can never deliver
                continue
            try:
                # #285: a staged file can be multi-MB — read it off the event loop so a turn
                # that emits files doesn't block other users (the empty-outbox common case
                # stays cheap: just the is_dir + empty iterdir above).
                data = await asyncio.to_thread(path.read_bytes)
            except OSError:
                continue
            if not is_img:
                # #206: a .md/.txt the agent dropped in outbox/ is shipped verbatim;
                # add a UTF-8 BOM (if absent) so mobile viewers don't mojibake non-ASCII.
                data = markup.ensure_text_bom(data, path.name)
            upload = BufferedInputFile(data, filename=path.name)
            try:
                if is_img:
                    await self.bot.send_photo(
                        chat_id, photo=upload, caption=path.name, **kwargs
                    )
                else:
                    await self.bot.send_document(chat_id, document=upload, **kwargs)
            except Exception:
                continue                   # transient failure → leave for the next turn
            with contextlib.suppress(OSError):
                path.unlink()              # delivered → drop the staging copy
        if too_big:
            await self._notify(
                chat_id, send_tid,
                i18n.t("outbox.too_big", lang, names=", ".join(too_big)),
            )
        # If the agent staged more than the per-turn cap (or a send failed), the rest
        # remain in outbox/ and go out after the next turn — tell the user.
        try:
            remaining = sum(1 for p in outbox.iterdir() if p.is_file())
        except OSError:
            remaining = 0
        if remaining:
            await self._notify(chat_id, send_tid, i18n.t("outbox.more", lang, n=remaining))

    async def _notify(self, chat_id: int, thread_id: int | None, text: str) -> None:
        """Send a plain notice into a topic, swallowing transient failures."""
        kwargs: dict = {}
        if thread_id is not None:
            kwargs["message_thread_id"] = thread_id
        with contextlib.suppress(Exception):
            await self.bot.send_message(chat_id, text, **kwargs)

    async def drain(self, timeout: float = 40.0) -> bool:
        """#325: graceful-shutdown step — stop STARTING new turns and wait for the in-flight
        ones to FINISH, so a restart doesn't kill a turn mid-generation (the #324 incident) or
        tear its transcript. Per-thread workers stop pulling new queued turns; the running ones
        complete. Bounded by ``timeout``; returns True if fully drained, False on timeout (the
        caller then tears down — #324 makes any still-running turn resumable). Idempotent.

        Requires ``KillMode=mixed`` in the systemd unit so SIGTERM reaches ONLY the bot (not the
        jailed ``claude`` children) — else systemd kills the subprocesses and there is nothing
        to drain. Pending (not-yet-started) queued turns are dropped; the user re-sends (the
        session keeps its context via the persisted resume id)."""
        self._draining = True
        if self._active_turns <= 0:
            return True
        logger.info("draining %d active turn(s), up to %.0fs…", self._active_turns, timeout)
        try:
            await asyncio.wait_for(self._idle_event.wait(), timeout)
            logger.info("drain complete — all in-flight turns finished")
            return True
        except asyncio.TimeoutError:
            logger.warning("drain timed out — %d turn(s) still active, tearing down",
                           self._active_turns)
            return False

    async def aclose(self) -> None:
        """Best-effort shutdown: forcefully cancel workers and disconnect clients.

        Unlike /stop (graceful interrupt) we cancel hard here — the process is
        exiting. We do NOT clear the DB (no db.reset_thread), so code-mode topics
        keep their persisted session id and resume after a restart.
        """
        # Stop the account-usage poller (#135) first.
        if self._usage_task is not None and not self._usage_task.done():
            self._usage_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._usage_task
        # #179: stop the idle-client reaper too.
        if self._reaper_task is not None and not self._reaper_task.done():
            self._reaper_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reaper_task
        # #178: stop the archive-retention purger too.
        if self._archive_purge_task is not None and not self._archive_purge_task.done():
            self._archive_purge_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._archive_purge_task
        # #188: stop the schedule runner too.
        if self._schedule_task is not None and not self._schedule_task.done():
            self._schedule_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._schedule_task
        # #191: stop the OAuth token refresher too.
        if self._token_refresh_task is not None and not self._token_refresh_task.done():
            self._token_refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._token_refresh_task
        for thread_id in list(self._records.keys()):
            rec = self._records.get(thread_id)
            if rec is None:
                continue
            with contextlib.suppress(Exception):
                async with rec.lock:
                    _drain_queue(rec.queue)
                    worker = rec.worker
                    if worker is not None and not worker.done():
                        worker.cancel()
                        with contextlib.suppress(asyncio.CancelledError, Exception):
                            await worker
                    rec.worker = None
                    if rec.session is not None:
                        old = rec.session
                        rec.session = None
                        with contextlib.suppress(Exception):
                            await old.aclose()
        # #274: close any persistent shells preserved across a reap.
        for tid in list(self._detached_shells.keys()):
            entry = self._detached_shells.pop(tid, None)
            if entry is not None:
                with contextlib.suppress(Exception):
                    await entry[0].close()
        self._records.clear()


# ---------------------------------------------------------------------- utils


def _attachment_icon(attachments) -> str:
    """A small icon for a queued turn's attachments ("" if there are none)."""
    if not attachments:
        return ""
    types = {a.get("type") for a in attachments if isinstance(a, dict)}
    if "image" in types:
        return "🖼"
    if "document" in types:
        return "📄"
    return "📎"


def _unpack_queue_item(item) -> tuple:
    """Normalize a queue item to (qid, text, attachments).

    Items are (qid, text, attachments) tuples; tolerate a legacy (text, atts)
    pair or a bare string so peeking never raises on an unexpected shape.
    """
    if isinstance(item, tuple):
        if len(item) >= 3:
            return item[0], item[1], item[2]
        if len(item) == 2:
            return None, item[0], item[1]
        return None, item[0] if item else "", None
    return None, item, None


def _drain_queue(queue: asyncio.Queue) -> None:
    """Discard all pending items so a cancelled worker leaves nothing behind."""
    while True:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        else:
            queue.task_done()


