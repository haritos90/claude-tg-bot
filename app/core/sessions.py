"""Per-thread orchestration: session, serial worker, task queue.

- One isolated record per forum topic
- Nothing is shared across thread_ids
- Messages during a run queue in the same session
- /stop interrupts, cancels the worker, clears queue
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import logging
import os
import re
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone  # Daily CLI-update slot
from pathlib import Path
from types import SimpleNamespace

from aiogram.types import BufferedInputFile

from app.storage import archive
from app.storage import db
from app import i18n
from app.telegram import markup
from app.core import token_refresh
from app.core import models  # CLI model catalog
from app.core import cli_update  # Periodic CLI update and jail re-stage
from app.storage import usage
from app.access import settings_schema
from app.core.engine import ClaudeSession
from app.telegram.streamer import Streamer, resolve_speed
from app.telegram.streamer import draft_release_period
from app.telegram.streamer import draft_push_enabled
from app.access.permissions import PermissionGate

logger = logging.getLogger(__name__)  # Drain progress goes to the journal

# Prompt cache stays warm ~5 minutes after last request.
_CACHE_WINDOW_SECONDS = 300.0


class FairAdmission:
    """Fair concurrency gate admitting turns round-robin by key.

    - At most `slots` turns run at once
    - Round-robin per user stops burst starvation
    - Cancellation-safe: handed slots pass on, never leak
    - Drop-in for Semaphore locked/acquire/release
    """

    def __init__(self, slots: int) -> None:
        self._slots = max(1, int(slots))
        self._in_use = 0
        self._waiters: dict = {}        # Per-key FIFO deque of futures
        self._order: deque = deque()    # Keys with waiters, round-robin order

    def locked(self) -> bool:
        """True when every slot is taken."""
        return self._in_use >= self._slots

    @property
    def active(self) -> int:
        return self._in_use

    async def acquire(self, key) -> None:
        """Take a slot, waiting round-robin by key if all busy."""
        if self._in_use < self._slots:
            self._in_use += 1
            return
        fut = asyncio.get_running_loop().create_future()
        q = self._waiters.get(key)
        if q is None:
            q = deque()
            self._waiters[key] = q
        q.append(fut)
        if len(q) == 1:                 # Key's first waiter joins rotation
            self._order.append(key)
        try:
            await fut
        except asyncio.CancelledError:
            # Drop our future if cancelled while waiting.
            # - If cancelled after handoff, pass the slot on
            # - Otherwise the slot would leak
            if not fut.done():
                with contextlib.suppress(ValueError):
                    q.remove(fut)
            elif not fut.cancelled():
                self.release()
            raise

    def release(self) -> None:
        """Release a slot, handing it round-robin to the next waiter."""
        while self._order:
            key = self._order.popleft()
            q = self._waiters.get(key)
            if not q:
                self._waiters.pop(key, None)
                continue
            fut = q.popleft()
            if q:                       # Key still waiting: back of rotation
                self._order.append(key)
            else:
                self._waiters.pop(key, None)
            if not fut.done():          # Hand slot over; `in_use` unchanged
                fut.set_result(None)
                return
            # Waiter cancelled in flight: try the next
        self._in_use -= 1               # Nobody waiting: slot is now free
        if self._in_use < 0:
            self._in_use = 0


# Outbox send-back: host delivers agent-dropped files after each turn.
# - Images go as photos, the rest as documents
# - Per-file size caps; image cap mirrors inbound limit
# - Count cap stops a runaway agent spamming the chat
_OUTBOX_DIRNAME = "outbox"
_OUTBOX_IMG_BYTES = 5 * 1024 * 1024
# Document cap matches /export and Telegram's ~50 MB send limit.
# - Lets the agent archive the whole workdir into outbox/
_OUTBOX_DOC_BYTES = 49 * 1024 * 1024
_OUTBOX_MAX_FILES = 10
_OUTBOX_IMG_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
# Show live context size in the plate only above this.
# - Small contexts aren't interesting
_CTX_STATUS_MIN = 50_000

# Longest auto-name we adopt, for session-label readability.
# - Manual /rename is uncapped
_AI_TITLE_MAX = 64
# Message-derived names are cut to the /sessions button width.
# - Browser shows `name[:40]`; cut on a word boundary
# - Avoids chopping mid-word
_BUTTON_NAME_MAX = 40


def _clip_words(s: str, limit: int = _BUTTON_NAME_MAX) -> str:
    """Whitespace-collapsed text cut to `limit` on a word boundary.

    - Ellipsis marks the cut; one over-long word is hard-cut
    """
    s = " ".join(s.split())
    if len(s) <= limit:
        return s
    cut = s[:limit - 1]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" -—–:;,.") + "…"


def _user_text(obj: dict) -> str:
    """Plain text of a transcript user line.

    - Content is a str or list of blocks
    - Empty for image-only or tool-result messages
    """
    msg = obj.get("message") or {}
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return " ".join(
            b.get("text", "") for b in c
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


# Injected user prompts that are not a real topic.
# - Never name a session after one
# - Auto-recap prompt is the one landing as user line
_NON_TOPIC_PREFIXES = ("recap our conversation",)


def _topic_from_text(txt: str) -> str | None:
    """Session-name candidate from a user message, or None.

    - None for bare greetings, probes, injected prompts
    - Conservative: fires only when no ai-title exists
    """
    if not txt:
        return None
    s = " ".join(txt.split())  # Collapse newlines and whitespace runs
    if any(s.lower().startswith(p) for p in _NON_TOPIC_PREFIXES):
        return None
    if sum(c.isalpha() for c in s) < 10:  # Greetings and acks ("ok", "hi", "yo")
        return None
    # As many whole words as fit on the /sessions button.
    return _clip_words(s).strip() or None


def _first_words(txt: str) -> str | None:
    """Name from the first user message as typed.

    - Cut to the button width
    - None for injected prompts or text without letters/digits
    """
    if not txt:
        return None
    s = " ".join(txt.split())
    if any(s.lower().startswith(p) for p in _NON_TOPIC_PREFIXES):
        return None
    if not any(c.isalnum() for c in s):
        return None
    return _clip_words(s) or None


def _read_session_title(
    cwd: str | None, session_id: str | None
) -> tuple[str | None, str | None]:
    """Read a transcript once, returning `(ai_title, fallback)`.

    - `ai_title` is the last ai-title line, or None
    - `fallback` names first user message; used without ai-title
    - Path: `<sid>/state/<encoded-cwd>/<session_id>.jsonl`
    - Single pass avoids rescanning an unbounded transcript
    """
    if not cwd or not session_id:
        return (None, None)
    try:
        path = archive.live_transcript_dir(cwd) / f"{session_id}.jsonl"
        if not path.is_file():
            return (None, None)
        title = None
        fallback = None
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                # Prefilter: skip JSON parsing unless the line can matter.
                if '"ai-title"' in line:
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue
                    if obj.get("type") == "ai-title" and obj.get("aiTitle"):
                        title = str(obj["aiTitle"]).strip()
                elif fallback is None and '"user"' in line:  # Hunt a fallback name
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue
                    if obj.get("type") == "user":
                        fallback = _topic_from_text(_user_text(obj))
        return (title[:_AI_TITLE_MAX] if title else None, fallback)
    except OSError:
        return (None, None)


# Minimum reply length worth naming a session by.
# - Liveness-probe answers stay well under it
# - Real answers clear it easily
_REPLY_TOPIC_MIN = 200
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_MD_NOISE_RE = re.compile(r"[*_`#>|~\[\]]+")
_SENTENCE_END_RE = re.compile(r"(?<=[.!?…])\s+")


def _clip_title(s: str) -> str:
    """Trim a reply-derived name to button width, capitalized."""
    s = _clip_words(" ".join(s.split()).strip(" -—–:;,."))
    return (s[:1].upper() + s[1:]) if s else s


def _topic_from_reply(txt: str) -> str | None:
    """Name candidate from an assistant reply.

    - Used only when no ai-title or user text qualifies
    - None for short replies such as probe answers
    - Prefers first bold phrase of 2+ words
    - Else the first sentence with real words
    """
    if not txt or len(txt.strip()) < _REPLY_TOPIC_MIN:
        return None
    for m in _BOLD_RE.finditer(txt):
        cand = (m.group(1) or m.group(2) or "").strip()
        if len(cand.split()) >= 2 and sum(c.isalpha() for c in cand) >= 6:
            return _clip_title(_MD_NOISE_RE.sub("", cand))
    for line in txt.splitlines():
        plain = _MD_NOISE_RE.sub("", line).strip()
        if sum(c.isalpha() for c in plain) < 10:
            continue
        sentence = _SENTENCE_END_RE.split(plain, 1)[0]
        return _clip_title(sentence)
    return None


def _read_name_fallbacks(cwd: str | None,
                         session_id: str | None) -> tuple[str | None, str | None]:
    """Two lower name tiers from one transcript pass.

    - Returns `(first_words, reply_topic)`
    - Reply topic only used when user sent no text
    - Meta and tool-result user lines are skipped
    """
    if not cwd or not session_id:
        return (None, None)
    first = topic = None
    try:
        path = archive.live_transcript_dir(cwd) / f"{session_id}.jsonl"
        if not path.is_file():
            return (None, None)
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if first is None and '"user"' in line:
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue
                    if obj.get("type") == "user" and not obj.get("isMeta"):
                        text = _user_text(obj)
                        if text.strip() and not text.lstrip().startswith("<"):
                            first = _first_words(text)
                elif topic is None and '"assistant"' in line:
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue
                    if obj.get("type") != "assistant":
                        continue
                    content = (obj.get("message") or {}).get("content")
                    blocks = (content if isinstance(content, list)
                              else [{"type": "text", "text": content}]
                              if isinstance(content, str) else [])
                    for b in blocks:
                        if isinstance(b, dict) and b.get("type") == "text":
                            topic = _topic_from_reply(b.get("text") or "")
                            if topic:
                                break
                if first is not None and topic is not None:
                    break
    except OSError:
        return (None, None)
    return (first, topic)


def _ctx_total(info) -> int:
    """Extract total tokens in context from a usage result.

    - Accepts a dict or object; 0 when unavailable
    """
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


# Sample for /test: 3 paragraphs, 5x5 table, x86 disasm.
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

Finally an inline **SVG diagram**: in a chat session the bot rasterizes this to a PNG and sends it as a photo. Example — a nightstand built from a washing-machine body, using the round porthole as the cabinet door:

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
# How often to poll the account usage endpoint.
# - 5h and 7d windows move slowly, so 5 minutes
# - Keeps footer and pin cheaply fresh
_USAGE_POLL_INTERVAL = 300.0
# Idle-client reaper sweep interval in seconds.
# - Cheap: compares timestamps and MemAvailable
# - Closes idle live clients over TTL or cap
_REAPER_INTERVAL = 60.0
# Seconds between CLI updater due-time checks.
# - Round starts at a fixed daily UTC time
# - Polling each minute starts it on time
_CLI_UPDATE_POLL = 60.0
# Seconds to wait for Telegram's held message after press.
# - Past this, the press counts as STOP
# - Held message arrives 20-30 ms after the press update
# - 1 s leaves a wide margin and still feels instant
_PUSH_STOP_WAIT_SECS = 1.0
# Delay before the startup model-catalog probe.
# - Runs post-READY, off the startup path
# - It spawns the CLI and reaches the network
_CLI_PROBE_DELAY = 20.0
# Untitled-session sweep: first run after startup, then per interval.
# - Names or disposes sessions for every DM user
# - Interaction-driven sweeps in handlers run in between
_UNTITLED_SWEEP_FIRST = 120.0
_UNTITLED_SWEEP_INTERVAL = 86400.0
# Archive-retention purge sweep interval in seconds.
# - Bundles move slowly, so daily suffices
# - Also runs once at startup
_ARCHIVE_PURGE_INTERVAL = 86400.0
# Schedule runner sweep interval for due recurring prompts (seconds).
_SCHEDULE_INTERVAL = 30.0

# Cap on prompts waiting behind a running turn, per session.
# - Further follow-ups are rejected, not queued
# - The running turn itself does not count
# - `handle_text()` return codes follow, for queued/full UX
MAX_QUEUED_MESSAGES = 5
SUBMIT_STARTED = 0      # Ran immediately; worker was idle
SUBMIT_QUEUE_FULL = -1  # Rejected: too many prompts waiting
SUBMIT_INJECTED = -2    # Handed to the running turn
# Any value above 0: queued, at that many waiting

# Line-interactive commands work; only full-screen TUIs are refused.
# - Persistent shell forwards the next message as input
# - TUIs can't render in a chat bubble (snapshot-and-send)
# - Heuristic checks the first command word only
_SHELL_TUI_CMDS = {
    "vim", "vi", "nvim", "nano", "emacs", "pico", "less", "more", "man", "top", "htop",
    "btop", "watch", "tmux", "screen", "vimdiff",
}


def _is_fullscreen_tui_cmd(cmd: str) -> bool:
    """True if the command is a full-screen TUI.

    - Such programs cannot render in a chat
    """
    parts = cmd.split()
    if not parts:
        return False
    base = parts[0].rsplit("/", 1)[-1].lower()
    return base in _SHELL_TUI_CMDS


# Typed key tokens for keys chat can't type.
# - Arrow pickers, Enter, Ctrl-C while a program awaits input
# - A message made only of tokens sends raw key bytes
# - Tokens chain, e.g. ".down .down .enter"
# - Prefix is "." not ":" (Telegram opens emoji search)
# - Inline keypad is primary; tokens are the typed fallback
_SHELL_KEYS = {
    ".enter": b"\r", ".return": b"\r", ".up": b"\x1b[A", ".down": b"\x1b[B",
    ".left": b"\x1b[D", ".right": b"\x1b[C", ".tab": b"\t", ".esc": b"\x1b",
    ".space": b" ", ".bs": b"\x7f", ".ctrl-c": b"\x03", ".c-c": b"\x03",
    ".pgup": b"\x1b[5~", ".pgdn": b"\x1b[6~", ".home": b"\x1b[H", ".end": b"\x1b[F",
}
# Keypad buttons map to key bytes via short callback tokens.
_SHELL_CB_KEYS = {
    "up": b"\x1b[A", "down": b"\x1b[B", "left": b"\x1b[D", "right": b"\x1b[C",
    "enter": b"\r", "esc": b"\x1b", "tab": b"\t", "space": b" ", "bs": b"\x7f",
    "ctrlc": b"\x03", "pgup": b"\x1b[5~", "pgdn": b"\x1b[6~", "home": b"\x1b[H", "end": b"\x1b[F",
}


def shell_keypad(more: bool = False):
    """Inline keypad for the interactive shell.

    - Each button sends one key via `shk:<key>` callback
    - `more` flips to the extra keys
    """
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
    """Lowercase only the first token of a command, else None.

    - Fixes phone keyboards auto-capitalizing the command name
    - Arguments and paths stay case-sensitive
    - Used only as retry after exit code 127
    """
    if not cmd or not cmd[0].isascii() or not cmd[0].isupper():
        return None
    parts = cmd.split(None, 1)
    head = parts[0].lower()
    if head == parts[0]:
        return None
    return head + (" " + parts[1] if len(parts) > 1 else "")


def _shell_input_keys(text: str) -> bytes | None:
    """Parse a key-token message into raw bytes, or None."""
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


def parse_update_time(raw) -> tuple[int, int] | None:
    """Parse a daily UTC update time into `(hour, minute)`.

    - Accepts "HH:MM" or "H"
    - None for "off", "", "never", "none", or malformed
    """
    text = str(raw or "").strip().lower()
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?", text)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def format_update_time(hm: tuple[int, int] | None) -> str:
    """Format `(hour, minute)` as "HH:MM"; None becomes "off"."""
    return f"{hm[0]:02d}:{hm[1]:02d}" if hm else "off"


def last_update_slot(now: float, hm: tuple[int, int]) -> float:
    """Epoch seconds of the latest daily `hm` before `now`."""
    dt = datetime.fromtimestamp(now, tz=timezone.utc)
    slot = dt.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
    if slot > dt:
        slot -= timedelta(days=1)
    return slot.timestamp()


@dataclass
class _ThreadRecord:
    """In-memory orchestration state for one isolated thread."""

    session: ClaudeSession | None = None
    # Config snapshot the live session was built for.
    # - A change in /mode, /model or /cwd forces a rebuild
    mode: str | None = None
    model: str | None = None
    cwd: str | None = None
    permission_mode: str | None = None
    big_memory: bool | None = None
    # Per-user global memory resolved for the session owner.
    # - A change rebuilds so `setting_sources` flips
    global_memory: bool | None = None
    # Pro-command options the live session was built for.
    # - A change rebuilds
    effort: str | None = None
    max_turns: int | None = None
    add_dirs: tuple = ()
    fork: bool = False
    # Per-session enabled tools the live session was built for.
    # - A change rebuilds
    # - Tuple, or None for the mode's default set
    tools_enabled: tuple | None = None
    # Per-user tool cap the live session was built for.
    # - Owner edits trigger a rebuild
    # - Tuple, or None when uncapped
    tool_cap: tuple | None = None
    # Manager's `_cli_generation` when this client was built.
    # - Older than the manager's means a replaced CLI binary
    cli_generation: int = 0

    # Queue items are `(qid, text, attachments)` tuples.
    # - `qid` is a per-thread monotonic id, for cancel-by-id
    # - `attachments` is None or Anthropic content-block dicts
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    next_qid: int = 1
    worker: asyncio.Task | None = None
    streamer: Streamer | None = None
    last_activity: float = field(default_factory=time.monotonic)
    # Per-user idle TTL in seconds, resolved at build.
    # - None means global default; 0 never reaps
    # - The reaper reads it per record
    idle_ttl: float | None = None
    rate: object | None = None  # Latest RateLimitInfo seen for thread
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # Per-thread display flags, defaulting to live streaming.
    # - `last_prompt` holds the latest submitted prompt, for /retry
    stream_enabled: bool = True
    # Shell-mode overlay: route text to a jailed command.
    # - Mirrors persisted `ThreadState.shell_mode`; re-synced on rebuild
    shell_mode: bool = False
    # Live task-list card toggle, code sessions only.
    # - Re-synced from effective settings on every `_ensure`; no rebuild
    # - Default off
    todo_card: bool = False
    # Current session label and whether auto-naming is on.
    # - Mirror persisted ThreadState; re-synced every `_ensure`
    # - Turn-end auto-namer writes only on change
    # - It skips entirely once /rename clears `name_auto`
    name: str | None = None
    name_auto: bool = True
    # True when the shell paused for interactive input.
    # - The next message goes to the running program
    shell_awaiting: bool = False
    # Message bearing the inline keypad, and its rendered body.
    # - /shell OFF strips the stale keypad
    # - /shell ON restores it where input paused
    shell_kb_chat: int | None = None
    shell_kb_msg: int | None = None
    shell_last_render: str | None = None
    # Most recent `(text, attachments)` submitted, used by /retry.
    last_prompt: tuple | None = None
    # Forced-on toggles the live session was built for.
    # - plus last-known context size, shown in next plate
    auto_compact: bool = True
    ctx_status: bool = True
    last_context_tokens: int = 0
    # Live warm-cache countdown message and its ticking task.
    # - cancelled when the next turn resets the window
    hot_cache_msg_id: int | None = None
    hot_cache_task: asyncio.Task | None = None


def _coerce_perm(mode: str | None) -> str:
    """Resolve a stored permission mode to a current value.

    - Legacy "default" maps to "acceptEdits"
    - Other modes pass through unchanged
    """
    return "acceptEdits" if (not mode or mode == "default") else mode


def _send_thread_id(thread_id: int) -> int | None:
    """Map a session key to a Telegram message_thread_id.

    - Only positive keys are real forum topics
    - General (0) and negative DM keys map to None
    """
    return thread_id if thread_id > 0 else None


class SessionManager:
    """Owns one isolated worker pipeline per forum topic."""

    def __init__(self, bot, settings, gate: PermissionGate, allowlist=None) -> None:
        self.bot = bot
        self.settings = settings
        self.gate = gate
        # Optional allowlist; omitted in some tests.
        # - resolves per-user build prefs, e.g. global memory
        # - `None` keeps every session isolated
        self.allowlist = allowlist
        self._records: dict[int, _ThreadRecord] = {}

        # Account-wide subscription rate-limit windows, keyed by `rate_limit_type`.
        self.rate_by_type: dict[str, object] = {}
        # Usage display: one of off, footer, pinned, both.
        self.usage_mode: str = "footer"
        # Global toggle: each fenced code block as its own message.
        # - default on; persisted
        self.split_code_messages: bool = True
        # Global on/off for the Working plate and Stop control.
        # - persisted
        self.working_plate: bool = True
        # Reveal pacing for the dormant group write-head.
        # - fixed at normal, not user-configurable
        # - DM streaming uses native drafts, no caret
        self.caret_speed: str = "normal"
        # Chat where the bot talks (pinned usage message).
        self._main_chat_id: int | None = None
        # `(chat_id, message_id)` of the pinned usage message, if any.
        self._pinned: tuple[int, int] | None = None
        # Fingerprint of the last persisted rate snapshot.
        # - skips the DB write and pin edit on repeats
        self._last_rate_sig: tuple | None = None
        # True while showing a synthesized limited five_hour window.
        # - rate events keep saying allowed after a limit failure
        # - cleared on the next successful turn
        self._synth_limit: bool = False
        # Background task polling the account usage endpoint.
        # - SDK rate events only report percent near a limit
        self._usage_task: asyncio.Task | None = None
        # Concurrency and RAM management.
        # - fair turn gate caps simultaneous active turns
        # - reaper closes idle live clients (~400-600 MB each)
        # - history is on disk; `resume` rebuilds it
        # - `getattr` fallbacks let a minimal settings stub construct
        self._max_live: int = int(getattr(settings, "max_live_clients", 4) or 4)
        self._idle_ttl: float = float(getattr(settings, "idle_ttl_sec", 360) or 360)
        # Idle seconds before a fresh session; 0 = off.
        # - per-user override via `idle_reset_min`
        self._idle_reset: float = float(getattr(settings, "idle_reset_sec", 1800) or 0)
        self._min_free_mb: int = int(getattr(settings, "min_free_mb", 400) or 400)
        # Persistent shells kept across a client reap, by `thread_id`.
        # - value is `(shell, monotonic_stash_ts)`
        # - reaped on shell TTL, reset, delete or shutdown
        # - 0 = keep until delete
        self._detached_shells: dict[int, tuple] = {}
        self._shell_ttl: float = float(getattr(settings, "shell_ttl_sec", 86400) or 0)
        # Fair admission, round-robin by user, instead of a plain semaphore.
        # - one user's burst can't starve others
        self._turn_gate: FairAdmission = FairAdmission(
            int(getattr(settings, "max_concurrent_turns", 4) or 4)
        )
        # Graceful drain: on shutdown stop starting new turns.
        # - `_active_turns` counts running turns
        # - `_idle_event` is set when none run
        # - `_draining` stops workers pulling queued turns
        self._draining: bool = False
        self._active_turns: int = 0
        self._idle_event: asyncio.Event = asyncio.Event()
        self._idle_event.set()
        self._reaper_task: asyncio.Task | None = None
        # Background task purging expired archive bundles.
        self._archive_purge_task: asyncio.Task | None = None
        # Background task firing due recurring schedules.
        self._schedule_task: asyncio.Task | None = None
        # Background task refreshing the OAuth token before expiry.
        # - the on-disk token has a hard ~8h life
        self._token_refresh_task: asyncio.Task | None = None
        # Last login-expiry banner display time (epoch).
        # - throttles display to about once a day
        # - in-memory is fine; a restart re-shows it once
        # - spent by the finalize caller after delivery
        self._login_warn_last = 0.0
        # Last creds-file read time for the login-expiry check.
        # - separate from the display throttle
        # - avoids reparsing creds on the event loop every turn
        self._login_check_last = 0.0
        # Periodic CLI update with jail re-stage.
        # - cadence from .env; owner overrides at runtime; 0 = off
        # - lock stops the updater running twice at once
        # - last result feeds the Admin page
        # - daily round at fixed UTC (hour, minute); `None` = off
        self._cli_update_at: tuple[int, int] | None = parse_update_time(
            getattr(settings, "cli_update_at", "12:00"))
        # Messages received per chat.
        # - distinguishes a push that let a held message through
        # - from a press with nothing waiting (a stop)
        self._inbound_by_chat: dict[int, int] = {}
        self._push_tasks: set[asyncio.Task] = set()
        # Bumped when an update replaced the CLI binary.
        # - clients built under older generation recycle once idle, never mid-reply
        self._cli_generation: int = 0
        self._cli_update_task: asyncio.Task | None = None
        self._cli_update_lock: asyncio.Lock = asyncio.Lock()
        self.cli_last_result: cli_update.UpdateResult | None = None
        self.cli_last_check: float = 0.0
        # Background sweep that names or disposes untitled DM sessions.
        self._untitled_task: asyncio.Task | None = None

    # ---- records ----

    def _record(self, thread_id: int) -> _ThreadRecord:
        """Return (creating if needed) the per-thread record. Never shared."""
        rec = self._records.get(thread_id)
        if rec is None:
            rec = _ThreadRecord()
            self._records[thread_id] = rec
        return rec

    def _default_cwd(self, thread_id: int) -> str:
        """Per-thread working directory: `BASE_WORKDIR/<pubid>/work`.

        - Named by the public ULID, not the raw thread_id
        - Matches the id shown in listings and exports
        """
        # Nested layout: cwd is `<sid>/work`, the agent's writable dir.
        # - jail state and transcript live in sibling `<sid>/state`
        # - `state` is not bound into the jail
        # - dir is named by the public ULID
        return str(Path(self.settings.base_workdir) / db.session_pubid(thread_id) / "work")

    # ---- session management ----

    def _resolve_global_memory(self, state: db.ThreadState) -> bool:
        """Whether this session loads global (~/.claude) memory.

        - Per-user owner-granted opt-out of isolation
        - Resolved from the session owner; False without allowlist
        """
        if not self.allowlist:
            return False
        owner_uid = state.created_by if state.created_by else state.chat_id
        try:
            return bool(self.allowlist.global_memory_of(owner_uid, None))
        except Exception:
            return False

    def _resolve_sandbox(self, state: db.ThreadState) -> bool:
        """Whether this session's code client runs in the jail.

        - Resolved via the settings registry, session to global
        - Session `no_sandbox` overrides the global setting
        """
        ctx = settings_schema.make_ctx(state=state, settings=self.settings)
        value, _scope = settings_schema.resolve(settings_schema.get("sandbox"), ctx)
        return bool(value)

    def _resolve_tool_cap(self, state: db.ThreadState):
        """Per-user tool cap for the session owner, or None.

        - None means uncapped
        - Resolved from the allowlist
        """
        if not self.allowlist:
            return None
        owner_uid = state.created_by if state.created_by else state.chat_id
        try:
            return self.allowlist.tool_cap_of(owner_uid, None)
        except Exception:
            return None

    async def _resolve_idle_ttl(self, state: db.ThreadState) -> float:
        """Per-user idle TTL in seconds for the session owner.

        - Reads per-uid KV `idle_ttl_min` (minutes)
        - None means global default; 0 or less never reaps
        - Otherwise minutes times 60
        """
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
        """Idle-to-new-session window in seconds for the session owner.

        - Reads per-uid KV `idle_reset_min` (minutes)
        - None means global default; 0 or less never rotates
        - Handler uses it to decide on a new session
        """
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
        """Clear a session's context without creating a new entry.

        - NULLs resume ids; keeps workdir, transcript, message log
        - Drops the live client so the next message rebuilds
        - Used when rotation can't mint a session at the cap
        """
        with contextlib.suppress(Exception):
            await db.rotate_session_for_idle(thread_id)
        rec = self._records.get(thread_id)
        if rec is not None and rec.session is not None:
            async with rec.lock:
                if rec.session is not None:
                    old = rec.session
                    rec.session = None
                    # Preserve a live jailed shell across in-place rotation.
                    # - running command and cd/env survive the context reset
                    # - re-attach on the next rebuild
                    if getattr(old, "has_live_shell", None) and old.has_live_shell():
                        sh = old.detach_shell()
                        if sh is not None:
                            self._detached_shells[thread_id] = (sh, time.monotonic())
                    with contextlib.suppress(Exception):
                        await old.aclose()

    def _raw_settings(self, state: db.ThreadState) -> dict:
        """Stored per-session values, used when no allowlist is wired.

        - Keeps behaviour identical to reading `state`
        """
        return {
            "model": state.model, "effort": state.effort,
            "permission_mode": _coerce_perm(state.permission_mode),
            "max_turns": state.max_turns,
        }

    def on_generation_stopped(self, chat_id: int, draft_id: int) -> bool:
        """Handle a push-button press on a reply draft.

        - Reply continues in a new draft
        - The message Telegram held then reaches the running turn
        - Returns True when a live draft of that chat matched
        """
        for tid, rec in list(self._records.items()):
            st = rec.streamer
            if st is not None and st.chat_id == chat_id and st.on_push(draft_id):
                # No held message after a press means stop.
                # - runs on the bot's event loop; otherwise skipped
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop is not None:
                    task = loop.create_task(self._stop_unless_pushed(
                        tid, chat_id, st, self._inbound_by_chat.get(chat_id, 0)))
                    self._push_tasks.add(task)
                    task.add_done_callback(self._push_tasks.discard)
                return True
        logger.info("chat %s: push for draft %s — no live reply draft", chat_id, draft_id)
        return False

    async def _stop_unless_pushed(self, thread_id: int, chat_id: int, streamer, mark: int) -> None:
        """Treat a button press with no held message as STOP.

        - Applies if none arrived within `_PUSH_STOP_WAIT_SECS`
        - Interrupts gracefully like /stop; text so far is kept
        - No-op if a message arrived or the reply is over
        """
        try:
            await asyncio.sleep(_PUSH_STOP_WAIT_SECS)
        except asyncio.CancelledError:
            return
        if self._inbound_by_chat.get(chat_id, 0) != mark:
            return  # Held message came through: a push
        rec = self._records.get(thread_id)
        if rec is None or rec.streamer is not streamer or not self._is_busy(thread_id):
            return
        logger.info("thread %s: draft button pressed with no message — stopping the reply",
                    thread_id)
        with contextlib.suppress(Exception):
            await self.stop(thread_id)

    def _model_line(self, rec: _ThreadRecord, lang: str) -> str:
        """Model and effort label for the thinking indicator's first line.

        - Example: "Opus 5.5 · medium"
        - Uses CLI-reported settings when known, else the catalog
        - Effort omitted for models without effort or when unknown
        """
        model = rec.model or self.settings.default_model
        session = rec.session
        name = models.runs_as_label(model, getattr(session, "resolved_model", None))
        if not name or (models.entries() and not models.effort_levels(model)):
            return name or ""
        effort = (getattr(session, "applied_effort", None)
                  or models.effective_effort(model, rec.effort))
        if not effort:
            return name
        return i18n.t("session.model_line", lang, model=name,
                      effort=i18n.maybe_t(f"effort.level.{effort}", lang, effort))

    async def model_and_effort(self, state: db.ThreadState) -> tuple[str, str | None]:
        """Model value and effort level a session effectively runs at.

        - Access-aware, including the `max` effort gate
        - Unset effort resolves to the model's CLI default
        - Effort is None if unsupported or not yet reported
        """
        eff = await self._effective_settings(state)
        model = eff.get("model") or self.settings.default_model
        return model, models.effective_effort(model, eff.get("effort"))

    async def _effective_settings(self, state: db.ThreadState) -> dict:
        """Resolve effective setting values for the session owner.

        - Read-only or hidden options fall back to global default
        - Only delegated options count the user's own value
        - `max` effort needs a grant; full-access is owner-only
        - Raw stored values used when no allowlist is wired
        """
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
        for skey in ("model", "effort", "permission_mode", "max_turns",
                     "auto_compact", "ctx_status", "todo_card"):
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
            # Legacy stored `default` mode is coerced to `acceptEdits`.
            # - file edits and creation then run without a prompt
            "permission_mode": _coerce_perm(eff("permission_mode")),
            "max_turns": eff("max_turns"),
            # Forced-on by default unless the owner delegated a disable.
            "auto_compact": bool(eff("auto_compact")),
            "ctx_status": bool(eff("ctx_status")),
            "todo_card": bool(eff("todo_card")),
        }
        # Capability gates applied to effective values.
        # - mirrors the per-turn gate in `handlers._access_block`
        # - a revoked grant takes effect at run time
        # - no owner bypass, so owner self-revoke downgrades the owner too
        # - a withheld model family never runs, even if stored earlier
        if models.is_hidden(out.get("model")):
            out["model"] = self.settings.default_model
        if out["effort"] == "max" and not self.allowlist.allow_max_effort_of(owner_uid, None):
            # Step down one level under max in the CLI's list.
            # - not every model offers a hardcoded level
            # - `None` = the model's default
            out["effort"] = models.effort_below_max(out.get("model") or self.settings.default_model)
        if out["permission_mode"] == "bypassPermissions" and not is_owner:
            # Soft-revoked full-access reverts to the non-owner baseline `acceptEdits`.
            out["permission_mode"] = "acceptEdits"
        return out

    def _owner_level(self, state: db.ThreadState) -> str:
        """Session owner's access level: "code" or "chat".

        - Tells the model whether the user can self-upgrade
        """
        owner_uid = state.created_by if state.created_by else state.chat_id
        if owner_uid is not None and owner_uid == getattr(self.settings, "owner_id", None):
            return "code"
        if self.allowlist is not None:
            with contextlib.suppress(Exception):
                if self.allowlist.level_of(owner_uid, None) == "code":
                    return "code"
        return "chat"

    def _build_session(self, state: db.ThreadState, eff: dict | None = None) -> ClaudeSession:
        """Construct a fresh ClaudeSession from a thread's stored state.

        - Uses access-resolved values in `eff`; raw state if None
        - Code mode gets the permission callback and resumes
        - Chat mode runs tool-free and never resumes
        """
        eff = eff or self._raw_settings(state)
        send_tid = _send_thread_id(state.thread_id)
        if state.mode == "code":
            # Pass `send_tid` (where to post) and the unique session key.
            # - key is for gate bookkeeping and cancellation
            # - gate uses the effective `permission_mode`
            can_use_tool = self.gate.make_callback(
                state.chat_id, send_tid, state.thread_id, eff["permission_mode"],
                cwd=state.cwd,  # Relativize tool-path previews to workdir
            )
            resume_id = state.code_session_id
        else:
            can_use_tool = None
            # Chat sessions are durable: always resume the persisted id.
            # - saved every turn, so context survives restart or stop
            # - `/reset` starts fresh
            resume_id = state.chat_session_id

        return ClaudeSession(
            mode=state.mode,
            model=eff["model"],
            cwd=state.cwd,
            can_use_tool=can_use_tool,
            resume_session_id=resume_id,
            permission_mode=eff["permission_mode"],
            global_memory=self._resolve_global_memory(state),
            tools_enabled=state.tools_enabled,
            tool_cap=self._resolve_tool_cap(state),
            effort=eff["effort"],
            max_turns=eff["max_turns"],
            add_dirs=state.add_dirs,
            fork=state.fork_pending,
            sandbox=self._resolve_sandbox(state),
            sandbox_uid=self.settings.sandbox_uid,
            sandbox_allow_exec=self.settings.sandbox_allow_exec,
            # Broker on: the jail gets a dummy token.
            # - `ANTHROPIC_BASE_URL` points at the host broker
            # - the real token stays out
            cred_broker_url=(f"http://127.0.0.1:{self.settings.cred_broker_port}"
                             if getattr(self.settings, "cred_broker", False) else None),
            # Egress allowlist, per-jail DoS limits and seccomp.
            # - `getattr`-guarded so a minimal test stub constructs
            # - cpu percent maps to `cpu.max` (100% = one core)
            # - mem MB maps to `memory.max` bytes
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
            auto_compact=eff.get("auto_compact", True),
            user_level=self._owner_level(state),  # Drives the this-session prompt note
            # Per-topic agent-driven session memory.
            # - current saved blob plus persistence hook for `remember`
            # - scoped to this thread
            session_notes=state.session_notes,
            on_remember=functools.partial(db.set_session_notes, state.thread_id),
        )

    async def _get_session(
        self, rec: _ThreadRecord, state: db.ThreadState
    ) -> ClaudeSession:
        """Return the live session, rebuilding if config drifted or absent.

        - Old client is closed first, never leaked
        - An SDK client is never shared across configs
        """
        gmem = self._resolve_global_memory(state)
        tkey = tuple(state.tools_enabled) if state.tools_enabled is not None else None
        cap = self._resolve_tool_cap(state)
        capkey = tuple(cap) if cap is not None else None
        # Compare against effective (access-resolved) values, not stored ones.
        # - owner access or global change triggers a rebuild
        # - applies from the next message
        eff = await self._effective_settings(state)
        rec.idle_ttl = await self._resolve_idle_ttl(state)  # Per-user idle TTL
        rec.todo_card = bool(eff.get("todo_card", False))   # Display toggle, no rebuild
        rec.name = state.name                                # For the auto-namer
        rec.name_auto = state.name_auto                      # Stop once `/rename` pins
        needs_rebuild = (
            rec.session is None
            or rec.mode != state.mode
            or rec.model != eff["model"]
            or rec.cwd != state.cwd
            or rec.permission_mode != eff["permission_mode"]
            or rec.global_memory != gmem
            or rec.tools_enabled != tkey
            or rec.tool_cap != capkey
            or rec.effort != eff["effort"]
            or rec.max_turns != eff["max_turns"]
            or rec.add_dirs != tuple(state.add_dirs)
            or rec.fork != state.fork_pending
            or rec.auto_compact != eff.get("auto_compact", True)  # Env changes
        )
        if needs_rebuild:
            # Never close or rebuild a client mid-turn.
            # - that disconnects mid-answer and kills the turn
            # - if busy, keep the session; rebuild when next idle
            # - a first-ever build still proceeds
            worker = rec.worker
            busy = worker is not None and not worker.done()
            if busy and rec.session is not None:
                return rec.session
            # Keep a live persistent shell alive across this rebuild.
            # - config drift otherwise killed it via `aclose`
            pending_shell = None
            if rec.session is not None:
                old = rec.session
                rec.session = None
                if getattr(old, "has_live_shell", None) and old.has_live_shell():
                    pending_shell = old.detach_shell()
                with contextlib.suppress(Exception):
                    await old.aclose()
            rec.session = self._build_session(state, eff)
            rec.cli_generation = self._cli_generation  # The CLI binary it spawns
            # Re-attach a shell preserved by rebuild or reaper.
            # - carries the shell across a code to chat switch, deliberately
            # - keeps cd/env and running command for switching back
            # - still reaped on `aclose`, shell TTL or delete
            self._reattach_shell(rec.session, state.thread_id, pending_shell)
            rec.mode = state.mode
            rec.model = eff["model"]
            rec.cwd = state.cwd
            rec.permission_mode = eff["permission_mode"]
            rec.global_memory = gmem
            rec.tools_enabled = tkey
            rec.tool_cap = capkey
            rec.effort = eff["effort"]
            rec.max_turns = eff["max_turns"]
            rec.add_dirs = tuple(state.add_dirs)
            rec.fork = state.fork_pending
            rec.auto_compact = eff.get("auto_compact", True)
            rec.ctx_status = eff.get("ctx_status", True)
            # Restore the persisted `/stream` preference (survives restart).
            rec.stream_enabled = state.stream_enabled
            rec.shell_mode = state.shell_mode  # Re-sync the shell overlay flag
        return rec.session

    # ---- entry ----

    async def handle_text(
        self,
        chat_id: int,
        thread_id: int,
        text: str,
        attachments: list | None = None,
    ) -> int:
        """Queue a prompt and ensure the worker runs.

        - `attachments`: Anthropic content-block dicts sent with the turn
        - Returns `SUBMIT_STARTED` (0) if it runs now
        - Returns waiting count (positive) when queued behind a turn
        - Returns `SUBMIT_QUEUE_FULL` (-1) at the backlog cap
        - Returns `SUBMIT_INJECTED` (-2) when sent into running turn
        """
        # Count it: a push-button press with no message means stop.
        self._inbound_by_chat[chat_id] = self._inbound_by_chat.get(chat_id, 0) + 1
        # Remember the chat for the pinned usage message.
        # - persist only on change, best effort
        if self._main_chat_id != chat_id:
            self._main_chat_id = chat_id
            with contextlib.suppress(Exception):
                await db.set_kv("main_chat_id", str(chat_id))

        default_cwd = self._default_cwd(thread_id)
        state = await db.ensure_thread(
            thread_id, chat_id, self.settings.default_model, default_cwd
        )

        # Resolve the record, take its lock, then re-check liveness.
        # - `reset()` pops the record while holding its lock
        # - a blocked `handle_text` would build on an orphaned record
        # - if popped, retry with the fresh record
        while True:
            rec = self._record(thread_id)
            async with rec.lock:
                if self._records.get(thread_id) is not rec:
                    continue  # `reset()` popped it while waiting; retry
                # Is a turn running? Then this prompt waits behind it.
                # - enforce the backlog cap, report queued depth for the ack
                # - running turn left the queue, so `qsize()` = waiting
                busy = rec.worker is not None and not rec.worker.done()
                # A running turn takes the message itself, like CLI input.
                # - no bot-side queue, no separate turn
                if busy and rec.session is not None and rec.queue.empty():
                    # Keep the inject outcome so the decision is logged.
                    # - log the outcome, never the text
                    injected = False
                    with contextlib.suppress(Exception):
                        injected = await rec.session.inject(text, attachments)
                    if injected:
                        logger.info("thread %s: message handed to the running turn", thread_id)
                        with contextlib.suppress(Exception):
                            await db.log_message(thread_id, "user", text)
                        return SUBMIT_INJECTED
                    # It waits and runs as the next turn.
                    # - the reply already finished (worker still delivering)
                    # - or the client reports no session state
                    logger.info("thread %s: message runs after the current reply (turn active=%s,"
                                " state events=%s)", thread_id,
                                getattr(rec.session, "_turn_active", None),
                                getattr(rec.session, "_states_seen", None))
                if busy and rec.queue.qsize() >= MAX_QUEUED_MESSAGES:
                    return SUBMIT_QUEUE_FULL
                # Idle handling lives in the handler (`_session_key_for_turn`).
                # - a long idle gap starts a new session
                # - the old one is kept
                # - build or refresh the session before enqueueing
                # - so config changes apply to the prompt
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
                # 0 when it runs now (idle worker), else waiting count.
                return rec.queue.qsize() if busy else SUBMIT_STARTED

    # ---- worker ----

    async def _worker(self, thread_id: int, chat_id: int) -> None:
        """Drain the thread's queue serially, streaming each turn.

        - One turn at a time per thread
        - On /stop the worker is cancelled; finally clears handle
        """
        rec = self._record(thread_id)
        send_tid = _send_thread_id(thread_id)
        try:
            while True:
                # Graceful drain: finish the in-flight turn.
                # - start no new queued turns once draining
                if self._draining:
                    break
                try:
                    _qid, prompt, attachments = rec.queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

                interval, step = resolve_speed(self.caret_speed)
                # DM sessions (negative keys) stream via rich message drafts.
                # - General topic and forum topics have no drafts
                # - Telegram caps edits at about 1/sec there
                # - so the write-head path is dormant, frozen supergroup mode only
                # - streaming on/off is the per-session `stream_enabled` flag
                use_drafts = thread_id < 0

                async def _new_streamer(use_drafts=use_drafts, interval=interval,
                                        step=step) -> Streamer:
                    # One per reply: the queued turn's and each follow-up's.
                    # - a new turn resets the warm-cache window
                    # - drop the previous countdown and its message
                    self._cancel_hot_cache(rec, chat_id)
                    # Working-plate note (own limit at 50% or more, owner account).
                    # - only the DM draft path shows the plate
                    working_note = ""
                    if use_drafts:
                        working_note = await self._working_note(
                            chat_id, i18n.cached_lang(chat_id), rec
                        )
                    return Streamer(
                        self.bot,
                        chat_id,
                        send_tid,
                        frame_interval=interval,
                        base_step=step,
                        use_drafts=use_drafts,
                        split_code_messages=self.split_code_messages,
                        working_note=working_note,
                        controllable=self.working_plate,   # Global plate on/off
                    )

                streamer = await _new_streamer()
                rec.streamer = streamer
                try:
                    # Global concurrency admission.
                    # - relieve memory if low, cap simultaneous active turns
                    # - a contended slot tells the user the turn is queued
                    # - per-thread queue still serializes this thread
                    await self._admit_turn(thread_id, chat_id, send_tid)
                    # Fair admission, round-robin by user (`chat_id`).
                    # - paired with the `release()` in the finally below
                    await self._turn_gate.acquire(chat_id)
                    # Track in-flight turns so a graceful drain can wait.
                    self._active_turns += 1
                    self._idle_event.clear()
                    try:
                        await self._run_one(
                            rec, thread_id, prompt, attachments, streamer
                        )
                        # The CLI answered an injected message as its own turn.
                        # - render each follow-up as its own reply
                        # - inside this same admission slot
                        while (getattr(rec.session, "followup_pending", False)
                               and not self._draining):
                            streamer = await _new_streamer()
                            rec.streamer = streamer
                            await self._run_one(rec, thread_id, None, None, streamer)
                    finally:
                        self._active_turns -= 1
                        if self._active_turns <= 0:
                            self._active_turns = 0
                            self._idle_event.set()
                        self._turn_gate.release()
                    # Deliver files the agent staged in `outbox/` this turn.
                    # - outside the turn gate so uploads hold no slot
                    # - inside the per-thread loop, before the next queued turn
                    # - skipped if `_run_one` raised
                    with contextlib.suppress(Exception):
                        await self._deliver_outbox(rec, chat_id, send_tid)
                finally:
                    rec.streamer = None
                    rec.queue.task_done()
        except asyncio.CancelledError:
            # The worker is only cancelled by `reset()`/`aclose()`.
            # - both surface their own message
            # - so tear down silently, with no duplicate stop notice
            raise
        finally:
            # Only release our own handle; a newer worker may exist.
            if rec.worker is asyncio.current_task():
                rec.worker = None

    async def _split_live_blocks(
        self, rec: _ThreadRecord, streamer: Streamer, running_text: str
    ) -> tuple[str, bool]:
        """Commit a closed code fence mid-stream as its own message.

        - Returns `(running_text, flushed)`; text trimmed to remainder
        - `flushed` marks earlier text as already posted
        - Code mode only, when the buffer holds a fence
        """
        if rec.mode != "code":
            return running_text, False
        # Cheap gate: a closed fenced block needs a marker pair.
        # - skip the DOTALL regex scan below 2 markers
        # - avoids O(n^2) rescans of a growing unclosed block
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
        """Run a prompt in the session's persistent jailed shell.

        - Posts the output; no model, no tokens
        - cd and env persist across messages
        - A command awaiting input makes the next message its input
        """
        session = rec.session
        lang = i18n.cached_lang(streamer.chat_id)
        cmd = (prompt or "").strip()
        if session is None or not cmd:
            return
        rec.last_activity = time.monotonic()
        awaiting = rec.shell_awaiting
        # Refuse only full-screen TUIs, which can't render in chat.
        # - line-interactive commands work via the await-input flow
        # - skip the guard while forwarding input
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
                # Forward this message to the program awaiting input.
                # - pure key tokens (`.down .enter`) go as raw key bytes
                # - anything else goes as a text line plus Enter
                keys = _shell_input_keys(cmd)
                if keys is not None:
                    rc, out, status = await session.shell_send_keys(keys)
                else:
                    rc, out, status = await session.shell_send_input(cmd)
            else:
                # Persistent shell; cd/env persist across messages.
                rc, out, status = await session.shell_run(cmd)
                # Auto-capitalized command (phone keyboard) gives 127; retry lowercased.
                if rc == 127:
                    alt = _normalize_shell_cmd(cmd)
                    if alt:
                        rc, out, status = await session.shell_run(alt)
        except Exception:
            # Persistent shell unavailable (spawn or PTY error): use one-shot.
            rec.shell_awaiting = False
            if awaiting:
                # `cmd` was input for a program awaiting it.
                # - the persistent shell died mid-await
                # - one-shot would execute the input as a command
                # - drop it with a notice
                with contextlib.suppress(Exception):
                    await streamer.finish(i18n.t("shell.ended", lang), notify=True)
                return
            try:
                rc, out = await session.run_shell(cmd)
                # Auto-capitalized command (phone keyboard) gives 127; retry lowercased.
                if rc == 127:
                    alt = _normalize_shell_cmd(cmd)
                    if alt:
                        rc, out = await session.run_shell(alt)
            except Exception as exc:  # Shell failure must not kill worker
                rc, out = (-1, f"shell error: {exc}")
        rec.shell_awaiting = (status == "awaiting")  # Next message is forwarded as input
        rendered = self._render_shell(out, rc, status, lang)
        kb = shell_keypad() if rec.shell_awaiting else None  # Inline key keypad
        with contextlib.suppress(Exception):
            await streamer.finish(rendered, notify=True, reply_markup=kb)
        # Remember the live keypad message.
        # - strip on detach, restore on re-attach
        if rec.shell_awaiting:
            rec.shell_kb_chat = streamer.chat_id
            rec.shell_kb_msg = streamer.message_id
            rec.shell_last_render = rendered
        else:
            rec.shell_kb_chat = rec.shell_kb_msg = rec.shell_last_render = None

    @staticmethod
    def _render_shell(out: str, rc, status: str, lang: str) -> str:
        """Render a shell result as monospace block plus hint."""
        body = (out or "").replace("\r\n", "\n").rstrip("\n")
        cap = 60_000  # Output cap (chars) against runaway output
        if len(body) > cap:
            body = body[:cap] + "\n... (truncated)"
        rendered = "```\n" + (body or "(no output)") + "\n```"
        if status == "awaiting":
            rendered += "\n" + i18n.t("shell.awaiting", lang)
        elif status != "timeout" and rc == 127:  # Not found: likely accidental `/shell`
            rendered += "\n" + i18n.t("shell.accidental", lang)
        return rendered

    async def shell_key(self, thread_id: int, key_token: str, lang: str = "en"):
        """Send a keypad press to the persistent shell.

        - Returns `(rendered_output, still_awaiting)` so the caller can edit
        """
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
        prompt: str | None,
        attachments: list | None,
        streamer: Streamer,
    ) -> None:
        """Execute a single prompt turn, optionally with attachments.

        - `prompt=None` renders a CLI-started follow-up turn
        - That turn answers a message injected mid-run
        - Nothing is sent; it was logged when injected
        """
        session = rec.session
        if session is None:
            # Should not happen (`handle_text` builds it); stay safe.
            await self._notify(
                streamer.chat_id,
                streamer.thread_id,
                i18n.t("session.not_initialized", i18n.cached_lang(streamer.chat_id)),
            )
            return

        # Shell-mode overlay: route the message to a jailed command.
        # - code sessions only; no tokens
        if rec.shell_mode and rec.mode == "code" and prompt is not None:  # Not a follow-up
            await self._run_shell_command(rec, thread_id, prompt, streamer)
            return

        # Streaming off: never call `streamer.start()` or `update()`.
        # - no live placeholder, no edits
        # - `finish()` posts the single reply as a fresh message
        stream = rec.stream_enabled

        # Log the user's prompt (feeds `/recap` and `/history`); best-effort.
        # - a follow-up's message was logged when injected
        if prompt is not None:
            with contextlib.suppress(Exception):
                await db.log_message(thread_id, "user", prompt)

        if stream:
            # Experimental, off via `THINKING_MODEL_LINE=0`.
            # - first line of the thinking indicator: model, version, effort
            with contextlib.suppress(Exception):
                streamer.model_line = self._model_line(rec, i18n.cached_lang(streamer.chat_id))
            # Experimental, off by default: the release cycle.
            with contextlib.suppress(Exception):
                streamer.draft_release_secs = draft_release_period(
                    streamer.chat_id, getattr(self.settings, "owner_id", None))
            # The draft's own button, used as push; on by default.
            with contextlib.suppress(Exception):
                streamer.push_button = draft_push_enabled(
                    streamer.chat_id, getattr(self.settings, "owner_id", None))
            await streamer.start()
        running_text = ""
        final_text = ""
        had_result = False
        # Code mode emits text in bursts between tool calls.
        # - commit each burst as its own message (`segment_break`)
        # - `segmented` tells the final flush earlier text is posted
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
                    # `text_full` carries the engine's cumulative turn text.
                    # - after committing segments, `running_text` is only the remainder
                    # - adopting the snapshot would re-flush posted text as a duplicate
                    # - deltas are authoritative; use the snapshot only before segmenting
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
                    # Stream extended thinking into the live thinking draft block.
                    # - cleared once real answer content starts
                    # - DM draft path only; the streamer no-ops it otherwise
                    # - cheap and sync; the draft loop renders next tick
                    if stream:
                        # Think-after-write: reasoning again after answer text, no tool between.
                        # - finalize that text as its own bubble
                        # - open a new one
                        # - re-shows the thinking placeholder so reasoning is visible
                        # - guard fires only on the first delta after text
                        if running_text.strip():
                            with contextlib.suppress(Exception):
                                await streamer.segment_break()
                            running_text = ""
                            segmented = True
                        streamer.add_reasoning(ev.text)
                elif kind == "tool_start":
                    # A tool is starting (e.g. a long server-side WebSearch).
                    # - surface its phase in the thinking block now
                    # - the assembled `tool` event only fires after completion
                    # - phase only: no source, no segment break
                    if stream:
                        with contextlib.suppress(Exception):
                            streamer.set_tool_phase(ev.tool_name, ev.tool_input)
                elif kind == "tool":
                    # Commit pre-tool text as its own message, in both modes.
                    # - the final result excludes pre-tool text
                    # - otherwise the final answer clobbers it in chat
                    # - frees the draft for the search animation
                    # - no-op when there is no pre-tool text
                    if stream and running_text.strip():
                        with contextlib.suppress(Exception):
                            await streamer.segment_break()
                        running_text = ""
                        segmented = True
                    # Show the live tool phase in the thinking block.
                    # - all modes; renders only on the DM draft path
                    if stream:
                        with contextlib.suppress(Exception):
                            # Localized to the user's language (streamer owns the lang).
                            streamer.set_tool_phase(ev.tool_name, ev.tool_input)
                    # Live task-list card from the agent's `TodoWrite` events.
                    # - separate rich message edited in place, off the draft path
                    # - code-only, opt-in
                    if rec.mode == "code" and rec.todo_card and ev.tool_name == "TodoWrite":
                        todos = (ev.tool_input or {}).get("todos") or []
                        with contextlib.suppress(Exception):
                            await streamer.update_todo_card(
                                todos, i18n.cached_lang(streamer.chat_id)
                            )
                    # Web-search Sources card disabled.
                    # - search feedback is the animated thinking tag alone
                    # - the card listed queries mislabelled as sources
                    # - machinery (`add_web_source`, `finalize_sources`) kept for re-enabling
                elif kind == "session":
                    # Persist the session id the moment the engine reports it.
                    # - a turn killed mid-flight still leaves a resumable id
                    # - the session keeps its context
                    if ev.session_id:
                        if rec.mode == "code":
                            with contextlib.suppress(Exception):
                                await db.set_code_session(thread_id, ev.session_id)
                        elif rec.mode == "chat":
                            with contextlib.suppress(Exception):
                                await db.set_chat_session(thread_id, ev.session_id)
                elif kind == "rate_limit":
                    rec.rate = ev.rate
                    # Accumulate per-window account-wide rate state.
                    # - events repeat identical data within a turn
                    # - persist and edit the pin only when the snapshot changed
                    rl_type = getattr(ev.rate, "rate_limit_type", None)
                    # Only the two subscription windows (5h, weekly) are tracked.
                    if rl_type and usage.keep_window(rl_type):
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
                    # A limit-failed turn emits no rate event.
                    # - events keep saying allowed; fabricate a rejected five_hour
                    # - so the display honestly reads limited
                    # - cleared by the next successful turn
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
                    # A successful turn proves the window isn't blocking.
                    # - drop any fabricated limited five_hour
                    # - real rate events repopulate it
                    if self._synth_limit:
                        self._synth_limit = False
                        self.rate_by_type.pop("five_hour", None)
                        self._last_rate_sig = self._rate_signature()
                        with contextlib.suppress(Exception):
                            await self._persist_rate()
                        with contextlib.suppress(Exception):
                            await self.update_pinned()
                    # With segments already posted, only the last burst is new.
                    # - don't reuse `ev.text`; a multi-tool turn repeats segments
                    final_text = running_text if segmented else (ev.text or running_text)
                    # Persist usage and the resumable session id for this mode.
                    # - store the turn's model and last-known context size
                    # - `context_tokens` is informational, from the prior turn
                    # - the units formula bills `cache_read`, which reflects context
                    with contextlib.suppress(Exception):
                        await db.add_usage(
                            thread_id, ev.usage, ev.cost,
                            # Record the concrete model the turn ran on.
                            # - the session stores a family alias the CLI resolves
                            model=(getattr(session, "resolved_model", None)
                                   or models.resolve(getattr(rec, "model", None))),
                            context_tokens=int(getattr(rec, "last_context_tokens", 0) or 0),
                        )
                    # Stamp durable last-activity (wall clock).
                    # - lets the next message detect a long idle gap
                    with contextlib.suppress(Exception):
                        await db.set_last_active(thread_id, time.time())
                    if ev.session_id:
                        if rec.mode == "code":
                            with contextlib.suppress(Exception):
                                await db.set_code_session(thread_id, ev.session_id)
                        elif rec.mode == "chat":
                            # Persist the chat session id every turn, making it durable.
                            # - the next build resumes it across restart or stop
                            with contextlib.suppress(Exception):
                                await db.set_chat_session(thread_id, ev.session_id)
                        # Adopt Claude Code's auto-title as the session label.
                        # - no-op once the user pins one with `/rename`
                        # - only when it changed, to avoid a write every turn
                        if getattr(rec, "name_auto", True):
                            with contextlib.suppress(Exception):
                                # The transcript JSONL grows unbounded; scan it off-loop.
                                # - one pass returns the ai-title and a first-user fallback
                                ai_title, fb_title = await asyncio.to_thread(
                                    _read_session_title, getattr(rec, "cwd", None), ev.session_id
                                )
                                # Prefer the engine's ai-title.
                                # - fall back to the first substantive user message
                                # - covers a trivial or API-errored opening
                                # - keeps the name auto, so a later ai-title supersedes it
                                new_name = ai_title or fb_title
                                # Next tiers: first user message, cut to button width.
                                # - covers a short message too
                                # - with no user text (captionless photo), the first reply's topic
                                if not new_name:
                                    first_words, reply_topic = await asyncio.to_thread(
                                        _read_name_fallbacks, getattr(rec, "cwd", None),
                                        ev.session_id,
                                    )
                                    new_name = (first_words or reply_topic
                                                or _topic_from_reply(final_text))
                                if new_name and new_name != getattr(rec, "name", None):
                                    await db.set_session_name(
                                        thread_id, new_name, manual=False
                                    )
                                    rec.name = new_name
                        # One-shot fork done: the branched id is persisted.
                        # - clear the flag; later turns continue this branch
                        if rec.fork:
                            rec.fork = False
                            with contextlib.suppress(Exception):
                                await db.set_fork_pending(thread_id, False)
        except asyncio.CancelledError:
            # Propagate cancellation so the worker can report the stop.
            # - interrupt the in-flight SDK turn first
            # - tear down the streamer's typing task; `finish()` is skipped here
            with contextlib.suppress(Exception):
                await session.interrupt()
            with contextlib.suppress(Exception):
                streamer.cancel()
            raise
        except Exception as exc:  # Defensive: one turn can't crash worker
            err = i18n.t("session.internal_error", i18n.cached_lang(streamer.chat_id), exc=exc)
            if not final_text and not running_text:
                final_text = err
        finally:
            rec.last_activity = time.monotonic()

        # Final flush; fall back to streamed running text.
        flush_text = final_text if (had_result or final_text) else running_text
        # The account footer is the owner's global usage; owner only.
        # - delegated users get their own `/limits`
        footer = self.usage_footer(i18n.cached_lang(streamer.chat_id), chat_id=streamer.chat_id)
        # Login-expiry heads-up shown above the answer.
        # - never inside the thinking draft; owner-only, about once a day
        # - display-only, not logged to history
        # - compute in the display branch, gated on real text
        # - else a cancelled or empty turn eats the day's throttle
        if segmented and not flush_text.strip():
            # All bursts committed; the turn ended on a tool.
            # - nothing new to post; stop the stream
            # - the empty draft self-expires, no bare ellipsis
            with contextlib.suppress(Exception):
                streamer.cancel()
        else:
            # Compute the heads-up here, only when there is real text.
            # - guard it: a broken creds read can't drop the answer
            # - spend the display throttle only after `finish()` delivers
            # - creds read is throttled inside `_login_expiry_banner`
            _banner = None
            if flush_text.strip():
                with contextlib.suppress(Exception):
                    _banner = self._login_expiry_banner(streamer.chat_id)
            display_text = f"{_banner}\n\n{flush_text}" if _banner else flush_text
            # The final answer pings the user; intermediate segments stay silent.
            with contextlib.suppress(Exception):
                await streamer.finish(display_text, footer=footer, notify=True)
                if _banner:
                    self._login_warn_last = time.time()   # Display throttle spent on delivery
            # Log the assistant's reply (feeds `/recap` and `/history`); best-effort.
            with contextlib.suppress(Exception):
                await db.log_message(thread_id, "assistant", flush_text)
            # Optional warm-cache reminder, ticking down (per-session toggle).
            with contextlib.suppress(Exception):
                await self._maybe_hot_cache_note(thread_id, streamer, rec)
            # Capture context size now for the next turn's working plate.
            # - the turn is done, so the SDK client is idle
            # - this control request is safe
            with contextlib.suppress(Exception):
                tot = _ctx_total(await session.context_usage())
                if tot:
                    rec.last_context_tokens = tot

    # ---- control ----

    async def stop(self, thread_id: int) -> bool:
        """Gracefully interrupt the current turn, keeping session context.

        - Stops generation so no more usage is burned
        - Worker and client stay alive; avoids doubled replies
        - `finish()` flushes text so far, keeping chat and memory aligned
        - Clears the queue and denies any pending permission prompt
        - Returns True if there was something to stop
        """
        rec = self._records.get(thread_id)
        if rec is None:
            return False

        async with rec.lock:
            worker = rec.worker
            running = worker is not None and not worker.done()
            if not running and rec.queue.empty():
                return False

            # Drop queued chained prompts so nothing new runs after stop.
            _drain_queue(rec.queue)

            # Deny any pending permission prompt so a gated turn unblocks.
            # - no leaked Future or stale inline buttons
            # - the gate keys prompts by send thread id
            # - `None` means General
            with contextlib.suppress(Exception):
                await self.gate.cancel_thread(thread_id)

            # Interrupt the in-flight turn (best effort).
            # - the worker finishes gracefully, showing partial text
            # - session and context stay alive for the next message
            if rec.session is not None:
                with contextlib.suppress(Exception):
                    await rec.session.interrupt()
        return True

    async def reset(self, thread_id: int) -> None:
        """Hard reset: cancel run, drop client, clear session.

        - Unlike /stop, context is fully cleared
        - Persisted session id is cleared; mode, model, cwd are kept
        - Next message starts a brand-new session
        """
        rec = self._records.get(thread_id)
        if rec is not None:
            # Hold the lock across teardown and the dict removal.
            # - a concurrent `handle_text()` either precedes it fully
            # - or follows the pop, and `_record()` builds a fresh record
            async with rec.lock:
                # Deny pending permission prompts and clear queued prompts.
                with contextlib.suppress(Exception):
                    await self.gate.cancel_thread(thread_id)
                _drain_queue(rec.queue)

                # Forcefully cancel the worker; reset discards the turn.
                # - cancel rather than interrupt-and-wait
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

        # A hard reset or delete tears the shell down.
        # - unlike the idle reaper, which preserves it
        # - also close any reaper-stashed shell for this thread
        await self._drop_detached_shell(thread_id)
        with contextlib.suppress(Exception):
            await db.reset_thread(thread_id)

    async def on_mode_or_model_or_cwd_change(self, thread_id: int) -> bool:
        """Drop the live client so the next message rebuilds.

        - Called after settings changes persist
        - Idle thread: close the client now
        - Busy thread: do nothing; rebuild happens once idle
        - Returns True when the change was deferred
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
            # Force a rebuild on next `handle_text`: clear the config snapshot.
            rec.mode = None
            rec.model = None
            rec.cwd = None
            rec.permission_mode = None
            rec.big_memory = None
        return False

    # ---- queue / retry ----

    def queue_info(self, thread_id: int) -> dict:
        """Peek at the pending queue without consuming it.

        - Returns count and the first ~3 prompts, ~60 chars each
        - Items list is empty if the deque is inaccessible
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
        """Return pending queue as `[{id, text}]`, oldest first.

        - Empty list when nothing is queued
        """
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
        """Remove one pending prompt by queue id, keeping order.

        - Returns a short preview, or None if not found
        - Runs under `rec.lock` to avoid racing enqueue
        """
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
        """Drop every pending prompt without cancelling the worker.

        - Returns the number discarded
        - Runs under `rec.lock` to avoid racing enqueue
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

        - Returns True if there was a prompt to retry
        - `last_prompt` is snapshotted before any await
        - Deliberate stale-read: retry runs once, never loops
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
        """Toggle live streaming for this thread.

        - Creates the record on a miss so the choice persists
        - Read-only APIs use `_records.get()` instead
        """
        rec = self._record(thread_id)
        rec.stream_enabled = bool(on)
        # Persist so the preference survives a restart.
        with contextlib.suppress(Exception):
            await db.set_stream_enabled(thread_id, on)

    async def set_shell_mode(self, thread_id: int, on: bool) -> None:
        """Toggle the shell-mode overlay for a code session.

        - Updates the live record and persists it
        """
        rec = self._record(thread_id)
        # Toggling shell mode is a detach, like leaving tmux.
        # - the shell and any running command stay alive in background
        # - re-attach keeps cd/env; `shell_awaiting` is preserved
        # - torn down on session delete/evict or the idle reaper
        # - interrupt with ^C; a stuck one is reaped when idle
        rec.shell_mode = bool(on)
        with contextlib.suppress(Exception):
            await db.set_shell_mode(thread_id, on)

    def shell_kb_ref(self, thread_id: int) -> tuple[int, int] | None:
        """Chat and message id bearing the shell keypad, or None.

        - Used by /shell OFF to strip the stale keypad
        """
        rec = self._records.get(thread_id)
        if rec is None or not rec.shell_kb_chat or not rec.shell_kb_msg:
            return None
        return (rec.shell_kb_chat, rec.shell_kb_msg)

    def shell_resume_render(self, thread_id: int) -> str | None:
        """Last awaiting-input render while the shell is paused, else None.

        - Lets /shell ON restore the keypad where it paused
        """
        rec = self._records.get(thread_id)
        if rec is None or not rec.shell_awaiting:
            return None
        return rec.shell_last_render

    async def shell_refresh(self, thread_id: int, lang: str = "en") -> str | None:
        """Surface output printed while the shell was detached.

        - Drains pending output without sending input
        - Returns the live render, or None for stored one
        - Re-renders and stores it when something is new
        """
        rec = self._records.get(thread_id)
        if rec is None:
            return None
        # Hold `rec.lock` across the snapshot read and peek.
        # - a concurrent rebuild can't swap `rec.session` between guard and await
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
        """Point the keypad tracker at a message, or forget it.

        - `None, None` forgets the ref but keeps the paused render
        - That keeps `shell_awaiting` so /shell ON can restore
        - `render` updates the stored body only when given
        """
        rec = self._records.get(thread_id)
        if rec is None:
            return
        rec.shell_kb_chat = chat
        rec.shell_kb_msg = msg
        if render is not None:
            rec.shell_last_render = render

    # ---- usage ----

    async def load_persisted(self) -> None:
        """Restore usage settings and last rate snapshot from DB.

        - Unreadable values fall back to defaults; startup never fails
        """
        # Usage display mode.
        with contextlib.suppress(Exception):
            mode = await db.get_kv("usage_mode")
            if mode in {"off", "footer", "pinned", "both"}:
                self.usage_mode = mode
            else:
                self.usage_mode = "footer"

        # Code-block message-splitting toggle (`/codesplit`).
        # - default on; only an explicit 0 or off disables
        with contextlib.suppress(Exception):
            raw = await db.get_kv("split_code_messages")
            if raw is not None:
                self.split_code_messages = str(raw).lower() not in ("0", "off", "false", "")

        # Working-plate toggle; default on, only explicit 0 or off disables.
        with contextlib.suppress(Exception):
            raw = await db.get_kv("working_plate")
            if raw is not None:
                self.working_plate = str(raw).lower() not in ("0", "off", "false", "")

        # Global idle-to-fresh-session window (seconds).
        # - owner-set in Admin, else the config default; 0 = off
        # - per-user `idle_reset_min` overrides it (see `idle_reset_seconds`)
        with contextlib.suppress(Exception):
            raw = await db.get_kv("idle_reset_sec")
            if raw is not None:
                self._idle_reset = max(0.0, float(int(raw)))
        # CLI auto-update: owner-set daily UTC time (`HH:MM` or off).
        # - falls back to the .env default
        # - plus when it last ran, so a restart doesn't re-run
        with contextlib.suppress(Exception):
            raw = await db.get_kv("cli_update_at")
            if raw is not None:
                self._cli_update_at = parse_update_time(raw)
        with contextlib.suppress(Exception):
            raw = await db.get_kv("cli_update_last")
            if raw:
                self.cli_last_check = float(raw)

        # Main chat id.
        with contextlib.suppress(Exception):
            raw = await db.get_kv("main_chat_id")
            if raw:
                self._main_chat_id = int(raw)

        # Pinned usage message as `chat:msg`.
        with contextlib.suppress(Exception):
            raw = await db.get_kv("pinned_msg")
            if raw and ":" in raw:
                chat_s, msg_s = raw.split(":", 1)
                self._pinned = (int(chat_s), int(msg_s))

        # Rate snapshot: `{type: {status, resets_at, rate_limit_type, util...}}`.
        with contextlib.suppress(Exception):
            raw = await db.get_kv("rate_snapshot")
            if raw:
                data = json.loads(raw)
                rebuilt: dict[str, object] = {}
                for rl_type, entry in data.items():
                    # Drops a stale per-model window saved earlier.
                    if not isinstance(entry, dict) or not usage.keep_window(rl_type):
                        continue
                    rebuilt[str(rl_type)] = SimpleNamespace(
                        status=entry.get("status"),
                        resets_at=entry.get("resets_at"),
                        rate_limit_type=entry.get("rate_limit_type"),
                        utilization=entry.get("utilization"),
                    )
                self.rate_by_type = rebuilt

    async def set_usage_mode(self, mode: str) -> None:
        """Set and persist the usage display mode, refreshing the pin."""
        if mode not in {"off", "footer", "pinned", "both"}:
            raise ValueError(f"invalid usage mode: {mode!r}")
        self.usage_mode = mode
        await db.set_kv("usage_mode", mode)
        if mode in {"pinned", "both"}:
            await self.update_pinned()

    async def set_split_code_messages(self, on: bool) -> None:
        """Set and persist per-code-block message splitting.

        - The /codesplit toggle
        - Takes effect next reply; no restart needed
        """
        self.split_code_messages = bool(on)
        await db.set_kv("split_code_messages", "1" if on else "0")

    async def set_working_plate(self, on: bool) -> None:
        """Set and persist the global Working/Stop plate toggle.

        - Takes effect next turn
        """
        self.working_plate = bool(on)
        await db.set_kv("working_plate", "1" if on else "0")

    async def set_idle_reset_sec(self, sec: int) -> None:
        """Set and persist the global idle-to-fresh-session window.

        - Seconds; 0 means off; owner-set in Admin
        - Takes effect on the next message
        - A per-user `idle_reset_min` still overrides it
        """
        self._idle_reset = max(0.0, float(sec))
        await db.set_kv("idle_reset_sec", str(int(self._idle_reset)))

    # ---- CLI auto-update ----

    @property
    def cli_update_at(self) -> tuple[int, int] | None:
        """Daily CLI-update time in UTC; None means off."""
        return self._cli_update_at

    async def set_cli_update_at(self, hm: tuple[int, int] | None) -> None:
        """Set and persist the daily CLI-update time.

        - UTC; None means off; owner-set in Admin
        - Running loop reads it on next poll; no restart
        """
        self._cli_update_at = hm
        await db.set_kv("cli_update_at", format_update_time(hm))

    def cli_update_due(self, now: float | None = None) -> bool:
        """True once today's update time passed with no round since.

        - Includes a slot missed while the bot was down
        - `cli_last_check` is persisted
        """
        hm = self._cli_update_at
        if hm is None:
            return False
        now = time.time() if now is None else now
        return self.cli_last_check < last_update_slot(now, hm)

    async def update_cli_now(self) -> "cli_update.UpdateResult":
        """Run one CLI update round now.

        - Runs `claude update` and re-stages the jail
        - Serialized with the periodic loop; blocking work in a thread
        - Model catalog refreshes on next client connect
        """
        async with self._cli_update_lock:
            stage_jail = bool(getattr(self.settings, "sandbox_per_session_uid", False))
            res = await asyncio.to_thread(cli_update.update_and_stage, stage_jail)
            self.cli_last_result = res
            self.cli_last_check = time.time()
            with contextlib.suppress(Exception):
                await db.set_kv("cli_update_last", str(self.cli_last_check))
        if not res.ok:
            logger.warning("Claude CLI update failed (%s); still on %s", res.detail,
                           res.after or res.before or "?")
        elif res.changed:
            logger.info("Claude CLI updated %s → %s (jail copy re-staged: %s)",
                        res.before or "?", res.after, res.staged)
        else:
            logger.info("Claude CLI is up to date (%s)%s", res.after or "?",
                        " — jail copy re-staged" if res.staged else "")
        if res.changed or res.staged:
            # A new binary is in place; move every client over.
            # - idle clients now, busy ones on the next reaper sweep
            self._cli_generation += 1
            with contextlib.suppress(Exception):
                await self._recycle_stale_clients()
        return res

    async def _recycle_stale_clients(self) -> int:
        """Close idle clients built before the last CLI update.

        - Next message reconnects on the new binary via resume
        - Conversation and live persistent shell are kept
        - Busy clients are skipped until their reply is done
        - Returns the count
        """
        gen = self._cli_generation
        closed = 0
        for tid in self._live_thread_ids(idle_only=True):
            rec = self._records.get(tid)
            if rec is None or rec.cli_generation >= gen:
                continue
            if await self._evict_session(tid):
                closed += 1
                logger.info("CLI update: recycled the idle client of thread %s onto the new "
                            "binary", tid)
        return closed

    async def probe_models(self) -> bool:
        """Refresh model catalog and default efforts from the host CLI.

        - No prompt, no tokens; result is persisted
        - Serialized with CLI updates
        """
        async with self._cli_update_lock:
            ok = False
            with contextlib.suppress(Exception):
                ok = await models.probe(cli_update.host_cli())
            with contextlib.suppress(Exception):
                await models.flush()
        if not ok:
            logger.warning("model catalog probe failed — menus use the last known catalog")
        return ok

    async def _cli_updater_loop(self) -> None:
        """Probe catalog at startup, then run daily CLI updates.

        - Polls every `_CLI_UPDATE_POLL` seconds for the due time
        - Due state is persisted, so restarts neither repeat nor skip
        - Time is re-read each poll; Admin changes need no restart
        - Re-probes the catalog after each round
        - All errors are swallowed
        """
        first = True
        while True:
            try:
                await asyncio.sleep(_CLI_PROBE_DELAY if first else _CLI_UPDATE_POLL)
            except asyncio.CancelledError:
                break
            if first:
                first = False
                with contextlib.suppress(Exception):
                    await self.probe_models()
                # No `continue`: a round missed during downtime runs immediately.
            with contextlib.suppress(Exception):
                if self.cli_update_due():
                    await self.update_cli_now()
                    await self.probe_models()

    def start_cli_updater(self) -> None:
        """Start the periodic CLI updater; idempotent, called at startup."""
        if self._cli_update_task is None or self._cli_update_task.done():
            self._cli_update_task = asyncio.create_task(self._cli_updater_loop())

    # ---- untitled sessions: name or dispose ----

    def _is_busy(self, thread_id: int) -> bool:
        """True while a turn runs or is queued; never dispose."""
        rec = self._records.get(thread_id)
        if rec is None:
            return False
        running = rec.worker is not None and not rec.worker.done()
        return running or not rec.queue.empty()

    async def dispose_dm_session(self, uid: int, key: int, name: str | None) -> bool:
        """Reset, delete and archive one DM session; True if deleted.

        - Shared with the background untitled sweep
        - Archive keeps the bundle for retention, so it's recoverable
        """
        with contextlib.suppress(Exception):
            await self.reset(key)
        ok = False
        with contextlib.suppress(Exception):
            ok = await db.delete_dm_session(uid, key)
        if ok:
            with contextlib.suppress(Exception):
                archive.archive_session(self.settings.base_workdir, db.session_pubid(key),
                                        owner_id=uid, key=key, name=name)
        return ok

    async def _derive_session_name(self, key: int) -> str | None:
        """Auto-name priority for a stored session, no live turn needed.

        - Order: ai-title, first substantive user message
        - Then first user message as typed, at button width
        - Then topic of first substantial reply, if no user text
        - Falls back to logged messages when transcript is gone
        - None means nothing to name it by
        """
        st = await db.get_thread(key)
        if st is None:
            return None
        order = ((st.code_session_id, st.chat_session_id) if st.mode == "code"
                 else (st.chat_session_id, st.code_session_id))
        sids = [x for x in order if x]
        substantive = first = topic = None
        for sid in sids:
            ai, fb = await asyncio.to_thread(_read_session_title, st.cwd, sid)
            if ai:
                return ai
            substantive = substantive or fb
        if substantive:
            return substantive
        for sid in sids:
            fw, tp = await asyncio.to_thread(_read_name_fallbacks, st.cwd, sid)
            first, topic = first or fw, topic or tp
        if first or topic:
            return first or topic
        msgs = await db.get_recent_messages(key, limit=200)
        user_texts = [m["text"] for m in msgs if m["role"] == "user"]
        for txt in user_texts:
            if _topic_from_text(txt):
                return _topic_from_text(txt)
        for txt in user_texts:
            if _first_words(txt):
                return _first_words(txt)
        for m in msgs:
            if m["role"] == "assistant" and _topic_from_reply(m["text"]):
                return _topic_from_reply(m["text"])
        return None

    async def tidy_untitled(self, uid: int, keep: int) -> tuple[int, int]:
        """Name or dispose every untitled DM session of a user.

        - Skips `keep`, favorites, manually named and busy sessions
        - Never-used sessions are archived
        - Used sessions are named by priority, else archived
        - Returns `(named, disposed)`
        """
        # Every page, not just the 100 most recent.
        # - an old leftover sits far down the list
        # - collected up front, since disposals shift offsets
        page: list = []
        while True:
            chunk, total = await db.browse_threads(uid, None, limit=100, offset=len(page))
            page.extend(chunk)
            if not chunk or len(page) >= total:
                break
        placeholders = i18n.placeholder_session_names()
        cands = [r for r in page
                 if r["thread_id"] != keep and r["thread_id"] < 0
                 and not r.get("favorite") and r.get("name_auto", True)
                 and not self._is_busy(r["thread_id"])]
        if not cands:
            return 0, 0
        stats: dict = {}
        with contextlib.suppress(Exception):
            stats = await db.get_usage_totals_bulk([r["thread_id"] for r in cands])
        named = disposed = 0
        for r in cands:
            tid = r["thread_id"]
            requests = int((stats.get(tid) or {}).get("requests", 0) or 0)
            if requests and (r.get("name") or "").strip() not in placeholders:
                continue  # Used and has a real name
            name = None
            if requests:
                try:
                    name = await self._derive_session_name(tid)
                except Exception:
                    # Fail safe: an unreadable session is left alone, never archived.
                    logger.warning("untitled sweep: could not read session %s", tid,
                                   exc_info=True)
                    continue
            if name:
                with contextlib.suppress(Exception):
                    await db.set_session_name(tid, name, manual=False)
                    rec = self._records.get(tid)
                    if rec is not None:
                        rec.name = name
                    named += 1
            elif await self.dispose_dm_session(uid, tid, r.get("name")):
                disposed += 1
        return named, disposed

    async def sweep_untitled_all(self) -> tuple[int, int]:
        """Run `tidy_untitled` for every DM user, keeping their current session.

        - Returns totals; logs a summary when anything changed
        """
        named = disposed = 0
        for uid in await db.dm_user_ids():
            with contextlib.suppress(Exception):
                keep = await db.get_dm_current(uid) or 0
                n, d = await self.tidy_untitled(uid, keep)
                named += n
                disposed += d
        if named or disposed:
            logger.info("untitled sweep: named %d session(s), archived %d", named, disposed)
        return named, disposed

    async def _untitled_sweeper_loop(self) -> None:
        """Sweep shortly after startup, then daily."""
        delay = _UNTITLED_SWEEP_FIRST
        while True:
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                break
            delay = _UNTITLED_SWEEP_INTERVAL
            with contextlib.suppress(Exception):
                await self.sweep_untitled_all()

    def start_untitled_sweeper(self) -> None:
        """Start the untitled-session sweeper; idempotent, called at startup."""
        if self._untitled_task is None or self._untitled_task.done():
            self._untitled_task = asyncio.create_task(self._untitled_sweeper_loop())

    def _login_expiry_banner(self, chat_id: int) -> str | None:
        """One-line localized warning when the host login nears expiry.

        - Fires within `LOGIN_EXPIRY_WARN_DAYS` of the refresh-token deadline
        - Owner-only, since only they can re-login
        - Throttled to about once a day
        - Returns None when there is nothing to show
        """
        owner_id = getattr(self.settings, "owner_id", None)
        if owner_id is None or chat_id != owner_id:
            return None
        now = time.time()
        # Display throttle: at most one banner per day.
        # - spent by the caller only when a banner shows
        # - checked first; also spares the creds read below
        if now - self._login_warn_last < 20 * 3600:   # About once a day (counts 3-2-1)
            return None
        # Read throttle: don't reopen the creds file every owner turn.
        # - outside the warn window `_login_warn_last` stays 0.0
        # - gate the read on its own once-a-day stamp
        if now - self._login_check_last < 20 * 3600:
            return None
        days = token_refresh.login_warn_days(token_refresh.login_seconds_left())
        if days is None:
            # Spend the read throttle only when nothing is shown.
            # - outside the warn window it limits creds reads to daily
            # - in-window, the display throttle governs the cadence
            # - a failed finish re-offers the heads-up next turn
            self._login_check_last = now
            return None
        # Don't spend `_login_warn_last` here; the caller spends it after delivery.
        return i18n.t("session.login_expiry_warn", i18n.cached_lang(chat_id), days=days)

    def usage_footer(self, lang: str = "en", chat_id: int | None = None) -> str:
        """Footer line appended to a finished reply when enabled.

        - Shown only to the owner: it holds account-wide usage
        - Delegated users get their own limits via /limits
        """
        if self.usage_mode not in {"footer", "both"}:
            return ""
        owner_id = getattr(self.settings, "owner_id", None)
        if owner_id is not None and chat_id is not None and chat_id != owner_id:
            return ""
        # 5h and 7d go on two separate lines.
        return usage.footer_line(self.rate_by_type, lang, sep="\n")

    async def stream_demo(self, chat_id: int, thread_id: int | None = None) -> None:
        """Simulate a streamed sample reply for the /test command.

        - Sample has paragraphs, a wide table, asm, an SVG diagram
        - Lets the owner watch rich-draft formatting build up
        - SVG renders to a PNG photo at finish
        - Drives a standalone Streamer, not a real session
        """
        # `controllable=False`: no mid-stream Stop message.
        # - `finish(notify=False)` makes the persisted message silent
        streamer = Streamer(self.bot, chat_id, thread_id,
                            use_drafts=chat_id > 0, controllable=False)
        await streamer.start()
        sample = _DEMO_SAMPLE
        step = max(8, len(sample) // 40)   # About 40 growth steps
        try:
            for i in range(step, len(sample) + step, step):
                await streamer.update(sample[:i])
                await asyncio.sleep(0.15)
            await streamer.finish(sample, notify=False)
        except Exception:
            with contextlib.suppress(Exception):
                streamer.cancel()

    async def _working_note(self, chat_id: int, lang: str, rec=None) -> str:
        """Extra lines for the Working plate.

        - Owner sees account usage; others see own limit at 50%+
        - Context size shown once big; owner may delegate disabling
        - Cheap and best-effort; empty string on failure
        """
        lines: list[str] = []
        try:
            owner_id = getattr(self.settings, "owner_id", None)
            if owner_id is not None and chat_id == owner_id:
                fl = usage.footer_line(self.rate_by_type, lang, sep="\n")  # Two lines
                if fl:
                    lines.append(fl)
            elif self.allowlist:
                caps = self.allowlist.rate_of(chat_id, None)
                day_cap, week_cap = caps.get("day"), caps.get("week")
                if day_cap or week_cap:
                    bd = await db.get_user_breakdown(chat_id)
                    best = None  # `(fraction, kind_key)`
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
            # Live context size from the previous turn's end.
            # - shown once it crosses the threshold, toggle on (default)
            if rec is not None and getattr(rec, "ctx_status", True):
                ctx = int(getattr(rec, "last_context_tokens", 0) or 0)
                if ctx >= _CTX_STATUS_MIN:
                    lines.append(i18n.t("stream.context", lang, n=f"{ctx / 1000:.0f}k"))
        except Exception:
            return "\n".join(lines)
        return "\n".join(lines)

    async def _maybe_hot_cache_note(self, thread_id: int, streamer, rec=None) -> None:
        """Post a warm-cache reminder after a reply when enabled.

        - Ticks down every minute until the 5-minute window expires
        - The next turn cancels it and resets the window
        - Best-effort throughout
        """
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
        """Tick the warm-cache note down each minute, then mark cold.

        - Cancelled by the next turn; edits are best-effort
        """
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
        """Drop the previous warm-cache countdown and its message.

        - New turn resets the 5-minute window
        - Fire-and-forget delete
        """
        if rec.hot_cache_task is not None:
            rec.hot_cache_task.cancel()
            rec.hot_cache_task = None
        if rec.hot_cache_msg_id is not None:
            mid = rec.hot_cache_msg_id
            rec.hot_cache_msg_id = None
            with contextlib.suppress(Exception):
                asyncio.create_task(self.bot.delete_message(chat_id, mid))

    def _rate_signature(self) -> tuple:
        """Cheap comparable fingerprint of the current rate snapshot.

        - Lets `_run_one` skip redundant DB writes and pin edits
        - Sorted by window key, so event order doesn't matter
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
        """Create or refresh the pinned usage message in General.

        - No-op unless usage_mode includes "pinned" and the chat is known
        - Telegram errors are swallowed; the bot may lack pin rights
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

        # Create a new message in General and pin it.
        # - no thread id; best effort; swallow everything
        # - missing pin rights are normal
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

    # ---- account usage ----

    async def refresh_account_usage(self) -> bool:
        """Refresh `rate_by_type` from the account usage endpoint.

        - Real per-window percent; SDK events only fire near limits
        - Persists and re-renders the pin when changed
        - Returns True if anything changed
        - A fetch failure leaves the prior snapshot untouched
        """
        data = await usage.fetch_account_usage()
        if not data:
            return False
        for key, info in data.items():
            self.rate_by_type[str(key)] = info
        # Also drop any untracked window an older run left behind.
        for key in [k for k in self.rate_by_type if not usage.keep_window(k)]:
            self.rate_by_type.pop(key, None)
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
        """Refresh account usage at startup and every `_USAGE_POLL_INTERVAL`.

        - Keeps footer, pin, status accurate while idle
        - One small GET per cycle; errors swallowed
        """
        while True:
            with contextlib.suppress(Exception):
                await self.refresh_account_usage()
            try:
                await asyncio.sleep(_USAGE_POLL_INTERVAL)
            except asyncio.CancelledError:
                break

    def start_usage_poller(self) -> None:
        """Start the account-usage poller; idempotent, called at startup."""
        if self._usage_task is None or self._usage_task.done():
            self._usage_task = asyncio.create_task(self._usage_poll_loop())

    # ---- concurrency / RAM ----

    @staticmethod
    def _mem_available_mb() -> int:
        """MemAvailable from /proc/meminfo, in MiB.

        - Returns a huge number on error, so it fails open
        """
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        return int(line.split()[1]) // 1024
        except Exception:
            pass
        return 1 << 30

    def _live_thread_ids(self, *, idle_only: bool = False) -> list[int]:
        """Thread ids whose claude client is currently live.

        - `idle_only` drops threads mid-turn; running turns are never evicted
        """
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
        """Close one thread's idle client; the next message resumes.

        - Clears the config snapshot; resumes from the on-disk transcript
        - No-op if busy or no live client
        - Mirrors the idle path of `on_mode_or_model_or_cwd_change` for consistent locking
        """
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
            # Preserve a live jailed shell across the reap.
            # - ~3 MB versus the ~500 MB client being freed
            # - holds the user's cd/env and running command
            # - own longer TTL; re-attached on the next rebuild
            if getattr(old, "has_live_shell", None) and old.has_live_shell():
                sh = old.detach_shell()
                if sh is not None:
                    self._detached_shells[thread_id] = (sh, time.monotonic())
            with contextlib.suppress(Exception):
                await old.aclose()
            # Clear the snapshot so `_get_session` rebuilds on the next message.
            rec.mode = None
            rec.model = None
            rec.cwd = None
            rec.permission_mode = None
            rec.big_memory = None
        return True

    def _reattach_shell(self, session, thread_id: int, pending_shell=None) -> None:
        """Give a fresh session a preserved persistent shell.

        - Source: `pending_shell`, or one the reaper stashed
        - A dead shell is dropped, not adopted
        """
        sh = pending_shell
        entry = self._detached_shells.pop(thread_id, None)
        if sh is None and entry is not None:
            sh = entry[0]
        elif entry is not None:
            # Drift-path shell wins; the stashed one is stale, discard it.
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
        """Best-effort fire-and-forget close of a shell from sync context."""
        with contextlib.suppress(Exception):
            asyncio.create_task(sh.close())

    async def _drop_detached_shell(self, thread_id: int) -> None:
        """Close and forget a reaper-stashed shell.

        - Used on hard reset and session delete
        """
        entry = self._detached_shells.pop(thread_id, None)
        if entry is not None:
            with contextlib.suppress(Exception):
                await entry[0].close()

    async def _reap_detached_shells(self, now: float) -> None:
        """Close reaper-stashed shells past the shell TTL or already dead.

        - A TTL of 0 means keep until session delete
        """
        for tid, (sh, ts) in list(self._detached_shells.items()):
            dead = not getattr(sh, "alive", lambda: False)()
            expired = self._shell_ttl > 0 and (now - ts) >= self._shell_ttl
            if dead or expired:
                self._detached_shells.pop(tid, None)
                with contextlib.suppress(Exception):
                    await sh.close()

    async def _relieve_memory(self, *, exclude: int | None = None, max_evict: int = 8) -> int:
        """Free RAM by evicting idle clients, oldest activity first.

        - Stops once MemAvailable clears the floor or `max_evict` hits
        - Called before a turn grabs more memory
        - Returns the number evicted
        """
        floor = self._min_free_mb
        idle = [
            (self._records[t].last_activity, t)
            for t in self._live_thread_ids(idle_only=True)
            if t != exclude
        ]
        idle.sort()  # Oldest activity first (LRU)
        freed = 0
        for _, tid in idle:
            if freed >= max_evict:
                break
            if await self._evict_session(tid):
                freed += 1
                logger.info("reaper: closed idle client of thread %s (low memory, floor %d MB)",
                            tid, floor)
            if self._mem_available_mb() >= floor:
                break
        return freed

    async def _admit_turn(self, thread_id: int, chat_id: int, send_tid: int | None) -> None:
        """Gate a turn before it runs.

        - Low MemAvailable: evict idle clients to make room
        - All slots taken: tell the user the turn is queued
        """
        if self._mem_available_mb() < self._min_free_mb:
            await self._relieve_memory(exclude=thread_id)
        if self._turn_gate.locked():
            with contextlib.suppress(Exception):
                await self._notify(
                    chat_id, send_tid, i18n.t("busy.queued", i18n.cached_lang(chat_id))
                )

    async def _reap_once(self) -> None:
        """One reaper sweep over idle live clients.

        - Evicts clients idle longer than `idle_ttl_sec`
        - Then trims least-recently-active idle ones to `max_live_clients`
        - Busy threads are never touched
        """
        now = time.monotonic()
        for tid in self._live_thread_ids(idle_only=True):
            rec = self._records.get(tid)
            if rec is None:
                continue
            # Per-user idle TTL resolved onto the record (seconds).
            # - `None` means global default; zero or less = never reap
            # - the RAM cap below still applies, so no OOM risk
            ttl = rec.idle_ttl if rec.idle_ttl is not None else self._idle_ttl
            if ttl > 0 and now - rec.last_activity >= ttl:
                # Log every eviction so idle closures show in the journal.
                if await self._evict_session(tid):
                    logger.info("reaper: closed idle client of thread %s (idle %ds, ttl %ds)",
                                tid, int(now - rec.last_activity), int(ttl))
        # Count all live clients against the cap; evict only idle.
        live_total = len(self._live_thread_ids())
        cap = self._max_live
        if live_total > cap:
            idle = [
                (self._records[t].last_activity, t)
                for t in self._live_thread_ids(idle_only=True)
            ]
            idle.sort()
            for _, tid in idle[: live_total - cap]:
                if await self._evict_session(tid):  # Logged
                    logger.info("reaper: closed idle client of thread %s (live cap %d reached)",
                                tid, cap)
        # Clients on a replaced CLI binary move over once idle.
        if self._cli_generation:
            with contextlib.suppress(Exception):
                await self._recycle_stale_clients()
        # Independently age out persistent shells preserved past the client reap.
        await self._reap_detached_shells(now)
        # Persist the CLI model catalog if a connect refreshed it.
        with contextlib.suppress(Exception):
            await models.flush()

    async def _reaper_loop(self) -> None:
        """Periodic idle-client reaper loop.

        - Sleeps `_REAPER_INTERVAL` between sweeps
        - Errors are swallowed so it never dies
        """
        while True:
            try:
                await asyncio.sleep(_REAPER_INTERVAL)
            except asyncio.CancelledError:
                break
            with contextlib.suppress(Exception):
                await self._reap_once()

    def start_reaper(self) -> None:
        """Start the idle-client reaper; idempotent, called at startup."""
        if self._reaper_task is None or self._reaper_task.done():
            self._reaper_task = asyncio.create_task(self._reaper_loop())

    # ---- schedule runner ----

    async def _fire_schedule(self, row: dict) -> None:
        """Run one due schedule and submit its prompt.

        - Advances `next_run` first so failures can't re-fire in a loop
        - Posts a small notice, then queues via the normal path
        - Errors are stamped, not raised
        """
        from app.core import schedules  # Local import: pure module, avoids cycle
        sid = int(row["id"])
        now = time.time()
        # `last_status` reflects dispatch, not turn outcome.
        # - running once submitted, ok once `handle_text` returns
        # - it only enqueues; a later turn error isn't captured
        # - ok means dispatched, not succeeded
        status = "ok"
        try:
            spec = json.loads(row["spec"])
            nxt = schedules.next_run_after(spec, now)
        except Exception:
            # Corrupt spec: disable it rather than spin; surfaces in `/schedules`.
            await db.set_schedule_enabled(sid, False)
            await db.update_schedule_run(sid, now, now, "bad-spec")
            return
        # Orphan guard: a deleted session must not be resurrected.
        # - `handle_text`/`ensure_thread` would recreate it
        # - disable any legacy orphan
        if await db.get_thread(int(row["thread_id"])) is None:
            await db.set_schedule_enabled(sid, False)
            await db.update_schedule_run(sid, now, now, "orphaned")
            return
        # Re-check the owner is still allowlisted.
        # - a schedule must not fire after owner removal or expiry
        owner_uid = int(row["owner_uid"]) if row.get("owner_uid") is not None else 0
        if self.allowlist and not self.allowlist.is_allowed(owner_uid, None):
            await db.set_schedule_enabled(sid, False)
            await db.update_schedule_run(sid, now, now, "revoked")
            return
        # Memory gate: host has no swap, fires spawn jails.
        # - below the `MemAvailable` floor, evict idle clients
        # - if still tight, defer and leave `next_run` untouched
        # - the next ~30s sweep retries; silent, no run notice
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
        """Fire due recurring schedules every `_SCHEDULE_INTERVAL`.

        - Rows fire sequentially so bursts can't spawn many turns
        - Errors are swallowed so the loop never dies
        """
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
        """Start the recurring-schedule runner; idempotent, called at startup."""
        if self._schedule_task is None or self._schedule_task.done():
            self._schedule_task = asyncio.create_task(self._schedule_loop())

    # ---- archive retention ----

    async def _resolve_archive_retention_days(self) -> int:
        """Effective archive-retention period in days.

        - Owner's runtime kv `archive_retention_days` wins
        - Else the startup default `settings.archive_retention_days`
        - 0 means keep forever
        """
        raw = await db.get_kv("archive_retention_days")
        if raw is not None:
            try:
                return max(0, int(raw))
            except (TypeError, ValueError):
                pass
        return max(0, int(getattr(self.settings, "archive_retention_days", 180) or 0))

    async def _archive_purge_loop(self) -> None:
        """Periodically delete archive bundles older than the retention.

        - Runs once at startup, then every `_ARCHIVE_PURGE_INTERVAL`
        - Purge runs in a thread; errors are swallowed
        """
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
        """Start the archive-retention purger; idempotent, called at startup."""
        if self._archive_purge_task is None or self._archive_purge_task.done():
            self._archive_purge_task = asyncio.create_task(self._archive_purge_loop())

    # ---- OAuth token refresh ----

    def start_token_refresher(self) -> None:
        """Start the proactive OAuth token refresher; idempotent.

        - Keeps the on-disk token fresh so idle gaps never 401
        - Fail-soft; disable with `OAUTH_REFRESH=0` in .env
        """
        if os.environ.get("OAUTH_REFRESH", "1").strip() in ("0", "false", "off", "no"):
            return
        if self._token_refresh_task is None or self._token_refresh_task.done():
            self._token_refresh_task = asyncio.create_task(
                token_refresh.refresh_loop(on_alert=self._token_refresh_alert))

    async def _token_refresh_alert(self, status: str, fails: int) -> None:
        """DM the owner when the host OAuth login stops refreshing.

        - Also notifies again on recovery
        - Owner-only, since only they can re-login
        - Fail-soft: a Telegram hiccup must not kill the loop
        """
        owner_id = getattr(self.settings, "owner_id", None)
        if owner_id is None:
            return
        lang = i18n.cached_lang(owner_id)
        key = ("session.login_refresh_recovered" if status.startswith("ok")
               else "session.login_refresh_failed")
        await self._notify(owner_id, None, i18n.t(key, lang, status=status, fails=fails))

    # ---- status ----

    def status(self, thread_id: int) -> dict:
        """Snapshot for /status without touching the DB.

        - `cache_seconds_left`: remaining prompt-cache warm window
        - `busy`: a turn is running
        - `queued`: number of pending prompts
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

    # ---- helpers ----

    async def _deliver_outbox(
        self, rec: "_ThreadRecord", chat_id: int, send_tid: int | None
    ) -> None:
        """Deliver files the agent staged in `outbox/` after a turn.

        - Images go as photos, others as documents; copies deleted
        - Per-file size caps and a per-turn count cap
        - Too-big files are dropped with one aggregated note
        - A send failure leaves the file for the next drain
        """
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
        # Bound work and noise to the count cap.
        # - the rest stays in `outbox/` for after the next turn
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
                    path.unlink()          # A staging copy we can't deliver
                continue
            try:
                # A staged file can be multi-MB; read it off-loop.
                # - the empty-outbox common case stays cheap
                data = await asyncio.to_thread(path.read_bytes)
            except OSError:
                continue
            if not is_img:
                # A `.md`/`.txt` in `outbox/` ships verbatim.
                # - add a UTF-8 BOM if absent, for mobile viewers
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
                continue                   # Transient failure: retry next turn
            with contextlib.suppress(OSError):
                path.unlink()              # Delivered: drop the staging copy
        if too_big:
            await self._notify(
                chat_id, send_tid,
                i18n.t("outbox.too_big", lang, names=", ".join(too_big)),
            )
        # Past the per-turn cap or a failed send, rest stays.
        # - it goes out after the next turn; tell the user
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
        """Graceful-shutdown step: stop new turns and drain in-flight ones.

        - Workers stop pulling queued turns; running ones complete
        - Bounded by `timeout`; returns True if fully drained
        - Needs `KillMode=mixed` so SIGTERM reaches only the bot
        - Not-yet-started queued turns are dropped; user re-sends
        - Idempotent
        """
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
        """Best-effort shutdown: cancel workers and disconnect clients.

        - Hard cancel since the process is exiting
        - DB untouched, so code topics keep session id and resume
        """
        # Stop the account-usage poller first.
        if self._usage_task is not None and not self._usage_task.done():
            self._usage_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._usage_task
        # Stop the idle-client reaper too.
        if self._reaper_task is not None and not self._reaper_task.done():
            self._reaper_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reaper_task
        # Stop the archive-retention purger too.
        if self._archive_purge_task is not None and not self._archive_purge_task.done():
            self._archive_purge_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._archive_purge_task
        # Stop the schedule runner too.
        if self._schedule_task is not None and not self._schedule_task.done():
            self._schedule_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._schedule_task
        # Stop the OAuth token refresher too.
        if self._token_refresh_task is not None and not self._token_refresh_task.done():
            self._token_refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._token_refresh_task
        # Stop the CLI updater and the untitled-session sweeper too.
        for task in (self._cli_update_task, self._untitled_task):
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        # Persist a model catalog captured since the last reaper flush.
        with contextlib.suppress(Exception):
            await models.flush()
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
        # Close any persistent shells preserved across a reap.
        for tid in list(self._detached_shells.keys()):
            entry = self._detached_shells.pop(tid, None)
            if entry is not None:
                with contextlib.suppress(Exception):
                    await entry[0].close()
        self._records.clear()


# ---- utils ----


def _attachment_icon(attachments) -> str:
    """Small icon for a queued turn's attachments (empty if none)."""
    if not attachments:
        return ""
    types = {a.get("type") for a in attachments if isinstance(a, dict)}
    if "image" in types:
        return "🖼"
    if "document" in types:
        return "📄"
    return "📎"


def _unpack_queue_item(item) -> tuple:
    """Normalize a queue item to `(qid, text, attachments)`.

    - Tolerates a legacy `(text, atts)` pair or bare string
    """
    if isinstance(item, tuple):
        if len(item) >= 3:
            return item[0], item[1], item[2]
        if len(item) == 2:
            return None, item[0], item[1]
        return None, item[0] if item else "", None
    return None, item, None


def _drain_queue(queue: asyncio.Queue) -> None:
    """Discard all pending items after a worker is cancelled."""
    while True:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        else:
            queue.task_done()


