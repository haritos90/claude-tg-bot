"""Live-updating Telegram message with a typewriter write-head.

A Streamer owns one placeholder message in a topic and reveals the model's reply
in it like a write-head "typing" across the message: text the model has produced
is held in a buffer, and a frame loop reveals it a chunk of characters at a time
while sliding a rotating braille caret to the new frontier. When the reveal
catches up to what the model has produced (or before the first token), the caret
just spins in place. Telegram caps single-message edits to ~1/second, so we
cannot truly animate per-character — each frame reveals a controlled number of
buffered characters instead, which still reads as writing.

The final flush renders the complete text (no caret), splitting long output into
chunks or a .md document. Tool-status lines are shown above the streamed text.
Every Telegram call is wrapped so a transient error never crashes the run.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
)

import i18n
import markup
import table_image  # noqa: F401  — kept for the commented-out #162 PNG-table revert path
from rich_message import SendRichMessage, SendRichMessageDraft

logger = logging.getLogger("streamer")

# Links in model output should stay inline — never expand into a web-page preview
# card (the owner asked for this; previews are noisy and can look like an
# attachment). Passed to every text send/edit.
_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)

# The caret/write-head animation is retired: DM streams via native Telegram drafts
# (Telegram owns the typewriter and any custom trailing glyph just flickers), and
# the dormant group write-head reveals text caret-free. Only the reveal-pacing
# presets below survive (they pace the write-head's per-edit reveal).

# Speed presets: (frame_interval seconds, base_step chars revealed per frame).
# Telegram caps single-message edits to ~1/sec, so frame_interval can't go much
# below that without tripping 429s — the caret rotation rate is bounded by it.
# "normal" targets ~16 chars/sec (reading pace) with a lively ~1.2 Hz caret.
CARET_SPEEDS: dict[str, tuple[float, int]] = {
    "calm":   (1.0, 8),
    "normal": (0.85, 14),
    "fast":   (0.7, 26),
}
_DEFAULT_SPEED = "normal"

# Clear a reveal backlog (model far ahead of the reveal) within ~this many frames.
_CATCHUP = 5

# ---------------------------------------------------------------- native drafts
# Native message-draft streaming (private chats / DM only — Telegram rejects
# drafts in supergroups with TEXTDRAFT_PEER_INVALID). Unlike edit_message_text,
# which Telegram throttles to ~1 edit/sec, sendMessageDraft is purpose-built for
# live generation: the client smoothly animates the text between updates, so we
# get genuine streaming instead of the once-a-second write-head. The draft is
# ephemeral (≈30s preview); finish() sends the real, persisted message at the end.
#
# draft_id must be NON-ZERO; reusing one id per chat means each update animates in
# place. Turns are serial per chat (one worker), so a single constant id is safe.
_DRAFT_ID = 1
# Sustainable draft cadence (≈5/sec). Measured against the live API: short bursts
# up to ~25/sec pass, but sustained sending below ~110ms/update trips a 3-second
# RetryAfter penalty (which reads as stutter). At ~5/sec the client still has
# plenty of keyframes to animate the appended characters letter-by-letter.
_DRAFT_INTERVAL = 0.2
# Optional console cursor appended at the typing frontier. Default OFF (""):
# Telegram's native draft animation owns the frontier and largely absorbs a
# trailing glyph — a rotating one just flickers and vanishes, and even a steady
# block is barely visible — so a custom caret adds little here. Telegram draws its
# own streaming indicator. Set e.g. "▌" to force a console cursor back on.
_DRAFT_CURSOR = ""

# A DM draft can't carry an inline button (send_message_draft has no reply_markup),
# so the ⏹ Stop affordance lives on a SEPARATE control message. To avoid flicker on
# quick replies, it's posted only once a turn has been running this long, and it's
# removed when the turn ends. (#49)
_CONTROL_DELAY = 3.0

# The ⏹ Stop control message used to animate a braille spinner here (#94). The
# animation was removed at the owner's request: capped at ~1 edit/sec it updated
# too slowly to read as motion and just flickered. The control is now a STATIC
# label + Stop button (see _delayed_control).


def resolve_speed(name: str | None) -> tuple[float, int]:
    """Return (frame_interval, base_step) for a speed preset name."""
    return CARET_SPEEDS.get(name or "", CARET_SPEEDS[_DEFAULT_SPEED])


class Streamer:
    """A single self-editing Telegram message for one streamed turn.

    thread_id is the real topic key; None (or 0) means the General topic and is
    rendered without a message_thread_id. We accept None for "General"; callers
    in this project pass None when the thread key is 0.
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
        # #172: whether to post the separate ⏹ Stop control message mid-stream. The
        # /test demo turns this OFF — a new message arriving mid-draft makes some
        # clients re-render the draft from the top (looks like it "regenerates").
        self.controllable = bool(controllable)
        # #164: an extra line shown under "Working…" in the Stop-control plate —
        # the user's own limit (≥50%) or, for the owner, the account usage.
        self.working_note = working_note or ""
        # Normalise the General topic (0) to None so _kwargs() omits the field.
        self.thread_id = thread_id if thread_id else None
        d_interval, d_step = CARET_SPEEDS[_DEFAULT_SPEED]
        self.frame_interval = frame_interval or d_interval
        self.base_step = base_step or d_step
        # Native draft streaming is only valid in a private chat (chat_id > 0);
        # guard here so a stray call in a group can never try (and fail) drafts.
        # start() probes once and falls back to the write-head if drafts error.
        self.use_drafts = bool(use_drafts) and chat_id > 0
        # Whether finish() isolates each fenced code block into its OWN message
        # (default — easy mobile copy); owner-toggleable via /codesplit. Off →
        # code stays inline in the reply.
        self._split_code_messages = bool(split_code_messages)
        # Drafts stream at a fixed, flood-safe cadence; Telegram animates the newly
        # appended characters between updates (the native letter-by-letter effect).
        self._draft_interval = _DRAFT_INTERVAL

        self.message_id: int | None = None
        self._start_time: float = 0.0
        self._last_edit: float = 0.0

        # Typewriter state: _full is everything the model has produced so far
        # (the buffer); _shown is how many of its characters we have revealed (the
        # write-head position). The frame loop advances _shown toward len(_full).
        self._full: str = ""
        self._shown: int = 0
        self._rendered_text: str = ""       # what is currently shown (for dedupe)

        # Whether a turn is actively streaming.
        self._streaming = False

        self._lock = asyncio.Lock()
        self._typing_task: asyncio.Task | None = None
        # Drives the typewriter reveal + caret rotation for the whole turn.
        self._anim_task: asyncio.Task | None = None
        # ⏹ Stop control message (separate from the draft): id + the delayed-poster.
        self._control_id: int | None = None
        self._control_task: asyncio.Task | None = None
        self._closed = False

    # ------------------------------------------------------------------ utils

    def _kwargs(self) -> dict[str, Any]:
        """Common send kwargs; include message_thread_id only for real topics."""
        if self.thread_id is not None:
            return {"message_thread_id": self.thread_id}
        return {}

    def _render_chunks(self, body: str) -> list[str]:
        """Produce independently-balanced HTML chunks for the model text.

        CRITICAL: we split the RAW body on text boundaries FIRST, then run
        md_to_html on each chunk separately. Rendering before splitting would
        let split_message cut inside a <pre>/<code>/<b> tag, producing
        unbalanced HTML that Telegram rejects (and _safe() would then silently
        drop). Splitting raw text means every rendered chunk is self-contained.
        """
        body = body.strip()
        if not body:
            return ["…"]
        rendered: list[str] = []
        for raw in markup.split_markdown(body, limit=markup.SAFE_LIMIT):
            # render_within_limit guarantees each HTML piece fits Telegram's hard
            # 4096 ceiling (md_to_html escaping can expand a raw chunk past it).
            rendered.extend(markup.render_within_limit(raw))
        return rendered or ["…"]

    def _render_message_chunks(self, body: str) -> list[str]:
        """Like _render_chunks, but ISOLATES each fenced code block into its own
        message so a snippet is trivially copyable (long-press → Copy) even on
        clients with no per-block copy button. Prose between blocks is its own
        message; an oversized segment is still size-split (fences repaired).
        """
        body = body.strip()
        if not body:
            return ["…"]
        out: list[str] = []
        for seg in markup.segment_blocks(body):
            for raw in markup.split_markdown(seg, limit=markup.SAFE_LIMIT):
                # Guarantee every rendered chunk fits Telegram's hard 4096 ceiling
                # (raw sizing + HTML escaping can otherwise overflow + drop it).
                for html in markup.render_within_limit(raw):
                    # Hard-cutting a single over-long line inside a fence can yield
                    # a lone fence that renders to an empty <pre></pre> box; drop it.
                    if markup.is_empty_render(html):
                        continue
                    out.append(html)
        return out or ["…"]

    async def _safe(self, coro_factory) -> Any:
        """Run a Telegram coroutine, swallowing transient/no-op errors.

        On TelegramRetryAfter we honour the server-provided delay once and
        retry a single time; any further failure is swallowed so the stream
        keeps running.
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
            # "message is not modified", "message to edit not found", etc.
            return None
        except Exception:
            # Network blips and other transient errors must not crash the turn.
            return None

    # --------------------------------------------------------------- typing

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
                # Telegram keeps the typing indicator for ~5s.
                await asyncio.sleep(4.0)
        except asyncio.CancelledError:
            return
        except Exception:
            return

    def _stop_typing(self) -> None:
        if self._typing_task is not None:
            self._typing_task.cancel()
            self._typing_task = None

    # --------------------------------------------------------------- animation

    async def _animate_loop(self) -> None:
        """Frame loop that drives the live stream.

        update() only fills the buffer; this loop owns every send/edit. Each frame
        _tick() pushes the latest text — a draft update (DM) or a write-head edit
        (group). Re-checks the finalize flags UNDER the lock so it can never fire
        after finish() has finalized the message.
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
        """One frame: advance the reveal toward the buffer, then repaint."""
        if self.use_drafts:
            # The client animates the text growth for us, so we do not meter the
            # reveal — push the whole frontier and let Telegram do the typewriter.
            self._shown = len(self._full)
            await self._render_draft()
            return
        target = len(self._full)
        if self._shown < target:
            remaining = target - self._shown
            # Reveal at least _BASE_STEP chars (so it reads as writing), more when
            # a backlog builds so the reveal never lags the model by much.
            step = max(self.base_step, -(-remaining // _CATCHUP))  # ceil division
            self._shown = min(target, self._shown + step)
        # else: caught up — the caret spins in place (no new characters revealed).
        await self._render_frame()

    async def _render_draft(self) -> None:
        """Push the current text as a native message draft (DM streaming).

        Telegram animates the characters APPENDED between two drafts that share a
        draft_id — that is the real letter-by-letter typewriter, and it is far
        smoother than the ~1/sec write-head. We rely on it instead of metering the
        reveal ourselves, and by default we add NO trailing cursor (_DRAFT_CURSOR
        is ""): Telegram owns the frontier and absorbs a custom glyph, so it just
        adds noise. _DRAFT_CURSOR can be set to a steady block to force one back on.

        We stream ONLY the model's text here — NOT the tool-status block. The
        status lines grow and change as tools run, which would break the clean
        growing-prefix relationship between drafts and make Telegram snap the whole
        message in chunks instead of animating the new characters. (Status still
        appears in the final message via finish().) Drafts cap at 4096 chars, so
        for long output we render the frontier chunk (the tail). No real message is
        touched here — finish() posts the persisted message once the turn ends.
        """
        body = self._full[: self._shown].strip()
        if not body:
            return  # nothing yet — the empty "Thinking…" draft already shows
        # #172: stream the RAW markdown via sendRichMessageDraft, so the draft is
        # ALREADY FORMATTED as it generates (Durov's GIF) instead of plain text that
        # snaps to rich at the end. Split raw first so a fence cut at the tail stays
        # balanced; stream the FRONTIER (tail) chunk so a long stream tracks the
        # frontier (Telegram animates same-draft_id updates). On any failure (e.g. a
        # partial-markdown parse hiccup) we fall back to a plain HTML draft for that
        # frame so streaming never goes dark; the final finish() message is always
        # correct on every client.
        raw_chunks = markup.split_markdown(body, limit=markup.SAFE_LIMIT)
        frontier = raw_chunks[-1] if raw_chunks else body
        if frontier == self._rendered_text:
            return
        # #176→owner pref: stream the WHOLE reply as rich (code included → monospace
        # in the draft, matching the final rich message). On any failure fall back to a
        # plain HTML draft for that frame so streaming never goes dark.
        try:
            await self.bot(
                SendRichMessageDraft(
                    chat_id=self.chat_id,
                    draft_id=_DRAFT_ID,
                    rich_message={"markdown": frontier},
                )
            )
        except Exception:
            chunk = markup.md_to_html(frontier) or "…"
            await self._safe(
                lambda: self.bot.send_message_draft(
                    chat_id=self.chat_id, draft_id=_DRAFT_ID,
                    text=f"{chunk}{_DRAFT_CURSOR}", parse_mode="HTML",
                )
            )
        self._rendered_text = frontier
        self._last_edit = time.monotonic()

    async def _render_frame(self) -> None:
        """Paint full[:shown] into the placeholder (the write-head).

        Caret-free: the write-head just reveals progressively more text per edit.
        No-op when the rendered result equals what is already on screen. (Only the
        dormant non-DM/group path uses this; DM streams via native drafts.)
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

    # ------------------------------------------------------------- stop control

    async def _delayed_control(self) -> None:
        """After a short delay, post a separate STATIC ⏹ Stop message (DM only).

        Skipped if the turn already finished — so a quick reply never flickers a
        Stop button. The button's callback is `stop:<thread_id>`, handled in
        handlers and routed to SessionManager.stop (graceful interrupt). The
        message is a fixed label + button (no animation — the old braille spinner
        was removed because at ~1 edit/sec it just flickered); it is deleted by
        _remove_control()/cancel() when the turn ends.
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
        # Register the id immediately so _remove_control()/cancel() can delete it,
        # then re-check the turn didn't end while we were posting — otherwise a turn
        # that finished during the send would leave an orphaned control message
        # (#94 audit). Deleting an already-gone message is a harmless no-op.
        self._control_id = cid
        async with self._lock:
            if self._closed or not self._streaming:
                self._control_id = None
                with contextlib.suppress(Exception):
                    await self.bot.delete_message(self.chat_id, cid)
                return
        # Static control: no animation loop — the message stands (unedited) until
        # _remove_control()/cancel() deletes it when the turn ends.

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
        """Stop the background tasks without finalizing the message.

        Used on the cancel path (reset/shutdown) where finish() never runs: the
        worker is cancelled mid-turn, so we tear down the typing + animation loops
        to avoid orphaned tasks. The partially-revealed text stays on screen.
        """
        self._closed = True
        self._streaming = False
        self._stop_typing()
        self._stop_anim()
        # Tear down the Stop control message too (fire-and-forget: cancel() is sync
        # and runs on the worker's cancel path, so we can't await here).
        if self._control_task is not None:
            self._control_task.cancel()
            self._control_task = None
        if self._control_id is not None:
            cid = self._control_id
            self._control_id = None
            with contextlib.suppress(Exception):
                asyncio.create_task(self.bot.delete_message(self.chat_id, cid))

    # ----------------------------------------------------------------- API

    async def start(self, placeholder: str | None = None) -> None:
        """Begin the live stream and start the animation (and typing) loops.

        Draft mode (DM): show Telegram's native "Thinking…" placeholder by sending
        an empty draft — no real message yet — and stream via sendMessageDraft. If
        the draft probe fails (unsupported client / not a private chat), we fall
        back to the edit-based write-head for this turn. Write-head mode: send a
        real placeholder message and run the typing indicator alongside the reveal.
        """
        async with self._lock:
            self._start_time = time.monotonic()
            self._last_edit = 0.0
            self._streaming = True
            self._full = ""
            self._shown = 0
            self._closed = False

            if self.use_drafts:
                # Probe once: an empty draft shows Telegram's native "Thinking…".
                # ONLY a definitive BadRequest (drafts genuinely unsupported here,
                # e.g. not a private chat) drops us to the write-head. A transient
                # error (RetryAfter / network blip) keeps drafts ON — the animation
                # loop just retries — so a brief throttle never silently reverts a
                # DM to the chunky 1/sec write-head mid-conversation.
                try:
                    await self.bot.send_message_draft(
                        chat_id=self.chat_id, draft_id=_DRAFT_ID, text=""
                    )
                except TelegramBadRequest:
                    self.use_drafts = False
                except Exception:
                    pass

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
                # The draft itself signals activity, so typing only runs here.
                if self._typing_task is None:
                    self._typing_task = asyncio.create_task(self._typing_loop())

            if self._anim_task is None:
                self._anim_task = asyncio.create_task(self._animate_loop())

            # DM: a draft can't carry a Stop button, so schedule a separate
            # control message (posted only if the turn outlasts _CONTROL_DELAY).
            # #172: skipped for the /test demo (controllable=False) so a mid-draft
            # message arrival can't make the client re-render the draft from the top.
            if self.use_drafts and self.controllable and self._control_task is None:
                self._control_task = asyncio.create_task(self._delayed_control())

    async def update(self, full_text: str) -> None:
        """Buffer the latest full text for the animator to reveal.

        We never edit here — the frame loop owns every edit — so a big token
        burst lands in the buffer and is revealed progressively rather than
        dumped in one chunky jump. Keep the longest snapshot seen.
        """
        async with self._lock:
            if len(full_text) >= len(self._full):
                self._full = full_text

    async def finish(self, full_text: str, footer: str = "", notify: bool = True) -> None:
        """Final flush for the turn: stop the loops and commit the persisted text.

        notify controls whether the FIRST committed message pings the user — True
        for the final answer (it is ready), False for an intermediate segment.
        """
        async with self._lock:
            # Reveal everything and stop the loops so neither can fire after we
            # finalize (the animator also re-checks these flags under the lock).
            self._streaming = False
            self._full = full_text
            self._shown = len(full_text)
            self._stop_typing()
            self._stop_anim()
            self._closed = True
            await self._commit(full_text, footer, notify)
            self._last_edit = time.monotonic()
        # Outside the lock: tear down the Stop control message for this turn.
        await self._remove_control()

    async def segment_break(self) -> None:
        """Commit the current segment as its own message and reset for the next.

        Used in code mode between tool calls: each burst of model text becomes a
        separate, visible message (silent — it is intermediate) instead of silently
        updating the previous one. Streaming stays live, so the next segment starts
        a fresh draft / placeholder. No-op when nothing has been produced yet.
        """
        async with self._lock:
            text = self._full.strip()
            if not text:
                return
            await self._commit(text, footer="", notify=False)
            await self._begin_next_segment()

    async def flush_segment(self, text: str) -> None:
        """Commit a caller-provided PREFIX as its own message(s) and reset for the
        next segment, keeping the stream live.

        Like segment_break, but commits the given text instead of the whole
        buffer. Used for live code-block splitting (#93): when a fenced block has
        fully closed mid-stream, sessions hands us the prose+block prefix so the
        snippet is posted (and copyable) immediately while the tail keeps
        streaming. No-op for blank text. The caller resets its own running text to
        the remainder and update()s us with it.
        """
        async with self._lock:
            if not text or not text.strip():
                return
            await self._commit(text, footer="", notify=False)
            await self._begin_next_segment()

    async def _begin_next_segment(self) -> None:
        """Reset the buffer + draft/placeholder so the next segment is a brand-new
        message. Caller holds the lock. Shared by segment_break and flush_segment.
        """
        self._full = ""
        self._shown = 0
        self._rendered_text = ""
        self.message_id = None
        if self.use_drafts:
            # Reset the draft to Telegram's native "Thinking…" for the next
            # segment; the committed message stands permanently above it.
            with contextlib.suppress(Exception):
                await self.bot.send_message_draft(
                    chat_id=self.chat_id, draft_id=_DRAFT_ID, text=""
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
        """Split the final answer into ordered sendables — ``('text', html)`` chunks and
        ``('rich', RichTable)`` native tables (#164). EVERY markdown table is sent as a
        NATIVE Telegram table (even in a code-containing reply, #172) — so a code reply
        still gets a proper classic code block in its text chunks AND a native table;
        _send_rich falls back to a <pre> grid only if that API call fails."""
        out: list = []
        # #164: route every table through the native rich-table path.
        for item in markup.split_rich_tables(full_text):
            if isinstance(item, markup.RichTable):
                out.append(("rich", item))
                continue
            for chunk in render_fn(item):
                if chunk and not markup.is_empty_render(chunk):
                    out.append(("text", chunk))
        return out

        # # was (#162) — wide tables as PNG images / narrow as <pre> grids. Replaced
        # # for #164 (native Telegram tables); kept commented for quick revert.
        # out: list = []
        # for item in markup.split_image_tables(full_text):
        #     if isinstance(item, markup.TableImage):
        #         try:
        #             out.append(("photo", table_image.render_table_png(item.rows)))
        #             continue
        #         except Exception:
        #             esc = [[markup.escape_html(c) for c in r] for r in item.rows]
        #             out.append(("text", markup._render_table_pre(esc)))
        #             continue
        #     for chunk in render_fn(item):
        #         if chunk and not markup.is_empty_render(chunk):
        #             out.append(("text", chunk))
        # return out

    async def _send_rich(self, table, silent: bool) -> None:
        """Send one markdown table as a NATIVE Telegram table via Bot API 10.1
        sendRichMessage (#164). The method is new, so on ANY failure we fall back to
        the old monospace <pre> grid — a table is never lost, just less pretty."""
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
        # Fallback: the legacy monospace grid (cells emphasis-stripped + escaped).
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

    async def _commit_rich_markdown(self, full_text: str, footer: str, silent: bool) -> bool:
        """#169/#172: post the ENTIRE reply as ONE native rich message (the markdown
        field): Telegram renders headings / lists / tables / quotes natively, with NO
        splitting. Returns True on success; False (→ classic fallback) on any error.

        #172/#174: in a rich message a ```fence``` renders as plain MONOSPACE (no
        language label, no copy) — RichBlockPreformatted is accepted by the API but not
        styled by the current client. Code is sent through this path anyway, keeping one
        consistent rich message instead of splitting; when the client styles
        RichBlockPreformatted, code renders as a full code block with NO change here.
        (The split-by-segment alternative lives in _commit_mixed.)"""
        md = full_text.strip() or "…"
        if footer:
            # Italicize each footer line separately — markdown italic can't span a
            # newline, and the usage footer is 2 lines (5h / 7d) (#169).
            foot = "\n".join(f"_{ln}_" for ln in footer.splitlines() if ln.strip())
            md = f"{md}\n\n{foot}"
        try:
            await self.bot(
                SendRichMessage(
                    chat_id=self.chat_id,
                    rich_message={"markdown": md},
                    disable_notification=silent,
                    **self._kwargs(),
                )
            )
        except Exception:
            logger.warning("#169 sendRichMessage(markdown) failed; legacy fallback", exc_info=True)
            return False
        # The rich message is a fresh bubble, so clear the streaming write-head
        # placeholder if there was one (DM drafts have none — they self-expire).
        if self.message_id is not None:
            with contextlib.suppress(Exception):
                await self.bot.delete_message(self.chat_id, self.message_id)
            self.message_id = None
        self._rendered_text = md
        return True

    async def _commit_mixed(self, full_text: str, footer: str, silent_first: bool) -> None:
        """#176: a reply that contains code → split by code block. Non-code segments
        (prose, tables, lists, headings) go as RICH messages (consistent font + native
        tables); each code block goes CLASSIC (a real code block with language + copy).
        The footer rides the last segment (or its own message if that segment is code).
        Each rich piece falls back to classic HTML if its send fails."""
        segs = [(k, s) for (k, s) in markup.split_code_blocks(full_text) if s.strip()]
        if not segs:
            segs = [("text", "…")]
        # Segments are fresh messages → drop the streaming write-head placeholder
        # (DM drafts have none; they self-expire).
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
                md = seg.strip()
                if want_footer:
                    foot = "\n".join(f"_{ln}_" for ln in footer.splitlines() if ln.strip())
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
                    seg_html = markup.md_to_html(seg)
                    await self._safe(
                        lambda h=seg_html, s=silent: self.bot.send_message(
                            chat_id=self.chat_id, text=h, parse_mode="HTML",
                            disable_notification=s, link_preview_options=_NO_PREVIEW,
                            **self._kwargs(),
                        )
                    )
            if want_footer:   # last segment was code → footer on its own line
                await self._safe(
                    lambda: self.bot.send_message(
                        chat_id=self.chat_id,
                        text=f"<i>{markup.escape_html(footer)}</i>",
                        parse_mode="HTML", disable_notification=True,
                        link_preview_options=_NO_PREVIEW, **self._kwargs(),
                    )
                )
        self._rendered_text = full_text

    async def _commit(self, full_text: str, footer: str, notify: bool) -> None:
        """Render full_text and post it as permanent message(s). Caller holds the
        lock and owns the streaming flags. Links never preview; only the FIRST
        message may ping (notify), the rest are silent.

        #169: the whole reply now goes as ONE rich-markdown message (see
        _commit_rich_markdown); the chunk/split/table-bubble logic below is the
        FALLBACK only. Very long → a .md document instead.
        """
        silent_first = not notify
        footer_line = f"\n\n<i>{markup.escape_html(footer)}</i>" if footer else ""

        # #176: send the WHOLE reply as ONE rich message, code included. In rich a
        # ```fence``` renders as plain MONOSPACE (no language / copy — RichBlockPreformatted
        # is accepted but not styled by the current client, #174); a single consistent
        # rich message is used rather than SPLITTING a code reply into rich+classic
        # bubbles, and when Telegram styles code this needs no change. The split-by-
        # segment path (_commit_mixed / markup.split_code_blocks) is kept, un-called, to
        # flip back if the trade-off is revisited.
        if await self._commit_rich_markdown(full_text, footer, silent_first):
            return
        # # was (#176): split a code reply → rich prose/tables + classic code block:
        # if markup.has_code_block(full_text):
        #     await self._commit_mixed(full_text, footer, silent_first)
        #     return

        # Very long output (fallback): deliver as a document so we do not spam chunks.
        if markup.should_send_as_file(full_text):
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
            document = markup.as_document(full_text, "response.md")
            await self._safe(
                lambda: self.bot.send_document(
                    chat_id=self.chat_id,
                    document=document,
                    disable_notification=silent_first,
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
            return

        # ---- legacy fallback (pre-#169): md_to_html chunks + native-table bubbles +
        #      char-limit splitting. Kept (not deleted) so a sendRichMessage failure
        #      never loses a reply, and for a quick revert. ----
        # #162: build ordered sendables — HTML text chunks + wide-table photos. A table
        # too wide for a phone can't be a clean <pre> grid (it wraps / runs off the
        # bubble) and Telegram has no native table, so it is drawn as a PNG and sent as
        # its own photo; narrow tables stay <pre> grids inside the text chunks. Per the
        # /codesplit toggle the text path isolates fenced code blocks (default — easy
        # mobile copy) or size-splits inline; empty code boxes are dropped, and one "…"
        # chunk is kept so an empty turn still shows something.
        # Fallback only (a NO-code reply whose rich send failed): classic md_to_html
        # chunks + native-table bubbles. Code-containing replies never reach here —
        # they are handled by _commit_mixed (rich prose/tables + classic code).
        render_fn = self._render_message_chunks if self._split_code_messages else self._render_chunks
        sendables = self._build_sendables(full_text, render_fn) or [("text", "…")]

        # Append the footer to the last TEXT sendable when it fits, else send it alone.
        footer_as_message = bool(footer_line)
        if footer_line:
            for idx in range(len(sendables) - 1, -1, -1):
                kind, payload = sendables[idx]
                if kind == "text" and len(payload) + len(footer_line) <= markup.HARD_LIMIT:
                    sendables[idx] = ("text", f"{payload}{footer_line}")
                    footer_as_message = False
                    break

        # Send in order. The FIRST text sendable replaces the streaming placeholder
        # (write-head/group); photos and the rest are sent fresh. Only the first send
        # may ping the user; the rest are silent intermediates.
        placeholder_used = False
        first_send = True
        for kind, payload in sendables:
            silent = silent_first if first_send else True
            if kind == "rich":
                # #164: a native Telegram table — its own bubble (like the old photo),
                # so it does not consume the streaming placeholder.
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
                await self._safe(
                    lambda t=payload: self.bot.edit_message_text(
                        text=t,
                        chat_id=self.chat_id,
                        message_id=self.message_id,
                        parse_mode="HTML",
                        link_preview_options=_NO_PREVIEW,
                    )
                )
                self._rendered_text = payload
                placeholder_used = True
            else:
                await self._safe(
                    lambda t=payload, s=silent: self.bot.send_message(
                        chat_id=self.chat_id,
                        text=t,
                        parse_mode="HTML",
                        disable_notification=s,
                        link_preview_options=_NO_PREVIEW,
                        **self._kwargs(),
                    )
                )
                self._rendered_text = payload
            first_send = False

        # A group placeholder left unconsumed (a photo-only answer) → don't orphan its
        # "typing…" text; replace it with a thin marker.
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
