"""Integration tests for sessions._run_one live code-block splitting (#93).

Guards the audit-found double-post regression: with include_partial_messages the
engine streams the text as deltas AND then emits a terminal CUMULATIVE text_full
snapshot (engine.py). Once a fenced block has been live-split off the running
text, that snapshot must NOT resurrect and re-flush it as a duplicate message.

Async tests wrap asyncio.run (no pytest-asyncio), matching the suite convention.
"""
import asyncio
import contextlib
import time
from types import SimpleNamespace

from app.storage import db
from app.storage import archive
from app import i18n
from app.core import sessions


class _FakeStreamer:
    """Records the commit calls _run_one makes, without touching Telegram."""

    def __init__(self):
        self.chat_id = 12345
        self.thread_id = None
        self.message_id = 999      # #279: id of the finished message (keypad tracking)
        self.flushed = []          # flush_segment(text) payloads (live splits)
        self.segment_breaks = 0    # segment_break() count (tool boundaries)
        self.finished_with = None  # finish(full_text) payload
        self.cancelled = False
        self.reasoning = []        # add_reasoning(delta) payloads
        self.phases = []           # set_phase(label) payloads (#262 tool phase)
        self.web_sources = []      # #318: add_web_source((kind, value)) payloads

    async def start(self, placeholder=None):
        pass

    async def update(self, full_text):
        pass

    async def segment_break(self):
        self.segment_breaks += 1

    async def flush_segment(self, text):
        self.flushed.append(text)

    async def finish(self, full_text, footer="", notify=True, reply_markup=None):
        self.finished_with = full_text

    def cancel(self):
        self.cancelled = True

    def add_reasoning(self, delta):
        self.reasoning.append(delta)

    def set_phase(self, label):
        self.phases.append(label)

    def set_tool_phase(self, tool_name, tool_input):
        # #294: mirror the real streamer — build the localized label (en in tests).
        from app.telegram import streamer as _st
        self.phases.append(_st.tool_phase_label(tool_name, tool_input, "en"))

    async def add_web_source(self, kind, value, lang="en"):
        self.web_sources.append((kind, value))


class _FakeSession:
    def __init__(self, events):
        self._events = events

    async def run(self, prompt, attachments=None):
        for ev in self._events:
            yield ev


def _ev(kind, text="", **kw):
    return SimpleNamespace(
        kind=kind, text=text,
        usage=kw.get("usage"), cost=kw.get("cost"),
        session_id=kw.get("session_id"), rate=kw.get("rate"),
        error_key=kw.get("error_key"), error_detail=kw.get("error_detail"),
        tool_name=kw.get("tool_name", ""), tool_input=kw.get("tool_input"),
    )


def _make(monkeypatch, events, mode="code"):
    async def _noop(*a, **k):
        return None
    for name in ("log_message", "add_usage", "set_fork_pending"):
        monkeypatch.setattr(db, name, _noop)
    # #324: record session-id persists so the early-persist test can assert them.
    saved_sessions: list = []

    async def _save_chat(tid, sid):
        saved_sessions.append(("chat", sid))

    async def _save_code(tid, sid):
        saved_sessions.append(("code", sid))
    monkeypatch.setattr(db, "set_chat_session", _save_chat)
    monkeypatch.setattr(db, "set_code_session", _save_code)
    sm = sessions.SessionManager(
        bot=SimpleNamespace(), settings=SimpleNamespace(), gate=SimpleNamespace()
    )
    monkeypatch.setattr(sm, "usage_footer", lambda lang, chat_id=None: "")
    rec = sessions._ThreadRecord(
        session=_FakeSession(events), mode=mode, stream_enabled=True
    )
    streamer = _FakeStreamer()
    streamer.saved_sessions = saved_sessions   # #324: expose persisted session ids
    asyncio.run(sm._run_one(rec, -1, "prompt", None, streamer))
    return streamer


def test_live_split_no_double_post_on_cumulative_text_full(monkeypatch):
    full = "Here is code:\n```py\nx = 1\n```\nmore"
    events = [
        _ev("text_delta", "Here is code:\n"),
        _ev("text_delta", "```py\n"),
        _ev("text_delta", "x = 1\n"),
        _ev("text_delta", "```\n"),   # closes the block -> exactly ONE live flush
        _ev("text_delta", "more"),
        _ev("text_full", full),       # cumulative snapshot -> must NOT re-flush
        _ev("result", full, usage={}, session_id="s1"),
    ]
    s = _make(monkeypatch, events)
    assert len(s.flushed) == 1, s.flushed          # not 2 (the regression)
    assert "x = 1" in s.flushed[0]
    assert s.finished_with == "more"               # only the trailing remainder


def test_thinking_after_text_splits_into_new_bubble(monkeypatch):
    # #259: model writes some answer text, then reasons again (interleaved thinking, no
    # tool). The prior text is finalized as its own bubble (segment_break) and a fresh one
    # opens; the trailing text after the reasoning becomes the final message.
    events = [
        _ev("text_delta", "First part. "),
        _ev("thinking_delta", "let me reconsider"),
        _ev("text_delta", "Second part."),
        _ev("result", "", usage={}, session_id="s1"),
    ]
    s = _make(monkeypatch, events, mode="chat")
    assert s.segment_breaks == 1                    # split exactly once, on the first delta
    assert s.reasoning == ["let me reconsider"]
    assert s.finished_with == "Second part."        # only the post-reasoning burst


def test_web_tool_phase_shown_in_chat(monkeypatch):
    # #262: a chat-mode web search shows a live "🌐 Searching the web…" phase (previously
    # the tool phase was code-only, so chat looked like a bare "thinking").
    events = [
        _ev("tool", tool_name="WebSearch", tool_input={"query": "weather"}),
        _ev("text_delta", "It's sunny."),
        _ev("result", "It's sunny.", usage={}, session_id="s1"),
    ]
    s = _make(monkeypatch, events, mode="chat")
    assert any("web" in p.lower() for p in s.phases), s.phases
    assert s.segment_breaks == 0          # #320: no text before the tool here → no split
    assert s.finished_with == "It's sunny."


def test_thinking_without_prior_text_does_not_split(monkeypatch):
    # A thinking_delta with no answer text yet must NOT break a (empty) segment.
    events = [
        _ev("thinking_delta", "planning"),
        _ev("text_delta", "Only answer."),
        _ev("result", "", usage={}, session_id="s1"),
    ]
    s = _make(monkeypatch, events, mode="chat")
    assert s.segment_breaks == 0
    assert s.finished_with == "Only answer."


def test_repeated_thinking_after_text_splits_each_time(monkeypatch):
    # #259/#317: think → text → think → text → think → text. EACH thinking phase that
    # follows answer text finalizes the prior text as its own bubble and re-opens a fresh
    # one (re-showing the <tg-thinking> block), so a multi-step interleave renders as
    # separate messages — not one blob, and no second/third thinking phase is lost.
    events = [
        _ev("thinking_delta", "t1"),       # before any text — no split
        _ev("text_delta", "A. "),
        _ev("thinking_delta", "t2"),       # after text — split #1
        _ev("text_delta", "B. "),
        _ev("thinking_delta", "t3"),       # after text — split #2
        _ev("text_delta", "C."),
        _ev("result", "", usage={}, session_id="s1"),
    ]
    s = _make(monkeypatch, events, mode="chat")
    assert s.segment_breaks == 2                       # one split per think-after-text
    assert s.reasoning == ["t1", "t2", "t3"]           # every thinking phase captured
    assert s.finished_with == "C."                     # only the final post-reasoning burst


# #321: web-search Sources card disabled (call sites commented) — this wiring test is parked
# with it; re-enable together. was:
# def test_web_tools_feed_sources_card(monkeypatch):
#     events = [
#         _ev("tool", tool_name="WebSearch", tool_input={"query": "weather kyiv"}),
#         _ev("tool", tool_name="WebFetch", tool_input={"url": "https://example.com/a"}),
#         _ev("text_delta", "Done."),
#         _ev("result", "Done.", usage={}, session_id="s1"),
#     ]
#     s = _make(monkeypatch, events, mode="chat")
#     assert ("search", "weather kyiv") in s.web_sources
#     assert ("fetch", "https://example.com/a") in s.web_sources


def test_tool_start_sets_phase_without_split_or_source(monkeypatch):
    # #319: a tool_start event (a tool BEGINNING — e.g. a slow server-side WebSearch) surfaces
    # the live phase immediately, but adds NO source and splits NO bubble — those wait for the
    # assembled `tool` event after the call returns.
    events = [
        _ev("tool_start", tool_name="WebSearch", tool_input={}),
        _ev("text_delta", "Answer."),
        _ev("result", "Answer.", usage={}, session_id="s1"),
    ]
    s = _make(monkeypatch, events, mode="chat")
    assert any("web" in p.lower() for p in s.phases), s.phases   # phase shown DURING the call
    assert s.web_sources == []                                   # no source yet (input empty)
    assert s.segment_breaks == 0
    assert s.finished_with == "Answer."


def test_fair_admission_round_robin_by_user():
    # #326: when slots are full, waiting turns are admitted ROUND-ROBIN by user — so user A's
    # burst of sessions can't starve user B. With 1 slot held and the wait-queue [A2, A3, B1]
    # (A bursts first), fair order serves A2, then B1 (jumps ahead of A3), then A3 — NOT the
    # plain-FIFO A2, A3, B1 that would make B wait behind A's whole burst.
    gate = sessions.FairAdmission(slots=1)
    order = []

    async def scenario():
        await gate.acquire("holder")          # the only slot is taken

        async def worker(key, tag):
            await gate.acquire(key)
            order.append(tag)
            gate.release()

        tasks = [asyncio.create_task(worker("A", "A2")),
                 asyncio.create_task(worker("A", "A3")),
                 asyncio.create_task(worker("B", "B1"))]
        await asyncio.sleep(0)                 # let all three block in the wait-queue
        gate.release()                         # holder done → cascade admits round-robin
        await asyncio.gather(*tasks)

    asyncio.run(scenario())
    assert order == ["A2", "B1", "A3"], order
    assert gate.active == 0                    # everything released — no leaked slot


def test_fair_admission_cancel_waiter_no_leak():
    # #326: a waiter cancelled while queued is removed cleanly and never leaks its slot.
    gate = sessions.FairAdmission(slots=1)

    async def scenario():
        await gate.acquire("A")                # full
        t = asyncio.create_task(gate.acquire("B"))
        await asyncio.sleep(0)                  # B blocks in the queue
        t.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await t
        gate.release()                         # holder done; B is gone → the slot must free
        assert gate.active == 0
        await gate.acquire("C")                # the gate still works after a cancel
        assert gate.active == 1
        gate.release()
        assert gate.active == 0

    asyncio.run(scenario())


def test_drain_waits_for_active_turns_then_returns():
    # #325: drain() blocks until in-flight turns finish (the idle event), bounded by timeout —
    # so a graceful restart lets the active turn complete instead of killing it.
    sm = sessions.SessionManager(
        bot=SimpleNamespace(), settings=SimpleNamespace(), gate=SimpleNamespace()
    )

    async def scenario():
        sm._active_turns = 1
        sm._idle_event.clear()
        assert await sm.drain(timeout=0.05) is False   # a turn is active → times out
        assert sm._draining is True                    # …and draining is latched on
        sm._active_turns = 0
        sm._idle_event.set()
        assert await sm.drain(timeout=0.05) is True     # turn finished → returns immediately
    asyncio.run(scenario())


def test_session_id_persisted_early_not_only_at_result(monkeypatch):
    # #324: the engine reports the session id up-front (the init message → a "session" event)
    # and the consumer persists it IMMEDIATELY — so a turn killed mid-flight (a restart/crash
    # before the terminal result) still leaves a resumable id. (Incident: a service restart
    # killed an SVG turn before its result; the id was never saved; the next message lost all
    # context and started a fresh "новая сессия".)
    events = [
        _ev("session", session_id="sid-1"),
        _ev("text_delta", "Drawing the SVG…"),
        _ev("result", "Done.", usage={}, session_id="sid-1"),
    ]
    s = _make(monkeypatch, events, mode="chat")
    assert s.saved_sessions[0] == ("chat", "sid-1")    # persisted by the EARLY session event…
    assert s.saved_sessions[-1] == ("chat", "sid-1")   # …and again at the terminal result


def test_chat_text_before_tool_is_kept_as_its_own_bubble(monkeypatch):
    # #320: in CHAT, when the model writes text, THEN runs a web search, THEN answers (it
    # commented before searching), the pre-tool text is committed as its OWN bubble
    # (segment_break) instead of being shown and then clobbered by the final answer. Mirrors
    # the real "Уточните…/А пока поищу… → [search] → Вот обзор…" transcript that looked janky.
    events = [
        _ev("text_delta", "Let me look that up. Meanwhile, searching… "),
        _ev("tool", tool_name="WebSearch", tool_input={"query": "news"}),
        _ev("text_delta", "Here is the overview."),
        _ev("result", "Here is the overview.", usage={}, session_id="s1"),
    ]
    s = _make(monkeypatch, events, mode="chat")
    assert s.segment_breaks == 1                          # pre-tool text kept as a bubble
    assert s.finished_with == "Here is the overview."     # final = the post-tool answer only


# --- #260: adopt Claude Code's transcript ai-title as the session name --------- #

def _write_transcript(tmp_path, sid, lines):
    """Lay out a session transcript the way the jail does: <root>/work is the cwd and
    its ai-title file lives at <root>/state/<encoded-cwd>/<sid>.jsonl."""
    import json as _json
    root = tmp_path / "sess"
    cwd = root / "work"
    cwd.mkdir(parents=True)
    # #335: encode the cwd EXACTLY as claude writes it on disk (and as _read_ai_title now
    # reads it) — via the shared archive helper (every non-alnum → '-'), NOT a plain
    # '/'→'-' (which diverges for a tmp_path containing '_'/'.' — the #335 bug this catches).
    tdir = archive.live_transcript_dir(str(cwd))
    tdir.mkdir(parents=True)
    (tdir / f"{sid}.jsonl").write_text(
        "\n".join(_json.dumps(o, ensure_ascii=False) for o in lines) + "\n",
        encoding="utf-8",
    )
    return str(cwd)


def _u(text):
    """#345: a transcript ``user`` line in the real message.content shape."""
    return {"type": "user", "message": {"role": "user", "content": text}}


def _a(text):
    """#345: a transcript ``assistant`` line (never a name source — here for realism)."""
    return {"type": "assistant", "message": {"role": "assistant", "content": text}}


def test_read_ai_title_returns_last_and_caps(tmp_path):
    cwd = _write_transcript(tmp_path, "s1", [
        {"type": "user", "text": "hi"},
        {"type": "ai-title", "aiTitle": "First guess", "sessionId": "s1"},
        {"type": "assistant", "text": "x"},
        {"type": "ai-title", "aiTitle": "Refined title", "sessionId": "s1"},
    ])
    assert sessions._read_session_title(cwd, "s1")[0] == "Refined title"  # the LAST one
    # length cap
    long = "z" * 200
    cwd2 = _write_transcript(tmp_path / "b", "s1", [
        {"type": "ai-title", "aiTitle": long, "sessionId": "s1"},
    ])
    assert sessions._read_session_title(cwd2, "s1")[0] == long[:sessions._AI_TITLE_MAX]


def test_read_ai_title_missing_returns_none(tmp_path):
    assert sessions._read_session_title(None, "s1")[0] is None
    assert sessions._read_session_title("/nope/work", None)[0] is None
    cwd = _write_transcript(tmp_path, "s1", [{"type": "user", "text": "no title"}])
    assert sessions._read_session_title(cwd, "s1")[0] is None  # no ai-title line


def test_auto_name_adopts_title_on_turn_end(monkeypatch, tmp_path):
    # End-to-end: a finished turn reads the transcript ai-title and renames (auto).
    cwd = _write_transcript(tmp_path, "s1", [
        {"type": "ai-title", "aiTitle": "Fix the parser", "sessionId": "s1"},
    ])
    calls = []
    async def _capture(thread_id, name, *, manual=True):
        calls.append((thread_id, name, manual))
    monkeypatch.setattr(db, "set_session_name", _capture)

    async def _noop(*a, **k):
        return None
    for name in ("log_message", "add_usage", "set_code_session"):
        monkeypatch.setattr(db, name, _noop)
    sm = sessions.SessionManager(
        bot=SimpleNamespace(), settings=SimpleNamespace(), gate=SimpleNamespace()
    )
    monkeypatch.setattr(sm, "usage_footer", lambda lang, chat_id=None: "")
    rec = sessions._ThreadRecord(
        session=_FakeSession([_ev("result", "done", usage={}, session_id="s1")]),
        mode="code", stream_enabled=True, cwd=cwd, name=None, name_auto=True,
    )
    asyncio.run(sm._run_one(rec, -1, "prompt", None, _FakeStreamer()))
    assert calls == [(-1, "Fix the parser", False)]   # auto rename, manual=False
    assert rec.name == "Fix the parser"               # in-memory kept fresh


def test_auto_name_skipped_when_pinned(monkeypatch, tmp_path):
    # name_auto False (user pinned via /rename) → the namer never calls the DB.
    cwd = _write_transcript(tmp_path, "s1", [
        {"type": "ai-title", "aiTitle": "Some title", "sessionId": "s1"},
    ])
    calls = []
    async def _capture(*a, **k):
        calls.append((a, k))
    monkeypatch.setattr(db, "set_session_name", _capture)
    async def _noop(*a, **k):
        return None
    for name in ("log_message", "add_usage", "set_code_session"):
        monkeypatch.setattr(db, name, _noop)
    sm = sessions.SessionManager(
        bot=SimpleNamespace(), settings=SimpleNamespace(), gate=SimpleNamespace()
    )
    monkeypatch.setattr(sm, "usage_footer", lambda lang, chat_id=None: "")
    rec = sessions._ThreadRecord(
        session=_FakeSession([_ev("result", "done", usage={}, session_id="s1")]),
        mode="code", stream_enabled=True, cwd=cwd, name="Pinned", name_auto=False,
    )
    asyncio.run(sm._run_one(rec, -1, "prompt", None, _FakeStreamer()))
    assert calls == []


def test_auto_name_falls_back_to_first_user_message(monkeypatch, tmp_path):
    # #345: no engine ai-title (a trivial / API-errored opening) → the namer falls back
    # to the first SUBSTANTIVE user message, still manual=False so a later ai-title wins.
    cwd = _write_transcript(tmp_path, "s1", [
        _u("hi"),                                  # greeting — skipped
        _a("API Error: 529 Overloaded"),
        _u("Compare the two SAP reports by aggregation totals"),
    ])
    calls = []
    async def _capture(thread_id, name, *, manual=True):
        calls.append((thread_id, name, manual))
    monkeypatch.setattr(db, "set_session_name", _capture)
    async def _noop(*a, **k):
        return None
    for name in ("log_message", "add_usage", "set_code_session"):
        monkeypatch.setattr(db, name, _noop)
    sm = sessions.SessionManager(
        bot=SimpleNamespace(), settings=SimpleNamespace(), gate=SimpleNamespace()
    )
    monkeypatch.setattr(sm, "usage_footer", lambda lang, chat_id=None: "")
    rec = sessions._ThreadRecord(
        session=_FakeSession([_ev("result", "done", usage={}, session_id="s1")]),
        mode="code", stream_enabled=True, cwd=cwd, name=None, name_auto=True,
    )
    asyncio.run(sm._run_one(rec, -1, "prompt", None, _FakeStreamer()))
    assert calls == [(-1, "Compare the two SAP reports by aggregation totals", False)]
    assert rec.name == "Compare the two SAP reports by aggregation totals"


def test_agent_ai_title_overrides_fallback_on_later_turn(monkeypatch, tmp_path):
    # #345 priority (user > AGENT ai-title > message fallback > placeholder): a turn-1
    # fallback name is SUPERSEDED when the agent writes its own ai-title on a later turn.
    # Both writes go through manual=False, so the name stays auto and the agent's title
    # wins — the exact "if the agent named it later, take it" requirement.
    reads = iter([
        (None, "Compare the two SAP reports"),                          # turn 1: no ai-title yet
        ("SAP report reconciliation", "Compare the two SAP reports"),   # turn 2: agent titled it
    ])
    monkeypatch.setattr(sessions, "_read_session_title", lambda cwd, sid: next(reads))
    calls = []
    async def _capture(thread_id, name, *, manual=True):
        calls.append((thread_id, name, manual))
    monkeypatch.setattr(db, "set_session_name", _capture)
    async def _noop(*a, **k):
        return None
    for name in ("log_message", "add_usage", "set_code_session"):
        monkeypatch.setattr(db, name, _noop)
    sm = sessions.SessionManager(
        bot=SimpleNamespace(), settings=SimpleNamespace(), gate=SimpleNamespace()
    )
    monkeypatch.setattr(sm, "usage_footer", lambda lang, chat_id=None: "")
    cwd = _write_transcript(tmp_path, "s1", [_u("hi")])  # content unused (read is mocked)
    rec = sessions._ThreadRecord(
        session=_FakeSession([_ev("result", "done", usage={}, session_id="s1")]),
        mode="code", stream_enabled=True, cwd=cwd, name=None, name_auto=True,
    )
    asyncio.run(sm._run_one(rec, -1, "prompt", None, _FakeStreamer()))
    assert calls[-1] == (-1, "Compare the two SAP reports", False)   # turn 1 → fallback
    assert rec.name == "Compare the two SAP reports"
    asyncio.run(sm._run_one(rec, -1, "prompt", None, _FakeStreamer()))
    assert calls[-1] == (-1, "SAP report reconciliation", False)     # turn 2 → agent title wins
    assert rec.name == "SAP report reconciliation"


# --- #261/#266: idle → new-session window resolution + in-place fallback ------ #

class _Closable:
    def __init__(self):
        self.closed = False
    async def aclose(self):
        self.closed = True


def _sm(window_sec):
    return sessions.SessionManager(
        bot=SimpleNamespace(),
        settings=SimpleNamespace(idle_reset_sec=window_sec),
        gate=SimpleNamespace(),
    )


def test_idle_window_global_default(monkeypatch):
    async def _no_default(uid, key):
        return None
    monkeypatch.setattr(db, "get_user_default", _no_default)
    sm = _sm(1800)
    assert asyncio.run(sm.idle_reset_seconds(42)) == 1800.0


def test_idle_window_per_user_override(monkeypatch):
    async def _default(uid, key):
        return "45"                                       # minutes
    monkeypatch.setattr(db, "get_user_default", _default)
    sm = _sm(1800)
    assert asyncio.run(sm.idle_reset_seconds(42)) == 45 * 60


def test_idle_window_per_user_disable(monkeypatch):
    async def _default(uid, key):
        return "0"                                        # ≤0 → never rotate
    monkeypatch.setattr(db, "get_user_default", _default)
    sm = _sm(1800)
    assert asyncio.run(sm.idle_reset_seconds(42)) == 0.0


def test_rotate_in_place_clears_ids_and_drops_client(monkeypatch):
    rotated = []
    async def _rot(tid):
        rotated.append(tid)
    monkeypatch.setattr(db, "rotate_session_for_idle", _rot)
    sm = _sm(1800)
    sess = _Closable()
    rec = sessions._ThreadRecord(session=sess, mode="code")
    sm._records[-1] = rec
    asyncio.run(sm.rotate_in_place(-1))
    assert rotated == [-1]                                 # DB resume-ids NULLed
    assert sess.closed and rec.session is None             # live client dropped → fresh rebuild


# --- #267: shell auto-capitalized command normalization ----------------------- #

def test_normalize_shell_cmd():
    assert sessions._normalize_shell_cmd("Ls") == "ls"
    assert sessions._normalize_shell_cmd("LS") == "ls"
    assert sessions._normalize_shell_cmd("Cat shell.md") == "cat shell.md"
    assert sessions._normalize_shell_cmd("Python3 app.py") == "python3 app.py"
    # only the COMMAND word changes — args/filenames keep their case
    assert sessions._normalize_shell_cmd("Cat Notes.md") == "cat Notes.md"
    # no change when not applicable
    assert sessions._normalize_shell_cmd("ls") is None        # already lowercase
    assert sessions._normalize_shell_cmd("./Foo") is None      # not a letter
    assert sessions._normalize_shell_cmd("") is None


def test_shell_retries_lowercased_on_not_found(monkeypatch):
    # #267: "Ls" returns 127 → retry "ls" → the user sees the real output.
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(db, "log_message", _noop)
    monkeypatch.setattr(i18n, "cached_lang", lambda cid: "en")
    calls = []

    class _Sess:
        async def shell_run(self, cmd, timeout=60.0):
            calls.append(cmd)
            if cmd == "Ls":
                return (127, "bash: Ls: command not found", "done")
            return (0, "file1  file2", "done")

    sm = sessions.SessionManager(
        bot=SimpleNamespace(), settings=SimpleNamespace(), gate=SimpleNamespace()
    )
    rec = sessions._ThreadRecord(session=_Sess(), mode="code", shell_mode=True,
                                 shell_awaiting=False)
    streamer = _FakeStreamer()
    asyncio.run(sm._run_shell_command(rec, -1, "Ls", streamer))
    assert calls == ["Ls", "ls"]                    # retried lowercased
    assert "file1" in streamer.finished_with        # success output shown, not the 127 error


def test_shell_no_retry_when_found(monkeypatch):
    # A normal (found) command must NOT trigger a second run.
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(db, "log_message", _noop)
    monkeypatch.setattr(i18n, "cached_lang", lambda cid: "en")
    calls = []

    class _Sess:
        async def shell_run(self, cmd, timeout=60.0):
            calls.append(cmd)
            return (0, "ok", "done")

    sm = sessions.SessionManager(
        bot=SimpleNamespace(), settings=SimpleNamespace(), gate=SimpleNamespace()
    )
    rec = sessions._ThreadRecord(session=_Sess(), mode="code", shell_mode=True,
                                 shell_awaiting=False)
    asyncio.run(sm._run_shell_command(rec, -1, "Ls", _FakeStreamer()))
    assert calls == ["Ls"]                           # found → no retry


def test_shell_keypad_tracked_on_await_and_resumable(monkeypatch):
    # #279: an awaiting command records the keypad message + render so /shell can strip it on
    # detach and restore it on re-attach; a done command clears the tracking.
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(db, "log_message", _noop)
    monkeypatch.setattr(i18n, "cached_lang", lambda cid: "en")

    class _Sess:
        async def shell_run(self, cmd, timeout=60.0):
            return (0, "? pick one", "awaiting")     # pauses for input

    sm = sessions.SessionManager(
        bot=SimpleNamespace(), settings=SimpleNamespace(), gate=SimpleNamespace())
    rec = sessions._ThreadRecord(session=_Sess(), mode="code", shell_mode=True)
    sm._records[-1] = rec
    st = _FakeStreamer()
    asyncio.run(sm._run_shell_command(rec, -1, "gh auth login", st))
    assert rec.shell_awaiting is True
    assert sm.shell_kb_ref(-1) == (st.chat_id, st.message_id)   # keypad message tracked
    assert sm.shell_resume_render(-1) is not None               # resumable render kept

    # Detach: handler strips the keypad + forgets the message ref, but keeps the render so a
    # re-attach can restore (shell_awaiting stays True).
    sm.set_shell_kb(-1, None, None)
    assert sm.shell_kb_ref(-1) is None
    assert sm.shell_resume_render(-1) is not None               # still resumable

    # The command completes → tracking is cleared, nothing to restore.
    class _Done:
        async def shell_send_input(self, text):
            return (0, "done", "done")
    rec.session = _Done()
    rec.shell_awaiting = True
    asyncio.run(sm._run_shell_command(rec, -1, "myuser", _FakeStreamer()))
    assert rec.shell_awaiting is False
    assert sm.shell_resume_render(-1) is None
    assert sm.shell_kb_ref(-1) is None


def test_shell_refresh_surfaces_advanced_prompt(monkeypatch):
    # #279: on re-attach, shell_refresh peeks output the program printed while detached.
    monkeypatch.setattr(i18n, "cached_lang", lambda cid: "en")

    class _Peek:
        def __init__(self, out):
            self._out = out

        async def shell_peek(self):
            return (None, self._out, "awaiting")

    sm = sessions.SessionManager(
        bot=SimpleNamespace(), settings=SimpleNamespace(), gate=SimpleNamespace())
    # Advanced-while-detached → returns a fresh render + updates the stored one.
    rec = sessions._ThreadRecord(session=_Peek("? Authenticate Git? (Y/n)"),
                                 mode="code", shell_mode=True, shell_awaiting=True)
    sm._records[-1] = rec
    live = asyncio.run(sm.shell_refresh(-1, "en"))
    assert live is not None and "Authenticate" in live
    assert rec.shell_last_render == live
    # Nothing new in the buffer → None (caller falls back to the stored render).
    rec.session = _Peek("")
    assert asyncio.run(sm.shell_refresh(-1, "en")) is None
    # Not awaiting → never peeks.
    rec.shell_awaiting = False
    assert asyncio.run(sm.shell_refresh(-1, "en")) is None


def test_set_idle_reset_sec_updates_and_persists(monkeypatch):
    # #261: the admin global setter updates the live window and persists it as a KV.
    saved = {}
    async def _set_kv(k, v):
        saved[k] = v
    monkeypatch.setattr(db, "set_kv", _set_kv)
    sm = sessions.SessionManager(
        bot=SimpleNamespace(),
        settings=SimpleNamespace(idle_reset_sec=1800),
        gate=SimpleNamespace(),
    )
    assert sm._idle_reset == 1800                       # from config default
    asyncio.run(sm.set_idle_reset_sec(45 * 60))
    assert sm._idle_reset == 2700 and saved["idle_reset_sec"] == "2700"
    asyncio.run(sm.set_idle_reset_sec(0))               # 0 = off
    assert sm._idle_reset == 0 and saved["idle_reset_sec"] == "0"


def test_text_full_fallback_still_adopted_when_not_segmented(monkeypatch):
    # No deltas (snapshot-only mode): the not-segmented fallback must still adopt
    # text_full so the answer is delivered (the fix only gates it AFTER segmenting).
    events = [
        _ev("text_full", "just prose, no code"),
        _ev("result", "just prose, no code", usage={}, session_id="s1"),
    ]
    s = _make(monkeypatch, events, mode="chat")
    assert s.flushed == []
    assert s.finished_with == "just prose, no code"


# --- #161/151c+151d: effective-settings resolution at consumption ----------- #

def test_effective_settings_soft_revoke_and_capability_gates(monkeypatch):
    """`_effective_settings` resolves through the access model (soft-revoke at
    consumption, 151c) and applies the capability gates (151d): a non-owner's
    read-only option falls back to global, ungranted `max` effort downgrades, and
    `full-access` reverts to ask. The owner keeps their own values."""
    async def _run():
        async def _no_overrides():
            return {}
        async def _no_default(uid, key):
            return None
        monkeypatch.setattr(db, "get_access_overrides", _no_overrides)
        monkeypatch.setattr(db, "get_user_default", _no_default)

        OWNER = 999

        class _AL:
            def level_of(self, uid, uname):
                return "code"
            def access_of(self, uid, uname):
                # owner has no exceptions; the user has model set to read-only.
                return {} if uid == OWNER else {"model": "readonly"}
            def allow_max_effort_of(self, uid, uname):
                return uid == OWNER          # only the owner may use max effort
            def global_memory_of(self, *a):
                return False
            def tool_cap_of(self, *a):
                return None

        settings = SimpleNamespace(owner_id=OWNER, default_model="claude-opus-4-8")
        sm = sessions.SessionManager(bot=SimpleNamespace(), settings=settings,
                                     gate=SimpleNamespace(), allowlist=_AL())

        def _state(uid):
            return SimpleNamespace(
                thread_id=-1, chat_id=uid, created_by=uid, mode="code",
                model="claude-haiku-4-5", effort="max",
                permission_mode="bypassPermissions", max_turns=None, big_memory=True,
            )

        # Non-owner code user with stale overrides the owner has since restricted.
        eff = await sm._effective_settings(_state(5))
        assert eff["model"] == "claude-opus-4-8"        # read-only → global (soft revoke)
        assert eff["effort"] == "xhigh"                 # max not granted → downgraded
        # #212: full-access is owner-only; a non-owner reverts to the normal
        # baseline, which is now acceptEdits (was "default"). Jail-backed default.
        assert eff["permission_mode"] == "acceptEdits"   # full-access owner-only → revert to baseline
        assert eff["big_memory"] is False               # memory Hidden by default → off

        # The owner keeps their own values (always Delegated + full capability).
        effo = await sm._effective_settings(_state(OWNER))
        assert effo["model"] == "claude-haiku-4-5"
        assert effo["effort"] == "max"
        assert effo["permission_mode"] == "bypassPermissions"
        assert effo["big_memory"] is True

    asyncio.run(_run())


# --- #179: idle-client reaper / eviction ------------------------------------ #


class _EvictSession:
    """Minimal ClaudeSession stand-in: records that aclose() was awaited."""

    def __init__(self):
        self.closed = False

    async def aclose(self):
        self.closed = True


def _sm_with_caps(max_live=2, idle_ttl=900, min_free=400, max_turns=2):
    return sessions.SessionManager(
        bot=SimpleNamespace(),
        settings=SimpleNamespace(
            max_live_clients=max_live, idle_ttl_sec=idle_ttl,
            min_free_mb=min_free, max_concurrent_turns=max_turns,
        ),
        gate=SimpleNamespace(),
    )


def test_evict_session_closes_idle_and_clears_snapshot():
    async def _run():
        sm = _sm_with_caps()
        sess = _EvictSession()
        rec = sessions._ThreadRecord(session=sess, mode="code", model="m", cwd="/w")
        sm._records[-1] = rec
        assert await sm._evict_session(-1) is True
        assert sess.closed is True            # aclose() awaited
        assert rec.session is None            # client dropped
        assert rec.mode is None and rec.cwd is None   # snapshot cleared → rebuild+resume
    asyncio.run(_run())


def test_evict_session_skips_busy_thread():
    async def _run():
        sm = _sm_with_caps()
        sess = _EvictSession()
        rec = sessions._ThreadRecord(session=sess, mode="code")
        rec.worker = SimpleNamespace(done=lambda: False)   # a turn is running
        sm._records[-1] = rec
        assert await sm._evict_session(-1) is False
        assert sess.closed is False           # never evict a busy session
        assert rec.session is sess
    asyncio.run(_run())


def test_reap_once_evicts_over_ttl_then_enforces_cap():
    async def _run():
        sm = _sm_with_caps(max_live=1, idle_ttl=100)
        now = time.monotonic()
        old = _EvictSession()
        r_old = sessions._ThreadRecord(session=old)
        r_old.last_activity = now - 10_000               # idle past TTL → evicted
        a = _EvictSession()
        r_a = sessions._ThreadRecord(session=a)
        r_a.last_activity = now - 5                       # idle, recent (LRU of the two)
        b = _EvictSession()
        r_b = sessions._ThreadRecord(session=b)
        r_b.last_activity = now - 1                       # idle, most recent → survives cap
        sm._records.update({-1: r_old, -2: r_a, -3: r_b})
        await sm._reap_once()
        assert old.closed is True             # TTL eviction
        assert a.closed is True               # over cap=1 → LRU evicted
        assert b.closed is False              # most-recently-active survives
    asyncio.run(_run())


def test_reap_respects_per_record_idle_ttl():
    # #182: a per-user idle-TTL on the record overrides the global default — 0 = ∞.
    async def _run():
        sm = _sm_with_caps(max_live=10, idle_ttl=100)  # high cap → only TTL matters
        now = time.monotonic()
        never = _EvictSession()
        r_never = sessions._ThreadRecord(session=never)
        r_never.last_activity = now - 10_000
        r_never.idle_ttl = 0                  # ∞ → never reaped on idle
        short = _EvictSession()
        r_short = sessions._ThreadRecord(session=short)
        r_short.last_activity = now - 10_000
        r_short.idle_ttl = 60                 # 60s TTL → reaped
        sm._records.update({-1: r_never, -2: r_short})
        await sm._reap_once()
        assert never.closed is False          # owner set ∞ — survives idle
        assert short.closed is True           # per-record TTL evicts
    asyncio.run(_run())


# --- #274: persistent shell survives the client reap ----------------------- #


class _FakeShell:
    def __init__(self, alive=True):
        self._alive = alive
        self.closed = False

    def alive(self):
        return self._alive

    async def close(self):
        self.closed = True


class _ShellSession(_EvictSession):
    """ClaudeSession stand-in that owns a detachable persistent shell (#274)."""

    def __init__(self, shell):
        super().__init__()
        self._shell = shell

    def has_live_shell(self):
        return self._shell is not None and self._shell.alive()

    def detach_shell(self):
        sh, self._shell = self._shell, None
        return sh

    def adopt_shell(self, sh):
        if sh is not None and self._shell is None:
            self._shell = sh


def test_evict_preserves_live_shell_then_reattaches():
    async def _run():
        sm = _sm_with_caps()
        shell = _FakeShell()
        sess = _ShellSession(shell)
        rec = sessions._ThreadRecord(session=sess, mode="code", model="m", cwd="/w")
        sm._records[-1] = rec
        assert await sm._evict_session(-1) is True
        assert sess.closed is True              # the ~500 MB client IS freed
        assert shell.closed is False            # …but the ~3 MB shell is preserved
        assert -1 in sm._detached_shells
        # The next rebuild re-attaches the preserved shell (cd/env/running cmd intact).
        new_sess = _ShellSession(None)
        sm._reattach_shell(new_sess, -1)
        assert new_sess._shell is shell
        assert -1 not in sm._detached_shells    # popped on adoption
    asyncio.run(_run())


def test_detached_shell_reaped_after_ttl_or_death():
    async def _run():
        sm = _sm_with_caps()
        sm._shell_ttl = 100
        now = time.monotonic()
        old = _FakeShell()
        sm._detached_shells[-1] = (old, now - 10_000)         # past the shell TTL
        fresh = _FakeShell()
        sm._detached_shells[-2] = (fresh, now - 5)            # within TTL → kept
        dead = _FakeShell(alive=False)
        sm._detached_shells[-3] = (dead, now - 5)            # died → dropped regardless
        await sm._reap_detached_shells(now)
        assert old.closed is True and -1 not in sm._detached_shells
        assert fresh.closed is False and -2 in sm._detached_shells
        assert dead.closed is True and -3 not in sm._detached_shells
    asyncio.run(_run())


def test_drop_detached_shell_closes_it():
    async def _run():
        sm = _sm_with_caps()
        shell = _FakeShell()
        sm._detached_shells[-1] = (shell, time.monotonic())
        await sm._drop_detached_shell(-1)        # hard reset/delete path
        assert shell.closed is True
        assert -1 not in sm._detached_shells
    asyncio.run(_run())


def test_mem_available_mb_is_positive():
    # On the Linux test box /proc/meminfo parses to a positive MiB figure.
    assert sessions.SessionManager._mem_available_mb() > 0


# --- #187: outbox file send-back -------------------------------------------- #


class _FakeBot:
    """Records the send_photo / send_document / send_message calls _deliver_outbox makes."""

    def __init__(self):
        self.photos: list = []
        self.docs: list = []
        self.messages: list = []

    async def send_photo(self, chat_id, photo=None, caption=None, **kw):
        self.photos.append(getattr(photo, "filename", None))

    async def send_document(self, chat_id, document=None, **kw):
        self.docs.append(getattr(document, "filename", None))

    async def send_message(self, chat_id, text, **kw):
        self.messages.append(text)


def _sm_with_bot(bot):
    return sessions.SessionManager(
        bot=bot, settings=SimpleNamespace(), gate=SimpleNamespace()
    )


def test_outbox_delivers_images_and_docs_then_clears(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "_OUTBOX_DOC_BYTES", 100)    # keep the too-big file tiny
    cwd = tmp_path / "work"
    outbox = cwd / "outbox"
    outbox.mkdir(parents=True)
    (outbox / "chart.png").write_bytes(b"img-bytes")          # image → photo
    (outbox / "report.txt").write_bytes(b"hello")             # other → document
    big = outbox / "huge.bin"
    big.write_bytes(b"x" * 101)                               # over the cap → skipped + noted

    bot = _FakeBot()
    sm = _sm_with_bot(bot)
    rec = sessions._ThreadRecord(session=SimpleNamespace(cwd=str(cwd)), mode="code")
    asyncio.run(sm._deliver_outbox(rec, 123, None))

    assert bot.photos == ["chart.png"]
    assert bot.docs == ["report.txt"]
    assert any("huge.bin" in m for m in bot.messages)          # too-big aggregated note
    # every staging copy is removed (delivered ones AND the undeliverable big one)
    assert not (outbox / "chart.png").exists()
    assert not (outbox / "report.txt").exists()
    assert not big.exists()


def test_outbox_count_cap_leaves_remainder(tmp_path):
    cwd = tmp_path / "work"
    outbox = cwd / "outbox"
    outbox.mkdir(parents=True)
    total = sessions._OUTBOX_MAX_FILES + 3
    for i in range(total):
        (outbox / f"f{i:02d}.txt").write_bytes(b"x")

    bot = _FakeBot()
    sm = _sm_with_bot(bot)
    rec = sessions._ThreadRecord(session=SimpleNamespace(cwd=str(cwd)), mode="code")
    asyncio.run(sm._deliver_outbox(rec, 123, None))

    assert len(bot.docs) == sessions._OUTBOX_MAX_FILES          # only the cap is sent
    left = [p for p in outbox.iterdir() if p.is_file()]
    assert len(left) == 3                                       # remainder stays for next turn
    assert any("staged" in m or "outbox" in m for m in bot.messages)  # "more pending" note


def test_outbox_no_dir_is_noop(tmp_path):
    # A chat session (no outbox dir) drains to nothing and never touches the bot.
    bot = _FakeBot()
    sm = _sm_with_bot(bot)
    rec = sessions._ThreadRecord(session=SimpleNamespace(cwd=str(tmp_path)), mode="chat")
    asyncio.run(sm._deliver_outbox(rec, 123, None))
    assert bot.photos == [] and bot.docs == [] and bot.messages == []


# ----------------------------------------------- #236 queue status + backlog cap

def test_handle_text_queue_status_and_cap(monkeypatch):
    """#236: handle_text() reports whether a prompt started immediately, was queued
    behind a running turn (returning the waiting count), or was rejected at the
    per-session backlog cap. Uses a fake worker that never drains so the session
    stays 'busy' for the whole test."""
    import contextlib

    async def _noop(*a, **k):
        return None

    async def _ensure(*a, **k):
        return SimpleNamespace()

    async def _slow_worker(*a, **k):
        await asyncio.sleep(3600)  # never consumes the queue → session stays busy

    monkeypatch.setattr(db, "ensure_thread", _ensure)
    monkeypatch.setattr(db, "set_kv", _noop)

    sm = sessions.SessionManager(
        bot=SimpleNamespace(),
        settings=SimpleNamespace(default_model="m"),
        gate=SimpleNamespace(),
    )
    monkeypatch.setattr(sm, "_default_cwd", lambda tid: "/tmp/x")
    monkeypatch.setattr(sm, "_get_session", _noop)
    monkeypatch.setattr(sm, "_worker", _slow_worker)

    async def _body():
        chat, tid = 100, 5
        # Idle session → runs now.
        assert await sm.handle_text(chat, tid, "a") == sessions.SUBMIT_STARTED
        rec = sm._records[tid]
        # Simulate the worker pulling the running item off the queue.
        rec.queue.get_nowait()
        # Now busy: each follow-up is queued and reports the waiting count.
        assert await sm.handle_text(chat, tid, "b") == 1
        assert await sm.handle_text(chat, tid, "c") == 2
        last = None
        for _ in range(3):
            last = await sm.handle_text(chat, tid, "x")
        assert last == sessions.MAX_QUEUED_MESSAGES  # backlog now full (5 waiting)
        # Over the cap → rejected, NOT enqueued.
        assert await sm.handle_text(chat, tid, "y") == sessions.SUBMIT_QUEUE_FULL
        assert rec.queue.qsize() == sessions.MAX_QUEUED_MESSAGES
        rec.worker.cancel()
        with contextlib.suppress(BaseException):
            await rec.worker

    asyncio.run(_body())


# ----------------------------------------------- #245/#227b full-screen TUI guard

def test_is_fullscreen_tui_cmd():
    """#245/#227b: only full-screen TUIs are refused; line-interactive commands now run
    (their input is forwarded via the await-input flow)."""
    tui = ["vim foo.py", "/usr/bin/nano x", "top", "htop", "less file", "man ls", "watch date"]
    ok = ["gh auth login", "sudo apt update", "python", "node", "ls -la", "pytest -q",
          "echo hi", "cat foo.txt", "git rebase -i HEAD~3", "read x"]
    for c in tui:
        assert sessions._is_fullscreen_tui_cmd(c) is True, c
    for c in ok:
        assert sessions._is_fullscreen_tui_cmd(c) is False, c


def test_shell_input_keys_parsing():
    """#227b: a pure key-token message (`.`-prefixed, not `:` → no emoji popup) → raw key
    bytes; literal text → None."""
    assert sessions._shell_input_keys(".enter") == b"\r"
    assert sessions._shell_input_keys(".down .enter") == b"\x1b[B\r"
    assert sessions._shell_input_keys(".UP") == b"\x1b[A"    # case-insensitive
    assert sessions._shell_input_keys(".ctrl-c") == b"\x03"
    assert sessions._shell_input_keys("GitHub.com") is None  # literal text → typed as input
    assert sessions._shell_input_keys(".down foo") is None   # mixed → literal
    assert sessions._shell_input_keys("") is None


def test_shell_keypad_builds():
    """#227b: the inline keypad builds primary + 'more' layouts with shk: callbacks. Primary
    layout (#227 owner request): Esc ↑ Enter / ← ↓ → / Tab ^C ⋯more."""
    datas = [b.callback_data for row in sessions.shell_keypad().inline_keyboard for b in row]
    for cb in ("shk:esc", "shk:up", "shk:enter", "shk:left", "shk:down", "shk:right",
               "shk:tab", "shk:ctrlc", "shk:more"):
        assert cb in datas, cb
    mdatas = [b.callback_data for row in sessions.shell_keypad(more=True).inline_keyboard for b in row]
    assert "shk:space" in mdatas and "shk:less" in mdatas and "shk:pgup" in mdatas


# --- #345: session-name fallback when the engine never wrote an ai-title ----------

def test_topic_from_text_skips_thin_keeps_substantive():
    """#345: greetings/probes/acks and the injected recap prompt are NOT topics; a
    real message is kept (whitespace-collapsed) and capped at _AI_TITLE_MAX. The
    threshold is letter-count, so it is language-agnostic (a short non-English probe
    is filtered by the same rule)."""
    tf = sessions._topic_from_text
    assert tf("hi") is None
    assert tf("you up?") is None          # 5 letters < 10
    assert tf("  ok  ") is None
    assert tf("Recap our conversation so far in one short sentence.") is None
    assert tf("Compare the two SAP reports by aggregation totals") == (
        "Compare the two SAP reports by aggregation totals"
    )
    assert tf("first line of a real ask\nmore detail") == "first line of a real ask more detail"
    assert len(tf("name " + "z" * 200)) == sessions._AI_TITLE_MAX


def test_read_session_title_prefers_ai_title(tmp_path):
    """When the engine wrote an ai-title, that wins (the fallback is still computed in
    the same single pass, but the caller takes ai_title)."""
    cwd = _write_transcript(tmp_path, "s1", [
        _u("Compare the two SAP reports by aggregation totals"),
        {"type": "ai-title", "aiTitle": "SAP report comparison"},
        _a("..."),
        {"type": "ai-title", "aiTitle": "SAP report comparison (final)"},  # LAST wins
    ])
    ai, fb = sessions._read_session_title(cwd, "s1")
    assert ai == "SAP report comparison (final)"
    assert fb == "Compare the two SAP reports by aggregation totals"


def test_read_session_title_fallback_on_errored_trivial_opening(tmp_path):
    """The #345 stuck-session shape: a contentless opener whose first turns ERROR (so the
    engine never wrote an ai-title), then a substantive turn → fallback names it from the
    first substantive user message, skipping the greetings and the API-error replies."""
    cwd = _write_transcript(tmp_path, "s2", [
        _u("hi"),
        _a("API Error: 500 Internal server error"),
        _u("hi"),
        _a("API Error: 529 Overloaded"),
        _u("Compare the two SAP reports by aggregation totals"),
    ])
    ai, fb = sessions._read_session_title(cwd, "s2")
    assert ai is None
    assert fb == "Compare the two SAP reports by aggregation totals"


def test_read_session_title_all_trivial_stays_unnamed(tmp_path):
    """A genuinely contentless session (only a greeting) yields no name at all — better
    unnamed than a junk label."""
    cwd = _write_transcript(tmp_path, "s3", [_u("hi"), _a("Not asleep — how can I help?")])
    ai, fb = sessions._read_session_title(cwd, "s3")
    assert ai is None and fb is None


def test_read_session_title_missing_or_empty_args(tmp_path):
    assert sessions._read_session_title(None, None) == (None, None)
    assert sessions._read_session_title(str(tmp_path / "work"), "nope") == (None, None)
