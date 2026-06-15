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
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import db
import i18n
import markup  # noqa: F401  (kept for symmetry / future formatting helpers)
import usage
from engine import ClaudeSession
from streamer import Streamer, resolve_speed
from permissions import PermissionGate

# The Anthropic prompt cache stays warm for ~5 minutes after the last request.
_CACHE_WINDOW_SECONDS = 300.0


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
    # Pro-command options the live session was built for (#23); a change rebuilds.
    effort: str | None = None
    max_turns: int | None = None
    add_dirs: tuple = ()
    fork: bool = False

    # Queue items are (qid, text, attachments) tuples — qid is a per-thread
    # monotonic id (so a single queued follow-up can be cancelled by id, #13);
    # attachments is None or a list of Anthropic content-block dicts.
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    next_qid: int = 1
    worker: asyncio.Task | None = None
    streamer: Streamer | None = None
    last_activity: float = field(default_factory=time.monotonic)
    rate: object | None = None  # latest RateLimitInfo seen for this thread
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # Per-thread display flags toggled via commands; default to today's
    # behavior (live streaming). last_prompt holds the most recent submitted
    # prompt for this thread (used by /retry).
    stream_enabled: bool = True
    # Most recent (text, attachments) submitted for this thread (used by /retry).
    last_prompt: tuple | None = None


def _send_thread_id(thread_id: int) -> int | None:
    """Map a session key to a Telegram message_thread_id.

    Only POSITIVE keys are real forum topics. General (0) and negative DM-session
    keys both map to None (no message_thread_id — they post to the bare chat).
    """
    return thread_id if thread_id > 0 else None


class SessionManager:
    """Owns one isolated worker pipeline per forum topic."""

    def __init__(self, bot, settings, gate: PermissionGate) -> None:
        self.bot = bot
        self.settings = settings
        self.gate = gate
        self._records: dict[int, _ThreadRecord] = {}

        # Account-wide subscription rate-limit windows, keyed by rate_limit_type.
        self.rate_by_type: dict[str, object] = {}
        # Usage display: one of "off", "footer", "pinned", "both".
        self.usage_mode: str = "footer"
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

    # ------------------------------------------------------------------ records

    def _record(self, thread_id: int) -> _ThreadRecord:
        """Return (creating if needed) the per-thread record. Never shared."""
        rec = self._records.get(thread_id)
        if rec is None:
            rec = _ThreadRecord()
            self._records[thread_id] = rec
        return rec

    def _default_cwd(self, thread_id: int) -> str:
        """Per-thread working directory: BASE_WORKDIR/<thread_id>."""
        return str(Path(self.settings.base_workdir) / str(thread_id))

    # --------------------------------------------------------------- session mgmt

    def _build_session(self, state: db.ThreadState) -> ClaudeSession:
        """Construct a fresh ClaudeSession for a thread from its stored state.

        Code mode gets the per-thread permission callback and resumes the stored
        code_session_id (so a rebuilt client continues the prior session). Chat
        mode runs tool-free and does not resume a code session.
        """
        send_tid = _send_thread_id(state.thread_id)
        if state.mode == "code":
            # Pass send_tid (where to post) AND the unique session key (for gate
            # bookkeeping/cancellation that must not collide across DM/General).
            can_use_tool = self.gate.make_callback(
                state.chat_id, send_tid, state.thread_id, state.permission_mode
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
            model=state.model,
            cwd=state.cwd,
            can_use_tool=can_use_tool,
            resume_session_id=resume_id,
            permission_mode=state.permission_mode,
            big_memory=state.big_memory,
            effort=state.effort,
            max_turns=state.max_turns,
            add_dirs=state.add_dirs,
            fork=state.fork_pending,
            sandbox=self.settings.sandbox_code and not state.no_sandbox,
            sandbox_uid=self.settings.sandbox_uid,
            sandbox_allow_exec=self.settings.sandbox_allow_exec,
        )

    async def _get_session(
        self, rec: _ThreadRecord, state: db.ThreadState
    ) -> ClaudeSession:
        """Return the live session, rebuilding it if config drifted or absent.

        A rebuild aclose()s the old client first so we never leak a connection,
        and never share an SDK client across distinct configs.
        """
        needs_rebuild = (
            rec.session is None
            or rec.mode != state.mode
            or rec.model != state.model
            or rec.cwd != state.cwd
            or rec.permission_mode != state.permission_mode
            or rec.big_memory != state.big_memory
            or rec.effort != state.effort
            or rec.max_turns != state.max_turns
            or rec.add_dirs != tuple(state.add_dirs)
            or rec.fork != state.fork_pending
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
            if rec.session is not None:
                old = rec.session
                rec.session = None
                with contextlib.suppress(Exception):
                    await old.aclose()
            rec.session = self._build_session(state)
            rec.mode = state.mode
            rec.model = state.model
            rec.cwd = state.cwd
            rec.permission_mode = state.permission_mode
            rec.big_memory = state.big_memory
            rec.effort = state.effort
            rec.max_turns = state.max_turns
            rec.add_dirs = tuple(state.add_dirs)
            rec.fork = state.fork_pending
            # Restore the persisted /stream preference (survives restart).
            rec.stream_enabled = state.stream_enabled
        return rec.session

    # ------------------------------------------------------------------ entry

    async def handle_text(
        self,
        chat_id: int,
        thread_id: int,
        text: str,
        attachments: list | None = None,
    ) -> None:
        """Queue a prompt (optionally with attachments) and ensure the worker runs.

        thread_id is the real storage key (0 for General). attachments, when given,
        is a list of Anthropic content-block dicts (image/document) sent with the
        turn. The message is always enqueued; if a run is in progress it executes
        next in the SAME session (task chaining), else the worker starts.
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
                break

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
                use_drafts = thread_id < 0
                streamer = Streamer(
                    self.bot,
                    chat_id,
                    send_tid,
                    frame_interval=interval,
                    base_step=step,
                    use_drafts=use_drafts,
                )
                rec.streamer = streamer
                try:
                    await self._run_one(
                        rec, thread_id, prompt, attachments, streamer
                    )
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
                elif kind == "tool":
                    # Code mode: commit the text produced before this tool as its
                    # own message so each burst is visible, then stream the next
                    # burst fresh. (Chat mode has no tools, so this never fires.)
                    if stream and rec.mode == "code" and running_text.strip():
                        with contextlib.suppress(Exception):
                            await streamer.segment_break()
                        running_text = ""
                        segmented = True
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
                elif kind == "result":
                    had_result = True
                    # When we have already posted segments, the only NEW text is the
                    # current (last) burst in running_text — do NOT reuse ev.text,
                    # which for a multi-tool turn can repeat earlier segments.
                    final_text = running_text if segmented else (ev.text or running_text)
                    # Persist usage + the resumable session id for this mode.
                    with contextlib.suppress(Exception):
                        await db.add_usage(thread_id, ev.usage, ev.cost)
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
        footer = self.usage_footer(i18n.cached_lang(streamer.chat_id))
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

    def usage_footer(self, lang: str = "en") -> str:
        """Footer line appended to a finished reply when footer display is on."""
        if self.usage_mode in {"footer", "both"}:
            return usage.footer_line(self.rate_by_type, lang)
        return ""

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

    async def _notify(self, chat_id: int, thread_id: int | None, text: str) -> None:
        """Send a plain notice into a topic, swallowing transient failures."""
        kwargs: dict = {}
        if thread_id is not None:
            kwargs["message_thread_id"] = thread_id
        with contextlib.suppress(Exception):
            await self.bot.send_message(chat_id, text, **kwargs)

    async def aclose(self) -> None:
        """Best-effort shutdown: forcefully cancel workers and disconnect clients.

        Unlike /stop (graceful interrupt) we cancel hard here — the process is
        exiting. We do NOT clear the DB (no db.reset_thread), so code-mode topics
        keep their persisted session id and resume after a restart.
        """
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


