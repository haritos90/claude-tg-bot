"""Live-updating Telegram message streamed for one model turn.

- Final flush splits long output into chunks or .md
- Every Telegram call is wrapped; errors never crash
- Tool-status lines appear above the streamed text
- Edits cap near one per second
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from typing import Any

from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
)

from app import i18n
from app.telegram import markup
from app.telegram import table_image  # wide tables rendered as PNG
from app.telegram import svg_image  # chat svg diagrams rasterized via cairosvg
from app.telegram.rich_message import EditRichMessage, SendRichMessage, SendRichMessageDraft

logger = logging.getLogger("streamer")

# Keep links inline; never expand into previews.
# - Passed to every text send and edit
_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)

# Caret animation retired; Telegram drafts own the typewriter.
# - Only the reveal-pacing presets below survive

# Speed presets: (frame_interval seconds, base_step chars).
# - Edits cap near one per second; faster trips 429
# - normal targets about 16 chars/sec
CARET_SPEEDS: dict[str, tuple[float, int]] = {
    "calm":   (1.0, 8),
    "normal": (0.85, 14),
    "fast":   (0.7, 26),
}
_DEFAULT_SPEED = "normal"

# Clear a reveal backlog within about this many frames.
_CATCHUP = 5

# ---- native drafts ----
# - Private chats only; supergroups reject with TEXTDRAFT_PEER_INVALID
# - Drafts are not throttled like edits to 1/sec
# - Draft is an ephemeral preview; finish() sends the real message
# - draft_id must be non-zero; reusing it animates in place
_DRAFT_ID_SEQ = 0


def _next_draft_id() -> int:
    """Unique non-zero draft id per Streamer.

    - Process-monotonic; wraps within int32, skips 0
    - Keeps a turn from animating a prior draft
    """
    global _DRAFT_ID_SEQ
    _DRAFT_ID_SEQ = (_DRAFT_ID_SEQ + 1) % 2_000_000_000
    return _DRAFT_ID_SEQ + 1
# Sustainable draft cadence, about 5 per second.
# - Sustained sends under 110ms trip a 3s RetryAfter
# - Short bursts up to 25/sec pass
_DRAFT_INTERVAL = 0.2
# Re-send an unchanged draft after this many seconds.
# - Drafts expire; iOS drops them about 20s after last update
# - 12s leaves room for network latency
_DRAFT_KEEPALIVE_SECS = 12.0
# Rich message limit: at most 50 media attachments.
_RICH_MEDIA_MAX = 50
# Optional console cursor at the typing frontier; default off.
# - Telegram's draft animation absorbs a trailing glyph
# - Set a steady block like ▌ to enable
_DRAFT_CURSOR = ""
# Draft-only thinking placeholder using the thinking tag.
# - Shown until first real content replaces it
# - Never appears in the final rich message
# - Thinking words rotate so the placeholder animates
# - Each word shown for _THINKING_ROTATE_SECS
_THINKING_ROTATE_SECS = 4.0

# Custom animated emoji for the thinking indicator.
# - Bot may send them only if owner has Premium
# - Needs a Premium owner and a configured id
# - Otherwise the unicode fallback is shown
# - Ids come from THINKING_EMOJI_IDS; empty means unicode
_OWNER_PREMIUM: bool = False
_CUSTOM_EMOJI_IDS: dict[str, str] = {}


def set_owner_premium(value: bool) -> None:
    """Record whether the bot owner has Telegram Premium.

    - Gates custom-emoji substitution
    """
    global _OWNER_PREMIUM
    _OWNER_PREMIUM = bool(value)


def configure_custom_emoji(raw: str | None) -> None:
    """Set the icon-to-custom-emoji map from a string.

    - Format: role:id pairs; roles think, search
    - Empty or unparseable disables custom emoji
    """
    global _CUSTOM_EMOJI_IDS
    out: dict[str, str] = {}
    for part in (raw or "").split(","):
        if ":" in part:
            role, cid = part.split(":", 1)
            role, cid = role.strip(), cid.strip()
            if role and cid:
                out[role] = cid
    _CUSTOM_EMOJI_IDS = out


# Read configured ids at import; owner premium is live.
configure_custom_emoji(os.environ.get("THINKING_EMOJI_IDS", ""))

# Draft table streaming mode; default is row-by-row.
# - DRAFT_HOLD_OPEN_TABLES=1 holds tables until complete
# - Works around iOS never drawing rows added later
_HOLD_OPEN_TABLES = os.environ.get("DRAFT_HOLD_OPEN_TABLES", "").strip().lower() in (
    "1", "true", "yes", "on")


def _thinking_placeholder_html(lang: str = "en") -> str:
    """Static thinking placeholder in the user's language."""
    return f"<tg-thinking>{i18n.t('stream.thinking', lang)}…</tg-thinking>"


# Experimental first line of the indicator names model and effort.
# - Second line follows via br; bare newline collapses
# - THINKING_MODEL_LINE=0 turns it off
_THINKING_MODEL_LINE = os.environ.get("THINKING_MODEL_LINE", "1").strip().lower() not in (
    "0", "false", "no", "off")

# Experimental: release held user messages during draft streaming.
# - Telegram delivers them once a real message lands
# - Cycle runs only during thinking-only phases
# - DRAFT_RELEASE values: owner, all, off
# - Default off: placeholders notified the user
_DRAFT_RELEASE_SCOPE = os.environ.get("DRAFT_RELEASE", "off").strip().lower()
# Period of 3 seconds; one cycle takes about 1.3s.
try:
    _DRAFT_RELEASE_SECS = max(0.0, float(os.environ.get("DRAFT_RELEASE_SECS", "3")))
except ValueError:
    _DRAFT_RELEASE_SECS = 3.0
# How long the placeholder stays before deletion.
_DRAFT_RELEASE_HOLD_SECS = 1.0


def draft_release_period(chat_id: int, owner_id: int | None) -> float:
    """Thinking-phase release-cycle period in seconds; 0 disables."""
    if _DRAFT_RELEASE_SCOPE in ("", "0", "off", "no", "false") or _DRAFT_RELEASE_SECS <= 0:
        return 0.0
    if _DRAFT_RELEASE_SCOPE != "all" and chat_id != owner_id:
        return 0.0
    return _DRAFT_RELEASE_SECS


# Experimental: the draft's own button used as push.
# - Pressing it ends the draft, releasing held messages
# - Bot continues in a new draft id
# - Button look is drawn by Telegram
# - DRAFT_PUSH values: all (default), owner, off
_DRAFT_PUSH_SCOPE = os.environ.get("DRAFT_PUSH", "all").strip().lower()


def draft_push_enabled(chat_id: int, owner_id: int | None) -> bool:
    """Whether this chat's drafts carry the push button."""
    if _DRAFT_PUSH_SCOPE in ("", "0", "off", "no", "false"):
        return False
    return _DRAFT_PUSH_SCOPE == "all" or chat_id == owner_id
# Extended-thinking text shown in the thinking block.
# - Keep only the tail, a compact live indicator
# - Retain slightly more than shown for smooth animation
_REASONING_MAX = 4000        # cap retained reasoning text
_REASONING_DRAFT_TAIL = 600  # tail length shown in block


def _thinking_label(elapsed: float, lang: str = "en", searching: bool = False) -> str:
    """Pick a localized thinking word by elapsed time.

    - Generic words, or search-themed words while searching
    - Changing text keeps the thinking tag animating
    """
    key = "stream.searching_words" if searching else "stream.thinking_words"
    words = [w for w in i18n.t(key, lang).split(",") if w]
    if not words:
        words = ["Searching"] if searching else ["Thinking"]
    return words[int(elapsed // _THINKING_ROTATE_SECS) % len(words)]


# Map a tool call to a short live phase.
# - Leading unicode emoji renders everywhere
# - Verb is localized; caller HTML-escapes the label
_TOOL_PHASES = {
    "Read": ("📖", "stream.verb_reading"), "Write": ("✏️", "stream.verb_writing"),
    "Edit": ("✏️", "stream.verb_editing"), "MultiEdit": ("✏️", "stream.verb_editing"),
    "NotebookEdit": ("✏️", "stream.verb_editing"),
    "Grep": ("🔍", "stream.verb_searching_code"), "Glob": ("🔍", "stream.verb_finding_files"),
    "LS": ("📂", "stream.verb_listing"), "WebSearch": ("🌐", "stream.verb_web_search"),
    "WebFetch": ("🌐", "stream.verb_web_fetch"), "TodoWrite": ("🧠", "stream.verb_planning"),
}


def tool_phase_label(tool_name: str, tool_input: dict | None, lang: str = "en") -> str:
    """Short localized phase label for a tool call.

    - Plain text, HTML-escaped before send
    - Emoji is fixed; the verb is localized
    """
    inp = tool_input or {}
    if tool_name == "Bash":
        cmd = (inp.get("command") or "").strip().splitlines()[0:1]
        cmd = cmd[0] if cmd else ""
        if len(cmd) > 40:
            cmd = cmd[:39] + "…"
        run = i18n.t("stream.verb_running", lang)
        return f"⚙️ {run} {cmd}…" if cmd else f"⚙️ {i18n.t('stream.phase_running_any', lang)}…"
    if tool_name in ("Read", "Write", "Edit", "MultiEdit", "NotebookEdit"):
        fp = inp.get("file_path") or inp.get("notebook_path") or ""
        base = fp.rsplit("/", 1)[-1]
        emoji, vkey = _TOOL_PHASES[tool_name]
        verb = i18n.t(vkey, lang)
        return f"{emoji} {verb} {base}…" if base else f"{emoji} {verb}…"
    if tool_name in _TOOL_PHASES:
        emoji, vkey = _TOOL_PHASES[tool_name]
        return f"{emoji} {i18n.t(vkey, lang)}…"
    if tool_name:
        return f"⚙️ {i18n.t('stream.verb_running', lang)} {tool_name}…"
    return f"💭 {i18n.t('stream.thinking', lang)}…"


def sources_card_markdown(sources: list, lang: str = "en", done: bool = False) -> str:
    """Render the live web-research card body.

    - sources: (kind, value) pairs; kind search or fetch
    - done switches the header from Searching to Sources
    - Header is its own block; each item a list row
    - Values are inline code; fetch URLs are trimmed
    - Pure; the streamer sends the rendered body
    """
    header = i18n.t("stream.sources_title" if done else "stream.searching", lang)
    items = []
    for kind, value in sources:
        v = (value or "").replace("`", "").strip()
        if kind == "fetch":
            for pre in ("https://", "http://"):
                if v.startswith(pre):
                    v = v[len(pre):]
                    break
            v = v.rstrip("/")
        if len(v) > 70:
            v = v[:69] + "…"
        glyph = "🔍" if kind == "search" else "🔗"
        items.append(f"- {glyph} `{v}`")
    return header + "\n\n" + "\n".join(items) if items else header


# Drafts can't carry inline buttons, so Stop is separate.
# - Posted only after the turn runs a while
# - Removed when the turn ends
_CONTROL_DELAY = 3.0

# Stop control is a static label plus button.


def resolve_speed(name: str | None) -> tuple[float, int]:
    """Return (frame_interval, base_step) for a speed preset."""
    return CARET_SPEEDS.get(name or "", CARET_SPEEDS[_DEFAULT_SPEED])


class Streamer:
    """One self-editing Telegram message for a streamed turn.

    - thread_id None or 0 means the General topic
    - General topic is sent without message_thread_id
    """

    def __init__(
        self,
        bot: Any,
        chat_id: int,
        thread_id: int | None,
        frame_interval: float | None = None,
        base_step: int | None = None,
        use_drafts: bool = False,
        split_code_messages: bool = True,
        working_note: str = "",
        controllable: bool = True,
    ) -> None:
        self.bot = bot
        self.chat_id = chat_id
        # Whether to post the separate Stop control mid-stream.
        # - A new message mid-draft makes some clients re-render
        # - The /test demo turns this off
        self.controllable = bool(controllable)
        # Extra line under Working in the Stop plate.
        # - User's own limit (50%+), or owner account usage
        self.working_note = working_note or ""
        # Normalise the General topic (0) to None.
        self.thread_id = thread_id if thread_id else None
        d_interval, d_step = CARET_SPEEDS[_DEFAULT_SPEED]
        self.frame_interval = frame_interval or d_interval
        self.base_step = base_step or d_step
        # Native drafts need a private chat (chat_id > 0).
        # - start() probes once, falls back to write-head
        self.use_drafts = bool(use_drafts) and chat_id > 0
        # Message id of the live task-list card.
        # - Separate bubble edited in place; None until first TodoWrite
        self._todo_msg_id: int | None = None
        # Experimental live Sources card, a separate bubble.
        # - Lists web fetch URLs and search queries
        # - Edited in place; persists across segment breaks
        # - None until the first web tool
        self._sources_msg_id: int | None = None
        self._web_sources: list[tuple[str, str]] = []
        self._web_sources_seen: set[tuple[str, str]] = set()
        # Accumulated extended-thinking text, shown as a tail.
        # - Cleared once real answer content starts
        self._reasoning: str = ""
        # Whether finish() isolates each code block into a message.
        # - Default on for easy copying; toggled via /codesplit
        # - Off keeps code inline in the reply
        self._split_code_messages = bool(split_code_messages)
        # Drafts stream at a fixed, flood-safe cadence.
        # - Telegram animates newly appended characters between updates
        self._draft_interval = _DRAFT_INTERVAL
        # Unique draft id for this turn.
        # - Flood backoff deadline: skip draft frames until it passes
        # - Set on RetryAfter
        self._draft_id = _next_draft_id()
        self._draft_retry_after: float = 0.0
        # Current live phase shown in the thinking block.
        # - Set from tool events; None rotates a gerund
        self._phase: str | None = None
        # True while a web search or fetch is in flight.
        # - Placeholder then rotates search-themed gerunds
        self._searching: bool = False
        # Set when custom emoji fails; use plain unicode afterwards.
        # - Prevents a rejected emoji blanking the thinking tag
        self._custom_emoji_failed: bool = False
        # Plain-text model line of the thinking indicator.
        # - Set by the session worker before start()
        self.model_line: str = ""
        # Release-cycle period (0 off), last run, undeleted placeholder.
        self.draft_release_secs: float = 0.0
        self._last_release: float = 0.0
        self._release_msg_id: int | None = None
        # Whether drafts carry the push button.
        self.push_button: bool = False

        self.message_id: int | None = None
        self._start_time: float = 0.0
        self._last_edit: float = 0.0

        # Typewriter state: _full is the buffer, _shown the write-head.
        # - Frame loop advances _shown toward len(_full)
        self._full: str = ""
        self._shown: int = 0
        self._rendered_text: str = ""       # currently shown text, for dedupe
        # Memoize per-frame wide-table substitution by body.
        # - Unchanged body skips re-parsing table structure
        # - Tuple: (cache_key_body, substituted_body)
        self._wide_cache: tuple[str, str] | None = None

        # Whether a turn is actively streaming.
        self._streaming = False

        self._lock = asyncio.Lock()
        self._typing_task: asyncio.Task | None = None
        # Drives the reveal for the whole turn.
        self._anim_task: asyncio.Task | None = None
        # Stop control message id and its delayed poster.
        self._control_id: int | None = None
        self._control_task: asyncio.Task | None = None
        self._closed = False

    # ---- utils ----

    def _kwargs(self) -> dict[str, Any]:
        """Common send kwargs; include message_thread_id only for real topics."""
        if self.thread_id is not None:
            return {"message_thread_id": self.thread_id}
        return {}

    def _render_chunks(self, body: str) -> list[str]:
        """Produce independently balanced HTML chunks for the model text.

        - Split raw text first, then render each chunk
        - Rendering first could cut inside an HTML tag
        """
        body = body.strip()
        if not body:
            return ["…"]
        rendered: list[str] = []
        for raw in markup.split_markdown(body, limit=markup.SAFE_LIMIT):
            # render_within_limit keeps each piece under Telegram's 4096 cap.
            # - HTML escaping can expand a raw chunk
            for html in markup.render_within_limit(raw):
                # Drop a lone fence that renders to blank pre.
                # - A hard cut in a long single-line fence causes it
                if markup.is_empty_render(html):
                    continue
                rendered.append(html)
        return rendered or ["…"]

    def _render_message_chunks(self, body: str) -> list[str]:
        """Like _render_chunks, but isolates each fenced code block.

        - Keeps snippets copyable via long-press
        - Oversized segments are still size-split
        """
        body = body.strip()
        if not body:
            return ["…"]
        out: list[str] = []
        for seg in markup.segment_blocks(body):
            for raw in markup.split_markdown(seg, limit=markup.SAFE_LIMIT):
                # Ensure every rendered chunk fits the 4096 limit.
                # - Raw sizing plus escaping can otherwise overflow
                for html in markup.render_within_limit(raw):
                    # Drop a lone fence rendering to an empty pre box.
                    # - Hard-cutting an over-long fenced line causes it
                    if markup.is_empty_render(html):
                        continue
                    out.append(html)
        return out or ["…"]

    async def _safe(self, coro_factory) -> Any:
        """Run a Telegram coroutine, swallowing transient errors.

        - RetryAfter: honour the delay and retry once
        - Any further failure is swallowed
        """
        try:
            return await coro_factory()
        except TelegramRetryAfter as exc:
            delay = getattr(exc, "retry_after", 1) or 1
            with contextlib.suppress(Exception):
                await asyncio.sleep(float(delay))
            try:
                return await coro_factory()
            except Exception:
                return None
        except TelegramBadRequest:
            # Benign errors: message not modified, edit target not found.
            return None
        except Exception:
            # Transient network errors must not crash the turn.
            return None

    # ---- typing ----

    async def _send_typing(self) -> None:
        await self._safe(
            lambda: self.bot.send_chat_action(
                chat_id=self.chat_id, action="typing", **self._kwargs()
            )
        )

    async def _typing_loop(self) -> None:
        """Re-send the typing action periodically until cancelled."""
        try:
            while not self._closed:
                await self._send_typing()
                # Telegram keeps the typing indicator about 5 seconds.
                await asyncio.sleep(4.0)
        except asyncio.CancelledError:
            return
        except Exception:
            return

    def _stop_typing(self) -> None:
        if self._typing_task is not None:
            self._typing_task.cancel()
            self._typing_task = None

    # ---- animation ----

    async def _animate_loop(self) -> None:
        """Frame loop that drives the live stream.

        - update() only fills the buffer; this loop sends
        - Rechecks finalize flags under the lock
        """
        interval = self._draft_interval if self.use_drafts else self.frame_interval
        try:
            while True:
                await asyncio.sleep(interval)
                if self._closed or not self._streaming:
                    return
                async with self._lock:
                    if self._closed or not self._streaming:
                        return
                    await self._tick()
        except asyncio.CancelledError:
            return
        except Exception:
            return

    async def _tick(self) -> None:
        """One frame: advance the reveal, then repaint."""
        if self.use_drafts:
            # Push the whole frontier; Telegram animates the typewriter.
            self._shown = len(self._full)
            await self._render_draft()
            return
        target = len(self._full)
        if self._shown < target:
            remaining = target - self._shown
            # Reveal at least _BASE_STEP chars per frame.
            # - More when a backlog builds
            step = max(self.base_step, -(-remaining // _CATCHUP))  # ceiling division
            self._shown = min(target, self._shown + step)
        await self._render_frame()

    def _emoji(self, uni: str, role: str) -> str:
        """Custom emoji for a role when available, else unicode.

        - Needs Premium owner, configured id, no failure this turn
        - Unicode is the fallback everyone sees
        """
        if self._custom_emoji_failed or not _OWNER_PREMIUM:
            return uni
        cid = _CUSTOM_EMOJI_IDS.get(role)
        return f'<tg-emoji emoji-id="{cid}">{uni}</tg-emoji>' if cid else uni

    def set_phase(self, label: str | None) -> None:
        """Set the live phase shown in the thinking placeholder.

        - Cheap and synchronous; cleared once content streams
        """
        self._phase = label or None

    def set_tool_phase(self, tool_name: str, tool_input: dict | None) -> None:
        """Set the live tool phase in the chat's language.

        - Web search or fetch enables searching mode
        - Other tools store a fixed file or command label
        """
        if tool_name in ("WebSearch", "WebFetch"):
            self._searching = True
            self._phase = None
        else:
            self._searching = False
            self._phase = tool_phase_label(tool_name, tool_input, i18n.cached_lang(self.chat_id))

    def add_reasoning(self, delta: str) -> None:
        """Append extended-thinking text for the thinking draft block.

        - Tail shown until answer content starts
        - Resuming reasoning drops any stale tool phase
        """
        if not delta:
            return
        self._reasoning = (self._reasoning + delta)[-_REASONING_MAX:]
        self._phase = None
        self._searching = False  # reasoning resumed; leave search mode

    def _thinking_html(self, inner: str) -> str:
        """Wrap indicator HTML in thinking tag, with model line.

        - Model line shown when set and enabled
        """
        if _THINKING_MODEL_LINE and self.model_line:
            return (f"<tg-thinking>{markup.escape_html(self.model_line)}<br>{inner}"
                    "</tg-thinking>")
        return f"<tg-thinking>{inner}</tg-thinking>"

    def _draft_extra(self) -> dict[str, Any]:
        """Extra draft fields: the push button when enabled."""
        return {"can_stop": True} if self.push_button else {}

    def on_push(self, draft_id: int) -> bool:
        """Handle the user pressing the draft's button.

        - Client ended the draft; continue under a new id
        - Returns True when it was this draft
        """
        if not self.use_drafts or self._closed or draft_id != self._draft_id:
            return False
        self._draft_id = _next_draft_id()
        self._rendered_text = ""   # force next frame to re-send
        self._last_edit = 0.0
        logger.info("chat %s: draft push (draft %s → %s)", self.chat_id, draft_id, self._draft_id)
        return True

    async def _release_held_messages(self, html: str) -> bool:
        """Release held user messages via a silent placeholder cycle.

        - Lands tiny message, deletes it, restores indicator
        - Caller holds the lock
        - Returns True when the cycle ran
        """
        self._last_release = time.monotonic()
        lang = i18n.cached_lang(self.chat_id)
        # Plain text mimicking the indicator keeps the swap quiet.
        text = f"💭 {i18n.t('stream.thinking', lang)}…"
        if _THINKING_MODEL_LINE and self.model_line:
            text = f"{self.model_line}\n{text}"
        try:
            msg = await self.bot.send_message(
                chat_id=self.chat_id, text=text,
                disable_notification=True, link_preview_options=_NO_PREVIEW, **self._kwargs())
        except Exception:
            return False
        self._release_msg_id = getattr(msg, "message_id", None)
        await asyncio.sleep(_DRAFT_RELEASE_HOLD_SECS)
        await self._drop_release_msg()
        logger.info("chat %s: draft release cycle (thinking phase)", self.chat_id)
        try:
            await self.bot(SendRichMessageDraft(chat_id=self.chat_id, draft_id=self._draft_id, **self._draft_extra(),
                                                rich_message={"html": html}))
            self._rendered_text = html
            self._last_edit = time.monotonic()
        except Exception:
            self._rendered_text = ""  # next frame re-sends the indicator
        return True

    async def _drop_release_msg(self) -> None:
        """Delete the release placeholder if still up."""
        mid, self._release_msg_id = self._release_msg_id, None
        if mid is not None:
            with contextlib.suppress(Exception):
                await self.bot.delete_message(self.chat_id, mid)

    def _thinking_placeholder(self) -> str:
        """Static Thinking placeholder, with the model line when set."""
        return self._thinking_html(
            f"{markup.escape_html(i18n.t('stream.thinking', i18n.cached_lang(self.chat_id)))}…")

    async def _render_draft(self) -> None:
        """Push the current text as a native message draft.

        - Appended text between same-id drafts animates letter-by-letter
        - Only model text is streamed, not tool status
        - Status changes would break the growing-prefix animation
        - Drafts cap at 4096 chars; long output shows the tail
        - No cursor by default; finish() posts the real message
        """
        # Row-by-row table streaming via clip_partial_table.
        # - Draft and finish() share the markdown renderer
        # - Dropping the in-progress row keeps each frame valid
        # - Under flood backoff, skip the frame; finish() is correct
        if self._draft_retry_after and time.monotonic() < self._draft_retry_after:
            return
        # Opt-in: hold a still-open trailing table out of frames.
        # - An animated building-table note with row count stands in
        # - Default is the row-by-row clip below
        table_note = ""
        if not _HOLD_OPEN_TABLES:
            body = markup.clip_partial_table(self._full[: self._shown]).strip()
        else:
            held, pending_rows = markup.hold_open_table(self._full[: self._shown])
            body = held.strip()
            if pending_rows is not None:
                table_note = i18n.t("stream.table_building", i18n.cached_lang(self.chat_id),
                                    rows=pending_rows)
        # Wide tables can't render as native drafts (cap 20 columns).
        # - Swap each for the same note final commit uses
        # - The PNG goes only at finish()
        if "|" in body:
            # Reuse the last substitution when the body is identical.
            # - Skips the table re-parse on keepalive or throttled re-send
            if self._wide_cache is not None and self._wide_cache[0] == body:
                body = self._wide_cache[1]
            else:
                _in = body
                body, _wide = markup.extract_wide_tables(body)
                body = self._wide_table_notes(body, _wide)
                self._wide_cache = (_in, body)
        # Hide svg diagrams from the draft while streaming.
        # - Complete ones become the note; unclosed tail is cut
        if "<svg" in body.lower():
            body, _svgs = markup.extract_svgs(body)
            body = self._svg_notes(body, _svgs)
            body = self._hide_unclosed_svg(body)
        # Hide location block JSON from the draft while streaming.
        # - Complete ones become the note; unclosed tail is cut
        _low = body.lower()
        if "```location" in _low or "```geo" in _low:
            body, _locs = markup.extract_locations(body)
            # Pin streams as the same inline map block as final.
            body = self._location_maps(body, _locs)
            body = self._hide_unclosed_location(body)
        if not body:
            # Animate the thinking placeholder; priority, most to least specific.
            # - Live reasoning text tail, unfurling
            # - Live tool phase when no reasoning streams
            # - Otherwise a rotating thinking gerund
            # - Dedup on rendered html: one draft update per change
            if table_note:
                # The reply opens with a table still being written.
                inner = markup.escape_html(table_note)
            elif self._reasoning:
                inner = self._emoji("💭", "think") + " " + markup.escape_html(
                    self._reasoning[-_REASONING_DRAFT_TAIL:])
            elif self._searching:
                # Web search in flight: rotate search-themed gerunds.
                # - Keeps the tag animating; a fixed string doesn't
                # - Search icon is a custom emoji for Premium owners
                lang = i18n.cached_lang(self.chat_id)
                inner = (self._emoji("🔎", "search")
                         + f" {_thinking_label(time.monotonic() - self._start_time, lang, searching=True)}…")
            elif self._phase:
                inner = markup.escape_html(self._phase)
            else:
                lang = i18n.cached_lang(self.chat_id)   # localized gerund
                inner = (self._emoji("💭", "think")
                         + f" {_thinking_label(time.monotonic() - self._start_time, lang)}…")
            html = self._thinking_html(inner)
            # Let user messages through, only in thinking-only phase.
            # - Never while answer text streams
            if (self.draft_release_secs > 0 and not table_note
                    and time.monotonic() - max(self._start_time, self._last_release)
                    >= self.draft_release_secs):
                if await self._release_held_messages(html):
                    return
            # Skip only if unchanged and recently sent.
            # - Otherwise re-send to keep the ~30s draft alive
            if html == self._rendered_text and (time.monotonic() - self._last_edit) < _DRAFT_KEEPALIVE_SECS:
                return
            try:
                await self.bot(
                    SendRichMessageDraft(
                        chat_id=self.chat_id, draft_id=self._draft_id, **self._draft_extra(),
                        rich_message={"html": html},
                    )
                )
                self._rendered_text = html
                self._last_edit = time.monotonic()
            except TelegramRetryAfter as exc:
                self._draft_retry_after = time.monotonic() + float(getattr(exc, "retry_after", 1) or 1)
            except Exception as exc:
                # Custom emoji draft failure falls back to plain unicode.
                # - Causes: lost Premium, bad id, or unsupported in drafts
                # - Unicode always works
                if _OWNER_PREMIUM and _CUSTOM_EMOJI_IDS:
                    self._custom_emoji_failed = True
                # Likewise drop the experimental model line for the turn.
                if isinstance(exc, TelegramBadRequest):
                    self.model_line = ""
            return
        self._phase = None  # real content streaming: drop tool phase
        self._searching = False  # and search-mode rotation
        self._reasoning = ""  # answer started: clear reasoning
        # Stream raw markdown via rich draft so it's formatted live.
        # - Split raw first so a tail fence stays balanced
        # - Stream the frontier chunk; rich limit is 32768
        # - Demote ATX headings to bold: one font, matches final
        # - On failure, fall back to a plain HTML draft
        body = markup.demote_headings(body)
        raw_chunks = markup.split_markdown(body, limit=markup.RICH_LIMIT)
        frontier = raw_chunks[-1] if raw_chunks else body
        if table_note:
            # Table being written below text: keep draft visibly alive.
            # - Row count changes so the block animates
            # - No model line; the reply text streams above
            frontier = f"{frontier}\n\n<tg-thinking>{markup.escape_html(table_note)}</tg-thinking>"
        # Re-send an unchanged frontier before the draft expires.
        # - Prevents streamed text vanishing during a mid-reply pause
        if frontier == self._rendered_text and (time.monotonic() - self._last_edit) < _DRAFT_KEEPALIVE_SECS:
            return
        try:
            await self.bot(
                SendRichMessageDraft(
                    chat_id=self.chat_id,
                    draft_id=self._draft_id,
                    rich_message={"markdown": frontier},
                    **self._draft_extra(),
                )
            )
        except TelegramRetryAfter as exc:
            # Flood: back off and skip this frame.
            # - Don't drop to the pre-grid fallback; it degrades tables
            # - Next tick resumes; finish() is correct
            self._draft_retry_after = time.monotonic() + float(getattr(exc, "retry_after", 1) or 1)
            return
        except Exception:
            # Genuine rich-draft failure: last-resort plain draft.
            # - Rare on rich-capable clients; finish() is always correct
            chunk = markup.md_to_html(frontier) or "…"
            await self._safe(
                lambda: self.bot.send_message_draft(
                    chat_id=self.chat_id, draft_id=self._draft_id,
                    text=f"{chunk}{_DRAFT_CURSOR}", parse_mode="HTML",
                )
            )
        self._rendered_text = frontier
        self._last_edit = time.monotonic()

    async def _render_frame(self) -> None:
        """Paint the revealed prefix into the placeholder.

        - No-op when output equals what is shown
        - Used only by the non-DM write-head path
        """
        if self.message_id is None:
            return
        display = self._render_chunks(self._full[: self._shown])[0] or "…"
        if display == self._rendered_text:
            return
        await self._safe(
            lambda: self.bot.edit_message_text(
                text=display,
                chat_id=self.chat_id,
                message_id=self.message_id,
                parse_mode="HTML",
                link_preview_options=_NO_PREVIEW,
            )
        )
        self._rendered_text = display
        self._last_edit = time.monotonic()

    def _stop_anim(self) -> None:
        if self._anim_task is not None:
            self._anim_task.cancel()
            self._anim_task = None

    # ---- stop control ----

    async def _delayed_control(self) -> None:
        """Post a separate static Stop message after a delay.

        - DM only; skipped if the turn already finished
        - Callback stop:<thread_id> routes to SessionManager.stop
        - Deleted when the turn ends
        """
        try:
            await asyncio.sleep(_CONTROL_DELAY)
        except asyncio.CancelledError:
            return
        async with self._lock:
            if self._closed or not self._streaming or self._control_id is not None:
                return
        lang = i18n.cached_lang(self.chat_id)
        label = i18n.t("stream.working", lang)
        if self.working_note:
            label = f"{label}\n{self.working_note}"
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=i18n.t("btn.stop", lang), callback_data=f"stop:{self.thread_id or 0}")
        ]])
        msg = await self._safe(
            lambda: self.bot.send_message(
                chat_id=self.chat_id,
                text=label,
                parse_mode="HTML",
                disable_notification=True,
                reply_markup=kb,
                link_preview_options=_NO_PREVIEW,
                **self._kwargs(),
            )
        )
        if msg is None:
            return
        cid = getattr(msg, "message_id", None)
        if cid is None:
            return
        # Register the id immediately so cleanup can delete it.
        # - re-check the turn didn't end during the send
        # - otherwise an orphaned control message remains
        self._control_id = cid
        async with self._lock:
            if self._closed or not self._streaming:
                self._control_id = None
                with contextlib.suppress(Exception):
                    await self.bot.delete_message(self.chat_id, cid)
                return
        # Static control message: no animation loop.
        # - stands unedited until the turn ends

    async def _remove_control(self) -> None:
        """Delete the Stop control message (idempotent)."""
        if self._control_task is not None:
            self._control_task.cancel()
            self._control_task = None
        cid = self._control_id
        self._control_id = None
        if cid is not None:
            with contextlib.suppress(Exception):
                await self.bot.delete_message(self.chat_id, cid)

    def cancel(self) -> None:
        """Stop background tasks without finalizing the message.

        - For cancel paths where finish() never runs
        - Partially revealed text stays on screen
        """
        self._closed = True
        self._streaming = False
        self._stop_typing()
        self._stop_anim()
        # Tear down the Stop control message too.
        # - fire-and-forget: cancel() is sync, cannot await
        if self._control_task is not None:
            self._control_task.cancel()
            self._control_task = None
        if self._control_id is not None:
            cid = self._control_id
            self._control_id = None
            with contextlib.suppress(Exception):
                asyncio.create_task(self.bot.delete_message(self.chat_id, cid))
        # Also tear down any release placeholder still up.
        if self._release_msg_id is not None:
            mid, self._release_msg_id = self._release_msg_id, None
            with contextlib.suppress(Exception):
                asyncio.create_task(self.bot.delete_message(self.chat_id, mid))

    # ---- API ----

    async def start(self, placeholder: str | None = None) -> None:
        """Begin the live stream and start animation loops.

        - DM uses drafts; falls back to edit-based write-head
        - Write-head mode sends a real placeholder message
        """
        async with self._lock:
            self._start_time = time.monotonic()
            self._last_edit = 0.0
            self._streaming = True
            self._full = ""
            self._shown = 0
            self._closed = False

            if self.use_drafts:
                # Probe with the <tg-thinking> placeholder block (draft-only).
                # - shows animated Thinking until first real content
                # - only a definitive BadRequest drops to the write-head
                # - transient errors keep drafts on; the loop retries
                # - two attempts: retry without the experimental model line
                for _attempt in range(2):
                    try:
                        await self.bot(
                            SendRichMessageDraft(
                                chat_id=self.chat_id, draft_id=self._draft_id, **self._draft_extra(),
                                rich_message={"html": self._thinking_placeholder()},
                            )
                        )
                    except TelegramBadRequest:
                        if self.model_line:
                            self.model_line = ""
                            continue
                        self.use_drafts = False
                    except Exception:
                        pass
                    break

            if not self.use_drafts:
                if placeholder is None:
                    placeholder = "…"
                msg = await self._safe(
                    lambda: self.bot.send_message(
                        chat_id=self.chat_id,
                        text=placeholder,
                        disable_notification=True,
                        link_preview_options=_NO_PREVIEW,
                        **self._kwargs(),
                    )
                )
                if msg is not None:
                    self.message_id = getattr(msg, "message_id", None)
                # The draft signals activity, so typing runs only here.
                if self._typing_task is None:
                    self._typing_task = asyncio.create_task(self._typing_loop())

            if self._anim_task is None:
                self._anim_task = asyncio.create_task(self._animate_loop())

            # DM drafts can't carry a Stop button.
            # - schedule a separate control message after _CONTROL_DELAY
            # - skipped when not controllable: a mid-draft message re-renders the draft
            if self.use_drafts and self.controllable and self._control_task is None:
                self._control_task = asyncio.create_task(self._delayed_control())

    async def update(self, full_text: str) -> None:
        """Buffer the latest full text for the animator.

        - Never edits here; the frame loop owns edits
        - Keeps the longest snapshot seen
        """
        async with self._lock:
            if len(full_text) >= len(self._full):
                self._full = full_text

    async def finish(self, full_text: str, footer: str = "", notify: bool = True,
                     reply_markup=None) -> None:
        """Final flush: stop loops and commit the persisted text.

        - notify: True for final answer, False for intermediate segments
        - reply_markup attaches an inline keyboard to the message
        """
        async with self._lock:
            # Reveal everything and stop both loops before finalizing.
            # - the animator also re-checks these flags under the lock
            self._streaming = False
            self._full = full_text
            self._shown = len(full_text)
            self._stop_typing()
            self._stop_anim()
            self._closed = True
            await self._commit(full_text, footer, notify, reply_markup=reply_markup)
            self._last_edit = time.monotonic()
        # Outside the lock: tear down this turn's Stop control.
        await self._remove_control()
        await self._drop_release_msg()  # never leave release placeholder behind
        # Web-search Sources card is disabled; finalize call omitted.

    async def segment_break(self) -> None:
        """Commit the current segment and reset for the next.

        - Code mode: each text burst becomes its own message
        - Silent; streaming stays live; no-op when empty
        """
        async with self._lock:
            text = self._full.strip()
            if not text:
                return
            await self._commit(text, footer="", notify=False)
            await self._begin_next_segment()

    async def flush_segment(self, text: str) -> None:
        """Commit a caller-provided prefix as its own message.

        - Like segment_break, but commits only the given text
        - Used to post closed code blocks mid-stream
        - No-op for blank text
        - Caller resets its running text to the remainder
        """
        async with self._lock:
            if not text or not text.strip():
                return
            await self._commit(text, footer="", notify=False)
            await self._begin_next_segment()

    async def _begin_next_segment(self) -> None:
        """Reset buffer and draft so the next segment is fresh.

        - Caller holds the lock
        - Shared by segment_break and flush_segment
        """
        self._full = ""
        self._shown = 0
        self._rendered_text = ""
        self.message_id = None
        if self.use_drafts:
            # Reset the draft to the placeholder for the next segment.
            # - the committed message stands permanently above it
            with contextlib.suppress(Exception):
                await self.bot(
                    SendRichMessageDraft(
                        chat_id=self.chat_id, draft_id=self._draft_id, **self._draft_extra(),
                        rich_message={"html": self._thinking_placeholder()},
                    )
                )
        else:
            msg = await self._safe(
                lambda: self.bot.send_message(
                    chat_id=self.chat_id,
                    text="…",
                    disable_notification=True,
                    link_preview_options=_NO_PREVIEW,
                    **self._kwargs(),
                )
            )
            if msg is not None:
                self.message_id = getattr(msg, "message_id", None)

    def _build_sendables(self, full_text: str, render_fn) -> list:
        """Split the final answer into ordered sendables.

        - Text HTML chunks and native rich tables
        - Every markdown table is sent as a native table
        - Falls back to a pre grid if the call fails
        """
        out: list = []
        # Route every table through the native rich-table path.
        for item in markup.split_rich_tables(full_text):
            if isinstance(item, markup.RichTable):
                out.append(("rich", item))
                continue
            for chunk in render_fn(item):
                if chunk and not markup.is_empty_render(chunk):
                    out.append(("text", chunk))
        return out

    async def _send_rich(self, table, silent: bool) -> None:
        """Send one markdown table as a native Telegram table.

        - Uses sendRichMessage; any failure falls back to a pre grid
        """
        html = markup.table_to_rich_html(table.rows, table.aligns)
        try:
            await self.bot(
                SendRichMessage(
                    chat_id=self.chat_id,
                    rich_message={"html": html},
                    disable_notification=silent,
                    **self._kwargs(),
                )
            )
            return
        except Exception:
            logger.warning("sendRichMessage failed; falling back to <pre> grid", exc_info=True)
        # Fallback: legacy monospace grid (cells stripped and escaped).
        esc = [[markup.escape_html(markup._strip_cell_emphasis(c)) for c in r] for r in table.rows]
        await self._safe(
            lambda: self.bot.send_message(
                chat_id=self.chat_id,
                text=markup._render_table_pre(esc),
                parse_mode="HTML",
                disable_notification=silent,
                link_preview_options=_NO_PREVIEW,
                **self._kwargs(),
            )
        )

    def _wide_table_notes(self, rich_text: str, wide_tables: list) -> str:
        """Replace wide-table tokens with the localized note.

        - The table itself is sent separately as a PNG
        - Shared by final commit and draft path
        - Avoids sending an over-cap native draft
        - No-op when nothing is wide
        """
        if not wide_tables:
            return rich_text
        lang = i18n.cached_lang(self.chat_id)
        parts = rich_text.split(markup.WIDE_TABLE_TOKEN)
        out = parts[0]
        for idx, tbl in enumerate(wide_tables):
            out += i18n.t("stream.wide_table", lang, n=idx + 1,
                          cols=markup.table_col_count(tbl.rows)) + parts[idx + 1]
        return out

    def _svg_notes(self, rich_text: str, svgs: list) -> str:
        """Replace svg tokens with the localized image note.

        - The diagram is sent separately as a PNG
        - Shared by final commit and draft path
        """
        if not svgs:
            return rich_text
        lang = i18n.cached_lang(self.chat_id)
        parts = rich_text.split(markup.SVG_TOKEN)
        out = parts[0]
        note = i18n.t("stream.svg_image", lang)
        for idx in range(len(svgs)):
            out += note + (parts[idx + 1] if idx + 1 < len(parts) else "")
        return out

    def _hide_unclosed_svg(self, body: str) -> str:
        """Hide an unclosed svg from a streaming draft.

        - Cut from the open svg to the end
        - Leaves a transient rendering note
        """
        low = body.lower()
        cut = low.rfind("<svg")
        if cut == -1 or "</svg>" in low[cut:]:
            return body
        fence = body.rfind("```", 0, cut)
        pos = fence if fence != -1 else cut
        note = i18n.t("stream.svg_rendering", i18n.cached_lang(self.chat_id))
        return (body[:pos].rstrip() + "\n" + note).strip()

    async def _send_svg_image(self, svg: str) -> None:
        """Rasterize one svg diagram to PNG and send it.

        - On render failure, sends the raw .svg document
        - Always a silent intermediate message
        """
        try:
            png = await asyncio.to_thread(svg_image.render_svg_png, svg)
        except Exception:
            logger.warning("svg render failed; sending raw .svg document", exc_info=True)
            with contextlib.suppress(Exception):
                await self.bot.send_document(
                    chat_id=self.chat_id,
                    document=BufferedInputFile(svg.encode("utf-8"), filename="diagram.svg"),
                    disable_notification=True, **self._kwargs(),
                )
            return
        await self._safe(
            lambda: self.bot.send_photo(
                chat_id=self.chat_id,
                photo=BufferedInputFile(png, filename="diagram.png"),
                disable_notification=True, **self._kwargs(),
            )
        )

    def _location_notes(self, rich_text: str, locations: list) -> str:
        """Replace location tokens with the localized note.

        - The pin is sent separately as a native map
        - Shared by final commit and draft path
        """
        if not locations:
            return rich_text
        lang = i18n.cached_lang(self.chat_id)
        note = i18n.t("stream.location", lang)
        # Replace each LOCATION_TOKEN present with the note.
        # - token and location counts match by construction
        # - joining on real tokens never drops a trailing part
        return note.join(rich_text.split(markup.LOCATION_TOKEN))

    @staticmethod
    def _map_block(loc: dict) -> str:
        """One map pin as a native rich map block.

        - Same block in draft and final message
        - Title and address become the caption
        """
        lat, lon = float(loc["lat"]), float(loc["lon"])
        block = f'<tg-map lat="{lat:.6f}" long="{lon:.6f}" zoom="15"/>'
        cap = " — ".join(markup.escape_html(str(loc[k])) for k in ("title", "address")
                         if loc.get(k))
        if cap:
            block = f"<figure>{block}<figcaption>{cap}</figcaption></figure>"
        return f"\n\n{block}\n\n"

    def _location_maps(self, rich_text: str, locations: list) -> str:
        """Replace each location token with its inline map block."""
        if not locations:
            return rich_text
        parts = rich_text.split(markup.LOCATION_TOKEN)
        out = parts[0]
        for idx, part in enumerate(parts[1:]):
            out += (self._map_block(locations[idx]) if idx < len(locations) else "") + part
        return out

    def _hide_unclosed_location(self, body: str) -> str:
        """Hide an unclosed location fence from a streaming draft.

        - Cut from the open fence; leave the note
        - Complete blocks are already replaced earlier
        """
        low = body.lower()
        cut = max(low.rfind("```location"), low.rfind("```geo"))
        if cut == -1 or "```" in body[cut + 3:]:  # no open fence, or already closed
            return body
        note = i18n.t("stream.location", i18n.cached_lang(self.chat_id))
        return (body[:cut].rstrip() + "\n" + note).strip()

    async def _send_location(self, loc: dict) -> None:
        """Deliver one location block as a real Telegram map.

        - Venue card when title and address exist, else a pin
        - Always a silent intermediate message
        """
        lat, lon = loc["lat"], loc["lon"]
        # Try the venue card first, then a plain pin.
        # - _safe returns None when Telegram rejects (e.g. long title)
        # - valid coordinates must always drop a marker
        if loc.get("title") and loc.get("address"):
            if await self._safe(
                lambda: self.bot.send_venue(
                    chat_id=self.chat_id, latitude=lat, longitude=lon,
                    title=loc["title"], address=loc["address"],
                    disable_notification=True, **self._kwargs(),
                )
            ):
                return
        # Log a lost pin; otherwise it vanishes without trace.
        if await self._safe(
            lambda: self.bot.send_location(
                chat_id=self.chat_id, latitude=lat, longitude=lon,
                disable_notification=True, **self._kwargs(),
            )
        ) is None:
            logger.warning("interleave: dropped a map pin at (%s, %s) — both sends failed",
                           lat, lon)

    async def _send_wide_table_image(self, table) -> None:
        """Send one wide (over 20 columns) table as a PNG.

        - Native rich tables cap at 20 columns
        - Falls back to a pre grid without the table font
        - Always a silent intermediate message
        """
        try:
            esc = [[markup._strip_cell_emphasis(c) for c in r] for r in table.rows]
            # PIL raster is synchronous CPU; run it off the loop.
            # - else a wide-table reply freezes other users' streams
            png = await asyncio.to_thread(table_image.render_table_png, esc)
        except Exception:
            logger.warning("wide-table PNG render failed; <pre> grid fallback", exc_info=True)
            grid = [[markup.escape_html(markup._strip_cell_emphasis(c)) for c in r] for r in table.rows]
            await self._safe(
                lambda: self.bot.send_message(
                    chat_id=self.chat_id,
                    text=markup._render_table_pre(grid),
                    parse_mode="HTML",
                    disable_notification=True,
                    link_preview_options=_NO_PREVIEW,
                    **self._kwargs(),
                )
            )
            return
        await self._safe(
            lambda: self.bot.send_photo(
                chat_id=self.chat_id,
                photo=BufferedInputFile(png, filename="table.png"),
                disable_notification=True,
                **self._kwargs(),
            )
        )

    async def update_todo_card(self, todos: list, lang: str = "en") -> None:
        """Render or refresh the live task-list card.

        - Separate rich message, edited in place; one per turn
        - Best-effort: send or edit failures are swallowed
        """
        total, done, open_, body = markup.summarize_todos(todos)
        if total == 0:
            return
        header = i18n.t("todo.card_header", lang, n=total, done=done, open=open_)
        # Header-to-body needs a markdown hard break (two spaces, newline).
        # - a bare newline is a soft break in rich markdown
        rich = {"markdown": f"{header}  \n{body}"}
        try:
            if self._todo_msg_id is None:
                msg = await self.bot(
                    SendRichMessage(
                        chat_id=self.chat_id,
                        rich_message=rich,
                        disable_notification=True,
                        **self._kwargs(),
                    )
                )
                self._todo_msg_id = getattr(msg, "message_id", None)
            else:
                await self.bot(
                    EditRichMessage(
                        chat_id=self.chat_id,
                        message_id=self._todo_msg_id,
                        rich_message=rich,
                    )
                )
        except Exception:
            # Edit failures (unchanged, deleted card) must not disturb the turn.
            logger.debug("todo card update failed", exc_info=True)

    # Web-search Sources card is currently disabled.
    # - its call sites in sessions.py and finish() are commented
    # - helper functions kept intact
    async def add_web_source(self, kind: str, value: str, lang: str = "en") -> None:
        """Collect a web source and re-render the Sources card.

        - Separate rich message, edited in place as sources arrive
        - Dedups and caps at 15; best-effort
        """
        value = (value or "").strip()
        if not value:
            return
        key = (kind, value)
        if key in self._web_sources_seen or len(self._web_sources) >= 15:
            return
        self._web_sources_seen.add(key)
        self._web_sources.append(key)
        rich = {"markdown": sources_card_markdown(self._web_sources, lang)}
        try:
            if self._sources_msg_id is None:
                msg = await self.bot(
                    SendRichMessage(
                        chat_id=self.chat_id,
                        rich_message=rich,
                        disable_notification=True,
                        **self._kwargs(),
                    )
                )
                self._sources_msg_id = getattr(msg, "message_id", None)
            else:
                await self.bot(
                    EditRichMessage(
                        chat_id=self.chat_id,
                        message_id=self._sources_msg_id,
                        rich_message=rich,
                    )
                )
        except Exception:
            logger.debug("sources card update failed", exc_info=True)

    async def finalize_sources(self) -> None:
        """Flip the research card header from Searching to Sources.

        - No-op if no web tool ran
        - Best-effort; never disturbs the finished answer
        """
        if self._sources_msg_id is None or not self._web_sources:
            return
        lang = i18n.cached_lang(self.chat_id)
        rich = {"markdown": sources_card_markdown(self._web_sources, lang, done=True)}
        with contextlib.suppress(Exception):
            await self.bot(
                EditRichMessage(
                    chat_id=self.chat_id,
                    message_id=self._sources_msg_id,
                    rich_message=rich,
                )
            )

    async def _commit_rich_markdown(self, full_text: str, footer: str, silent: bool,
                                    reply_markup=None) -> bool:
        """Post the entire reply as one native rich message.

        - Returns True on success; False falls back to classic
        - Fenced code renders as plain monospace in rich messages
        - Split-by-segment alternative lives in _commit_mixed
        """
        # Demote ATX headings to bold: one font in the reply.
        # - matches the draft; emoji decoration left to the model
        md = markup.demote_headings(full_text).strip() or "…"
        if footer:
            # Italicize each footer line separately.
            # - markdown italic can't span a newline
            # - join with a hard break, not a bare newline
            foot = "  \n".join(f"_{ln}_" for ln in footer.splitlines() if ln.strip())
            md = f"{md}\n\n{foot}"
        try:
            await self.bot(
                SendRichMessage(
                    chat_id=self.chat_id,
                    rich_message={"markdown": md},
                    disable_notification=silent,
                    reply_markup=reply_markup,
                    **self._kwargs(),
                )
            )
        except Exception:
            logger.warning("sendRichMessage(markdown) failed; legacy fallback", exc_info=True)
            return False
        # Rich message is a fresh bubble: clear the write-head placeholder.
        # - DM drafts have none; they self-expire
        if self.message_id is not None:
            with contextlib.suppress(Exception):
                await self.bot.delete_message(self.chat_id, self.message_id)
            self.message_id = None
        self._rendered_text = md
        return True

    async def _commit_rich_embedded(self, rich_text: str, locations: list, svgs: list,
                                    wide_tables: list, footer: str, silent: bool,
                                    reply_markup=None) -> bool:
        """Post a reply with out-of-band blocks as one rich message.

        - Map pins become inline map blocks
        - Diagrams and wide tables embed as PNG media
        - Failed diagram embeds as .svg; failed table as text grid
        - Returns False when the send fails or media exceeds limit
        """
        loc_q, svg_q, tbl_q = list(locations), list(svgs), list(wide_tables)
        if len(svg_q) + len(tbl_q) > _RICH_MEDIA_MAX:
            return False
        media: list[dict] = []

        def _attach(kind: str, data: bytes, filename: str) -> str:
            mid = f"m{len(media) + 1}"
            media.append({"id": mid, "media": {"type": kind,
                                               "media": BufferedInputFile(data, filename=filename)}})
            return f"\n\n![](tg://{kind}?id={mid})\n\n"

        out: list[str] = []
        for idx, seg in enumerate(markup.split_on_attachment_tokens(rich_text)):
            if not idx % 2:
                out.append(seg)
                continue
            if seg == markup.LOCATION_TOKEN and loc_q:
                out.append(self._map_block(loc_q.pop(0)))
            elif seg == markup.SVG_TOKEN and svg_q:
                svg = svg_q.pop(0)
                try:
                    png = await asyncio.to_thread(svg_image.render_svg_png, svg)
                    out.append(_attach("photo", png, "diagram.png"))
                except Exception:
                    logger.warning("svg render failed; embedding the raw .svg", exc_info=True)
                    out.append(_attach("document", svg.encode("utf-8"), "diagram.svg"))
            elif seg == markup.WIDE_TABLE_TOKEN and tbl_q:
                tbl = tbl_q.pop(0)
                try:
                    rows = [[markup._strip_cell_emphasis(c) for c in r] for r in tbl.rows]
                    png = await asyncio.to_thread(table_image.render_table_png, rows)
                    out.append(_attach("photo", png, "table.png"))
                except Exception:
                    logger.warning("wide-table render failed; embedding a text grid",
                                   exc_info=True)
                    grid = markup._render_table_pre(
                        [[markup._strip_cell_emphasis(c) for c in r] for r in tbl.rows])
                    out.append("\n\n```\n" + grid[len("<pre>"):-len("</pre>")] + "\n```\n\n")
        md = markup.demote_headings("".join(out)).strip() or "…"
        if footer:
            foot = "  \n".join(f"_{ln}_" for ln in footer.splitlines() if ln.strip())
            md = f"{md}\n\n{foot}"
        rich: dict = {"markdown": md}
        if media:
            rich["media"] = media
        try:
            await self.bot(
                SendRichMessage(
                    chat_id=self.chat_id,
                    rich_message=rich,
                    disable_notification=silent,
                    reply_markup=reply_markup,
                    **self._kwargs(),
                )
            )
        except Exception:
            logger.warning("embedded rich send failed; interleave fallback", exc_info=True)
            return False
        if self.message_id is not None:
            with contextlib.suppress(Exception):
                await self.bot.delete_message(self.chat_id, self.message_id)
            self.message_id = None
        self._rendered_text = md
        return True

    async def _commit_rich_interleaved(self, rich_text: str, locations: list, svgs: list,
                                       wide_tables: list, footer: str, silent_first: bool,
                                       reply_markup=None) -> None:
        """Deliver out-of-band blocks interleaved at their document positions.

        - Splits rich body at each token; sends block in place
        - Empty text runs send no bubble
        - Footer and keypad ride the last non-empty text bubble
        - Each bubble falls back to classic HTML; always delivers
        """
        # Ordered queues, each in document order.
        loc_q, svg_q, tbl_q = list(locations), list(svgs), list(wide_tables)
        # split() keeps tokens: even indices prose, odd indices sentinels.
        parts = markup.split_on_attachment_tokens(rich_text)
        # A token inside a fenced block splits the fence.
        # - repair prose runs so each has balanced backticks
        # - a reply without such tokens is returned unchanged
        parts = markup.repair_fences_across_tokens(parts)
        # Segments are fresh messages: drop the write-head placeholder.
        # - DM drafts have none; they self-expire
        if self.message_id is not None:
            with contextlib.suppress(Exception):
                await self.bot.delete_message(self.chat_id, self.message_id)
            self.message_id = None
        # Last non-empty prose run carries the footer and keypad.
        last_text_idx = max((i for i, p in enumerate(parts) if i % 2 == 0 and p.strip()), default=-1)
        first = True
        for idx, seg in enumerate(parts):
            if idx % 2:  # odd index: attachment token; send its native message here
                if seg == markup.LOCATION_TOKEN and loc_q:
                    await self._send_location(loc_q.pop(0))
                elif seg == markup.SVG_TOKEN and svg_q:
                    await self._send_svg_image(svg_q.pop(0))
                elif seg == markup.WIDE_TABLE_TOKEN and tbl_q:
                    await self._send_wide_table_image(tbl_q.pop(0))
                continue
            if not seg.strip():
                continue  # empty prose run: no bubble
            silent = silent_first if first else True
            first = False
            md = markup.demote_headings(seg).strip()  # one font
            if footer and idx == last_text_idx:
                foot = "  \n".join(f"_{ln}_" for ln in footer.splitlines() if ln.strip())
                md = f"{md}\n\n{foot}"
            kb = reply_markup if idx == last_text_idx else None
            try:
                await self.bot(
                    SendRichMessage(
                        chat_id=self.chat_id, rich_message={"markdown": md},
                        disable_notification=silent, reply_markup=kb, **self._kwargs(),
                    )
                )
            except Exception:
                # Single rich send failed, usually prose exceeding the message limit.
                # - split and send each piece as HTML
                # - size pieces by rendered HTML; escaping inflates raw chunks
                # - render_within_limit keeps every piece within HARD_LIMIT
                # - keypad rides last piece; only first keeps notify
                # - skip blank <pre></pre> pieces, keep one carrier
                htmls = [h for raw in (markup.split_markdown(md) or [md])
                         for h in markup.render_within_limit(raw)
                         if not markup.is_empty_render(h)] or ["…"]
                for pi, piece_html in enumerate(htmls):
                    p_kb = kb if pi == len(htmls) - 1 else None
                    p_silent = silent if pi == 0 else True
                    sent = await self._safe(
                        lambda h=piece_html, s=p_silent, k=p_kb: self.bot.send_message(
                            chat_id=self.chat_id, text=h, parse_mode="HTML",
                            disable_notification=s, link_preview_options=_NO_PREVIEW,
                            reply_markup=k, **self._kwargs(),
                        )
                    )
                    if sent is None:
                        logger.warning("interleave fallback: dropped a %d-char HTML piece "
                                       "(send failed after render_within_limit)", len(piece_html))
        # Attachment-only reply: send a trailing bubble for footer and keypad.
        # - Telegram rejects empty text
        # - a keypad without footer uses an invisible carrier
        if last_text_idx == -1 and (footer or reply_markup):
            foot_html = f"<i>{markup.escape_html(footer)}</i>" if footer else "\u2063"
            sent = await self._safe(
                lambda h=foot_html: self.bot.send_message(
                    chat_id=self.chat_id, text=h,
                    parse_mode="HTML", disable_notification=True,
                    link_preview_options=_NO_PREVIEW, reply_markup=reply_markup,
                    **self._kwargs(),
                )
            )
            # Keypad-only send: retry with a visible carrier if rejected.
            # - invisible U+2063 is unverified against the empty-text check
            # - with a footer, failure is not emptiness; skip retry
            # - log if even the retry fails
            if sent is None and reply_markup is not None and not footer:
                sent = await self._safe(
                    lambda: self.bot.send_message(
                        chat_id=self.chat_id, text="\u2026",
                        parse_mode="HTML", disable_notification=True,
                        link_preview_options=_NO_PREVIEW, reply_markup=reply_markup,
                        **self._kwargs(),
                    )
                )
            if sent is None:
                logger.warning("interleave: dropped the trailing footer/keypad bubble (send "
                               "failed%s)", " after carrier retry" if (reply_markup and not footer) else "")
        self._rendered_text = rich_text

    async def _commit_mixed(self, full_text: str, footer: str, silent_first: bool) -> None:
        """Split a reply containing code by code block.

        - Prose and tables go as rich messages
        - Code blocks go classic, with language and copy
        - Footer rides the last segment; rich falls back to HTML
        """
        segs = [(k, s) for (k, s) in markup.split_code_blocks(full_text) if s.strip()]
        if not segs:
            segs = [("text", "…")]
        # Segments are fresh messages: drop the write-head placeholder.
        # - DM drafts have none; they self-expire
        if self.message_id is not None:
            with contextlib.suppress(Exception):
                await self.bot.delete_message(self.chat_id, self.message_id)
            self.message_id = None
        last = len(segs) - 1
        for idx, (kind, seg) in enumerate(segs):
            silent = silent_first if idx == 0 else True
            want_footer = bool(footer) and idx == last
            if kind == "code":
                code_html = markup.md_to_html(seg)
                await self._safe(
                    lambda h=code_html, s=silent: self.bot.send_message(
                        chat_id=self.chat_id, text=h, parse_mode="HTML",
                        disable_notification=s, link_preview_options=_NO_PREVIEW,
                        **self._kwargs(),
                    )
                )
            else:
                md = markup.demote_headings(seg).strip()  # one font
                if want_footer:
                    foot = "  \n".join(f"_{ln}_" for ln in footer.splitlines() if ln.strip())
                    md = f"{md}\n\n{foot}"
                    want_footer = False
                try:
                    await self.bot(
                        SendRichMessage(
                            chat_id=self.chat_id, rich_message={"markdown": md},
                            disable_notification=silent, **self._kwargs(),
                        )
                    )
                except Exception:
                    # Render md, not seg, so the fallback keeps the footer.
                    seg_html = markup.md_to_html(md)
                    await self._safe(
                        lambda h=seg_html, s=silent: self.bot.send_message(
                            chat_id=self.chat_id, text=h, parse_mode="HTML",
                            disable_notification=s, link_preview_options=_NO_PREVIEW,
                            **self._kwargs(),
                        )
                    )
            if want_footer:   # after code, footer goes on its own line
                await self._safe(
                    lambda: self.bot.send_message(
                        chat_id=self.chat_id,
                        text=f"<i>{markup.escape_html(footer)}</i>",
                        parse_mode="HTML", disable_notification=True,
                        link_preview_options=_NO_PREVIEW, **self._kwargs(),
                    )
                )
        self._rendered_text = full_text

    async def _commit(self, full_text: str, footer: str, notify: bool, reply_markup=None) -> None:
        """Render full_text and post it as permanent messages.

        - Caller holds the lock and owns streaming flags
        - Links never preview; only the first message pings
        - Whole reply is one rich message; chunking is the fallback
        - Very long replies become a .md document
        """
        silent_first = not notify
        footer_line = f"\n\n<i>{markup.escape_html(footer)}</i>" if footer else ""

        # Send the whole reply as ONE rich message, code included.
        # - rich renders fences as plain monospace
        # - native rich tables cap at 20 columns
        # - svg diagrams, wide tables, location pins are extracted first
        # - each extractor leaves a localized note; order is independent
        loc_text, locations = markup.extract_locations(full_text)
        svg_text, svgs = markup.extract_svgs(loc_text)
        rich_text, wide_tables = markup.extract_wide_tables(svg_text)
        # Out-of-band blocks are interleaved: split the bubble at each spot.
        # - pins, svg diagrams, wide tables send native messages in order
        # - raw *_TOKEN sentinels must survive into the interleaver
        # - so note-substitution helpers are not applied here
        # - the draft path still applies them
        if locations or svgs or wide_tables:
            # One rich message with embedded blocks; interleave is the fallback.
            # - A session without rich blocks (MAX) interleaves straight away
            embeds = getattr(self.bot.session, "embeds_rich_media", None)
            if (embeds is None or embeds(self.chat_id)) and await self._commit_rich_embedded(
                    rich_text, locations, svgs, wide_tables, footer, silent_first,
                    reply_markup=reply_markup):
                return
            await self._commit_rich_interleaved(
                rich_text, locations, svgs, wide_tables, footer, silent_first,
                reply_markup=reply_markup,
            )
            return
        # No out-of-band blocks: one plain rich bubble, no tokens.
        if await self._commit_rich_markdown(rich_text, footer, silent_first, reply_markup=reply_markup):
            return

        # Fallbacks run only when no blocks and rich send failed.
        # - so locations, svgs, wide tables are empty here
        # - note and pin handling is a defensive no-op
        loc_noted = self._location_notes(loc_text, locations)

        # Very long output (fallback): deliver as a document.
        if markup.should_send_as_file(loc_noted):
            note_chunk = self._render_chunks(
                i18n.t("stream.too_long", i18n.cached_lang(self.chat_id))
            )[0]
            if self.message_id is not None:
                await self._safe(
                    lambda: self.bot.edit_message_text(
                        text=note_chunk,
                        chat_id=self.chat_id,
                        message_id=self.message_id,
                        parse_mode="HTML",
                        link_preview_options=_NO_PREVIEW,
                    )
                )
            document = markup.as_document(loc_noted, "response.md")
            await self._safe(
                lambda: self.bot.send_document(
                    chat_id=self.chat_id,
                    document=document,
                    disable_notification=silent_first,
                    reply_markup=reply_markup,  # keep the shell keypad on fallback
                    **self._kwargs(),
                )
            )
            if footer_line:
                await self._safe(
                    lambda: self.bot.send_message(
                        chat_id=self.chat_id,
                        text=footer_line.lstrip("\n"),
                        parse_mode="HTML",
                        disable_notification=True,
                        link_preview_options=_NO_PREVIEW,
                        **self._kwargs(),
                    )
                )
            self._rendered_text = note_chunk
            for loc in locations:  # also deliver pins on document fallback
                await self._send_location(loc)
            return

        # Legacy fallback: classic HTML chunks plus native-table bubbles.
        # - a failed rich send never loses a reply
        # - code isolation follows the /codesplit toggle
        # - one ellipsis chunk keeps an empty turn visible
        render_fn = self._render_message_chunks if self._split_code_messages else self._render_chunks
        sendables = self._build_sendables(loc_noted, render_fn) or [("text", "…")]

        # Footer joins the last text sendable if it fits.
        # - otherwise it is sent alone
        footer_as_message = bool(footer_line)
        if footer_line:
            for idx in range(len(sendables) - 1, -1, -1):
                kind, payload = sendables[idx]
                if kind == "text" and len(payload) + len(footer_line) <= markup.HARD_LIMIT:
                    sendables[idx] = ("text", f"{payload}{footer_line}")
                    footer_as_message = False
                    break

        # Send in order; first text sendable replaces the placeholder.
        # - photos and the rest are sent fresh
        # - only the first send may ping the user
        placeholder_used = False
        first_send = True
        kb_pending = reply_markup  # keypad goes on the first text message
        for kind, payload in sendables:
            silent = silent_first if first_send else True
            if kind == "rich":
                # A native Telegram table gets its own bubble.
                # - it does not consume the streaming placeholder
                await self._send_rich(payload, silent)
            elif kind == "photo":
                await self._safe(
                    lambda p=payload, s=silent: self.bot.send_photo(
                        chat_id=self.chat_id,
                        photo=BufferedInputFile(p, filename="table.png"),
                        disable_notification=s,
                        **self._kwargs(),
                    )
                )
            elif self.message_id is not None and not placeholder_used:
                kb, kb_pending = kb_pending, None  # first text gets the keypad
                await self._safe(
                    lambda t=payload, k=kb: self.bot.edit_message_text(
                        text=t,
                        chat_id=self.chat_id,
                        message_id=self.message_id,
                        parse_mode="HTML",
                        link_preview_options=_NO_PREVIEW,
                        reply_markup=k,
                    )
                )
                self._rendered_text = payload
                placeholder_used = True
            else:
                kb, kb_pending = kb_pending, None  # first text gets the keypad
                await self._safe(
                    lambda t=payload, s=silent, k=kb: self.bot.send_message(
                        chat_id=self.chat_id,
                        text=t,
                        parse_mode="HTML",
                        disable_notification=s,
                        link_preview_options=_NO_PREVIEW,
                        reply_markup=k,
                        **self._kwargs(),
                    )
                )
                self._rendered_text = payload
            first_send = False

        # Unconsumed group placeholder (photo-only answer): replace it with a marker.
        # - avoids orphaning its typing text
        if self.message_id is not None and not placeholder_used:
            await self._safe(
                lambda: self.bot.edit_message_text(
                    text="📊",
                    chat_id=self.chat_id,
                    message_id=self.message_id,
                    parse_mode="HTML",
                    link_preview_options=_NO_PREVIEW,
                )
            )

        if footer_as_message:
            await self._safe(
                lambda: self.bot.send_message(
                    chat_id=self.chat_id,
                    text=footer_line.lstrip("\n"),
                    parse_mode="HTML",
                    disable_notification=True,
                    link_preview_options=_NO_PREVIEW,
                    **self._kwargs(),
                )
            )

        # Deliver location pins on the legacy fallback path too.
        # - the rich path returns earlier, so pins are sent once
        for loc in locations:
            await self._send_location(loc)
