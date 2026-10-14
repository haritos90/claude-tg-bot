"""Integration tests for `_run_one` live code-block splitting.

- cumulative text_full snapshot must not re-flush a split block
- async tests wrap asyncio.run (no pytest-asyncio)
"""
import asyncio
import contextlib
import time
from types import SimpleNamespace

from app.storage import db
from app.storage import archive
from app import i18n
from app.core import models, sessions


class _FakeStreamer:
    """Records the commit calls `_run_one` makes, without Telegram."""

    def __init__(self):
        self.chat_id = 12345
        self.thread_id = None
        self.message_id = 999      # id of the finished message
        self.flushed = []          # `flush_segment` payloads (live splits)
        self.segment_breaks = 0    # `segment_break` count (tool boundaries)
        self.finished_with = None  # `finish` payload
        self.cancelled = False
        self.reasoning = []        # `add_reasoning` payloads
        self.phases = []           # `set_phase` payloads (tool phase)
        self.web_sources = []      # `add_web_source` payloads

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
        # Mirror the real streamer: build the localized label.
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
    # Record session-id persists for the early-persist test.
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
    streamer.saved_sessions = saved_sessions   # expose persisted session ids
    asyncio.run(sm._run_one(rec, -1, "prompt", None, streamer))
    return streamer


def test_live_split_no_double_post_on_cumulative_text_full(monkeypatch):
    full = "Here is code:\n```py\nx = 1\n```\nmore"
    events = [
        _ev("text_delta", "Here is code:\n"),
        _ev("text_delta", "```py\n"),
        _ev("text_delta", "x = 1\n"),
        _ev("text_delta", "```\n"),   # closes block: one live flush
        _ev("text_delta", "more"),
        _ev("text_full", full),       # cumulative snapshot must not re-flush
        _ev("result", full, usage={}, session_id="s1"),
    ]
    s = _make(monkeypatch, events)
    assert len(s.flushed) == 1, s.flushed          # not 2 (the regression)
    assert "x = 1" in s.flushed[0]
    assert s.finished_with == "more"               # only the trailing remainder


def test_thinking_after_text_splits_into_new_bubble(monkeypatch):
    # Answer text, then reasoning again (interleaved thinking, no tool).
    # - prior text finalized as its own bubble; fresh one opens
    # - trailing text after reasoning becomes the final message
    events = [
        _ev("text_delta", "First part. "),
        _ev("thinking_delta", "let me reconsider"),
        _ev("text_delta", "Second part."),
        _ev("result", "", usage={}, session_id="s1"),
    ]
    s = _make(monkeypatch, events, mode="chat")
    assert s.segment_breaks == 1                    # split once, on first delta
    assert s.reasoning == ["let me reconsider"]
    assert s.finished_with == "Second part."        # only the post-reasoning burst


def test_web_tool_phase_shown_in_chat(monkeypatch):
    # Chat-mode web search shows a live 'Searching the web' phase.
    events = [
        _ev("tool", tool_name="WebSearch", tool_input={"query": "weather"}),
        _ev("text_delta", "It's sunny."),
        _ev("result", "It's sunny.", usage={}, session_id="s1"),
    ]
    s = _make(monkeypatch, events, mode="chat")
    assert any("web" in p.lower() for p in s.phases), s.phases
    assert s.segment_breaks == 0          # no text before tool: no split
    assert s.finished_with == "It's sunny."


def test_thinking_without_prior_text_does_not_split(monkeypatch):
    # thinking_delta before any answer text must not break a segment.
    events = [
        _ev("thinking_delta", "planning"),
        _ev("text_delta", "Only answer."),
        _ev("result", "", usage={}, session_id="s1"),
    ]
    s = _make(monkeypatch, events, mode="chat")
    assert s.segment_breaks == 0
    assert s.finished_with == "Only answer."


def test_repeated_thinking_after_text_splits_each_time(monkeypatch):
    # Each thinking phase after answer text opens a fresh bubble.
    # - prior text is finalized as its own bubble
    # - thinking block is re-shown each time
    # - no later thinking phase is lost
    events = [
        _ev("thinking_delta", "t1"),       # before any text: no split
        _ev("text_delta", "A. "),
        _ev("thinking_delta", "t2"),       # after text: split one
        _ev("text_delta", "B. "),
        _ev("thinking_delta", "t3"),       # after text: split two
        _ev("text_delta", "C."),
        _ev("result", "", usage={}, session_id="s1"),
    ]
    s = _make(monkeypatch, events, mode="chat")
    assert s.segment_breaks == 2                       # one split per think-after-text
    assert s.reasoning == ["t1", "t2", "t3"]           # every thinking phase captured
    assert s.finished_with == "C."                     # only the final post-reasoning burst



def test_tool_start_sets_phase_without_split_or_source(monkeypatch):
    # A `tool_start` event shows the live phase immediately.
    # - adds no source and splits no bubble
    # - those wait for the assembled `tool` event
    events = [
        _ev("tool_start", tool_name="WebSearch", tool_input={}),
        _ev("text_delta", "Answer."),
        _ev("result", "Answer.", usage={}, session_id="s1"),
    ]
    s = _make(monkeypatch, events, mode="chat")
    assert any("web" in p.lower() for p in s.phases), s.phases   # phase shown during the call
    assert s.web_sources == []                                   # no source yet (input empty)
    assert s.segment_breaks == 0
    assert s.finished_with == "Answer."


def test_fair_admission_round_robin_by_user():
    # Full slots admit waiting turns round-robin by user.
    # - one user's burst can't starve another
    # - queue [A2, A3, B1] is served A2, B1, A3
    # - plain FIFO would make B wait behind A
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
        await asyncio.sleep(0)                 # let all three block in queue
        gate.release()                         # holder done: cascade admits round-robin
        await asyncio.gather(*tasks)

    asyncio.run(scenario())
    assert order == ["A2", "B1", "A3"], order
    assert gate.active == 0                    # everything released, no leaked slot


def test_fair_admission_cancel_waiter_no_leak():
    # A waiter cancelled while queued never leaks its slot.
    gate = sessions.FairAdmission(slots=1)

    async def scenario():
        await gate.acquire("A")                # full
        t = asyncio.create_task(gate.acquire("B"))
        await asyncio.sleep(0)                  # B blocks in the queue
        t.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await t
        gate.release()                         # holder done, B gone: slot frees
        assert gate.active == 0
        await gate.acquire("C")                # gate still works after cancel
        assert gate.active == 1
        gate.release()
        assert gate.active == 0

    asyncio.run(scenario())


def test_drain_waits_for_active_turns_then_returns():
    # `drain()` blocks until in-flight turns finish, bounded by timeout.
    # - lets a graceful restart complete the active turn
    sm = sessions.SessionManager(
        bot=SimpleNamespace(), settings=SimpleNamespace(), gate=SimpleNamespace()
    )

    async def scenario():
        sm._active_turns = 1
        sm._idle_event.clear()
        assert await sm.drain(timeout=0.05) is False   # turn active: times out
        assert sm._draining is True                    # draining is latched on
        sm._active_turns = 0
        sm._idle_event.set()
        assert await sm.drain(timeout=0.05) is True     # turn finished: returns immediately
    asyncio.run(scenario())


def test_session_id_persisted_early_not_only_at_result(monkeypatch):
    # Session id is persisted immediately from the init event.
    # - a turn killed mid-flight still leaves a resumable id
    # - otherwise the next message would lose all context
    events = [
        _ev("session", session_id="sid-1"),
        _ev("text_delta", "Drawing the SVG…"),
        _ev("result", "Done.", usage={}, session_id="sid-1"),
    ]
    s = _make(monkeypatch, events, mode="chat")
    assert s.saved_sessions[0] == ("chat", "sid-1")    # persisted by the early session event
    assert s.saved_sessions[-1] == ("chat", "sid-1")   # and again at terminal result


def test_chat_text_before_tool_is_kept_as_its_own_bubble(monkeypatch):
    # In chat, pre-search text is committed as its own bubble.
    # - not shown, then clobbered by the final answer
    # - mirrors the check-first, search, then answer flow
    events = [
        _ev("text_delta", "Let me look that up. Meanwhile, searching… "),
        _ev("tool", tool_name="WebSearch", tool_input={"query": "news"}),
        _ev("text_delta", "Here is the overview."),
        _ev("result", "Here is the overview.", usage={}, session_id="s1"),
    ]
    s = _make(monkeypatch, events, mode="chat")
    assert s.segment_breaks == 1                          # pre-tool text kept as bubble
    assert s.finished_with == "Here is the overview."     # final is the post-tool answer


# --- Adopt transcript ai-title as session name ---

def _write_transcript(tmp_path, sid, lines):
    """Lay out a session transcript the way the jail does.

    - `<root>/work` is the cwd
    - ai-title lives at `<root>/state/<encoded-cwd>/<sid>.jsonl`
    """
    import json as _json
    root = tmp_path / "sess"
    cwd = root / "work"
    cwd.mkdir(parents=True)
    # Encode the cwd exactly as claude writes it on disk.
    # - every non-alphanumeric char becomes '-' via the shared archive helper
    # - plain '/' replacement diverges when paths contain '_' or '.'
    tdir = archive.live_transcript_dir(str(cwd))
    tdir.mkdir(parents=True)
    (tdir / f"{sid}.jsonl").write_text(
        "\n".join(_json.dumps(o, ensure_ascii=False) for o in lines) + "\n",
        encoding="utf-8",
    )
    return str(cwd)


def _u(text):
    """A transcript `user` line in real message.content shape."""
    return {"type": "user", "message": {"role": "user", "content": text}}


def _a(text):
    """A transcript `assistant` line, never a name source."""
    return {"type": "assistant", "message": {"role": "assistant", "content": text}}


def test_read_ai_title_returns_last_and_caps(tmp_path):
    cwd = _write_transcript(tmp_path, "s1", [
        {"type": "user", "text": "hi"},
        {"type": "ai-title", "aiTitle": "First guess", "sessionId": "s1"},
        {"type": "assistant", "text": "x"},
        {"type": "ai-title", "aiTitle": "Refined title", "sessionId": "s1"},
    ])
    assert sessions._read_session_title(cwd, "s1")[0] == "Refined title"  # the last one
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
    # End-to-end: a finished turn reads ai-title and renames.
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
    assert rec.name == "Fix the parser"               # in-memory name kept fresh


def test_auto_name_skipped_when_pinned(monkeypatch, tmp_path):
    # Pinned name (`name_auto` False): the namer never calls the DB.
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
    # Without ai-title, the namer falls back to a user message.
    # - uses first substantive user message
    # - still manual=False so a later ai-title wins
    cwd = _write_transcript(tmp_path, "s1", [
        _u("hi"),                                  # greeting skipped
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
    # Message-derived names are cut to button width at words.
    assert calls == [(-1, "Compare the two SAP reports by…", False)]
    assert rec.name == "Compare the two SAP reports by…"


def test_agent_ai_title_overrides_fallback_on_later_turn(monkeypatch, tmp_path):
    # Priority: user, agent ai-title, message fallback, placeholder.
    # - a turn-1 fallback is superseded by a later agent ai-title
    # - both writes use manual=False, so the name stays auto
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
    assert calls[-1] == (-1, "Compare the two SAP reports", False)   # turn 1: fallback
    assert rec.name == "Compare the two SAP reports"
    asyncio.run(sm._run_one(rec, -1, "prompt", None, _FakeStreamer()))
    assert calls[-1] == (-1, "SAP report reconciliation", False)     # turn 2: agent title wins
    assert rec.name == "SAP report reconciliation"


# --- Idle new-session window resolution and in-place fallback ---

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
        return "0"                                        # zero or less: never rotate
    monkeypatch.setattr(db, "get_user_default", _default)
    sm = _sm(1800)
    assert asyncio.run(sm.idle_reset_seconds(42)) == 0.0


def test_login_expiry_banner_owner_gate_read_throttle_and_display_spend(monkeypatch):
    """Login-expiry heads-up is owner-only and throttled.

    - creds file read at most once/day outside the warn window
    - display throttle spent only after finish() delivers
    - read throttle not spent in-window before delivery
    - a failed finish never eats the day's heads-up
    """
    OWNER = 777
    sm = sessions.SessionManager(
        bot=SimpleNamespace(),
        settings=SimpleNamespace(owner_id=OWNER, idle_reset_sec=1800),
        gate=SimpleNamespace(),
    )
    monkeypatch.setattr(sessions.i18n, "cached_lang", lambda cid: "en")
    reads = {"n": 0}
    seconds_left = {"v": 2 * 86400}            # 2 days out: inside default window

    def _login_seconds_left(*a, **k):
        reads["n"] += 1
        return seconds_left["v"]

    monkeypatch.setattr(sessions.token_refresh, "login_seconds_left", _login_seconds_left)

    # non-owner: nothing read, no throttle spent
    assert sm._login_expiry_banner(OWNER + 1) is None
    assert reads["n"] == 0
    assert sm._login_check_last == 0.0 and sm._login_warn_last == 0.0

    # Owner in window: banner shown, read throttle unspent.
    # - display throttle stays 0.0 until finish() delivers
    # - a failed finish keeps re-offering the heads-up
    banner = sm._login_expiry_banner(OWNER)
    assert banner and reads["n"] == 1
    assert sm._login_check_last == 0.0
    assert sm._login_warn_last == 0.0

    # An undelivered in-window banner is re-offered next turn.
    assert sm._login_expiry_banner(OWNER) and reads["n"] == 2

    # After delivery spends the display throttle, banner is None.
    sm._login_warn_last = sessions.time.time()
    assert sm._login_expiry_banner(OWNER) is None
    assert reads["n"] == 2

    # Outside the window: None, and the read throttle is spent.
    # - creds file is not reopened every turn
    # - display throttle stays untouched
    sm._login_warn_last = 0.0
    sm._login_check_last = 0.0
    seconds_left["v"] = 60 * 86400
    reads_before = reads["n"]
    assert sm._login_expiry_banner(OWNER) is None
    assert reads["n"] == reads_before + 1                      # it did read (throttle clear)
    assert sm._login_check_last > 0.0
    assert sm._login_warn_last == 0.0
    # A second outside-window turn does not re-read; throttle holds.
    assert sm._login_expiry_banner(OWNER) is None
    assert reads["n"] == reads_before + 1


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
    assert rotated == [-1]                                 # DB resume-ids nulled
    assert sess.closed and rec.session is None             # live client dropped: fresh rebuild


# --- Shell auto-capitalized command normalization ---

def test_normalize_shell_cmd():
    assert sessions._normalize_shell_cmd("Ls") == "ls"
    assert sessions._normalize_shell_cmd("LS") == "ls"
    assert sessions._normalize_shell_cmd("Cat shell.md") == "cat shell.md"
    assert sessions._normalize_shell_cmd("Python3 app.py") == "python3 app.py"
    # Only the command word changes; args keep their case.
    assert sessions._normalize_shell_cmd("Cat Notes.md") == "cat Notes.md"
    # no change when not applicable
    assert sessions._normalize_shell_cmd("ls") is None        # already lowercase
    assert sessions._normalize_shell_cmd("./Foo") is None      # not a letter
    assert sessions._normalize_shell_cmd("") is None


def test_shell_retries_lowercased_on_not_found(monkeypatch):
    # 'Ls' returns 127, retry 'ls', user sees real output.
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
    assert "file1" in streamer.finished_with        # success output shown, not 127


def test_shell_no_retry_when_found(monkeypatch):
    # A found command must not trigger a second run.
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
    assert calls == ["Ls"]                           # found: no retry


def test_shell_keypad_tracked_on_await_and_resumable(monkeypatch):
    # An awaiting command records the keypad message and render.
    # - lets /shell strip it on detach and restore on re-attach
    # - a done command clears the tracking
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

    # Detach strips the keypad and forgets the message ref.
    # - keeps the render so re-attach can restore
    # - `shell_awaiting` stays True
    sm.set_shell_kb(-1, None, None)
    assert sm.shell_kb_ref(-1) is None
    assert sm.shell_resume_render(-1) is not None               # still resumable

    # Command completes: tracking cleared, nothing to restore.
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
    # On re-attach, `shell_refresh` peeks output printed while detached.
    monkeypatch.setattr(i18n, "cached_lang", lambda cid: "en")

    class _Peek:
        def __init__(self, out):
            self._out = out

        async def shell_peek(self):
            return (None, self._out, "awaiting")

    sm = sessions.SessionManager(
        bot=SimpleNamespace(), settings=SimpleNamespace(), gate=SimpleNamespace())
    # Advanced while detached: fresh render, stored one updated.
    rec = sessions._ThreadRecord(session=_Peek("? Authenticate Git? (Y/n)"),
                                 mode="code", shell_mode=True, shell_awaiting=True)
    sm._records[-1] = rec
    live = asyncio.run(sm.shell_refresh(-1, "en"))
    assert live is not None and "Authenticate" in live
    assert rec.shell_last_render == live
    # Nothing new in buffer: None (caller uses stored render).
    rec.session = _Peek("")
    assert asyncio.run(sm.shell_refresh(-1, "en")) is None
    # Not awaiting: never peeks.
    rec.shell_awaiting = False
    assert asyncio.run(sm.shell_refresh(-1, "en")) is None


def test_set_idle_reset_sec_updates_and_persists(monkeypatch):
    # Admin global setter updates the live window and persists.
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
    # Snapshot-only mode (no deltas): fallback must still adopt `text_full`.
    # - the answer must be delivered
    # - adoption is gated only after segmenting
    events = [
        _ev("text_full", "just prose, no code"),
        _ev("result", "just prose, no code", usage={}, session_id="s1"),
    ]
    s = _make(monkeypatch, events, mode="chat")
    assert s.flushed == []
    assert s.finished_with == "just prose, no code"


# --- Effective-settings resolution at consumption ---

def test_effective_settings_soft_revoke_and_capability_gates(monkeypatch):
    """`_effective_settings` resolves via access model and capability gates.

    - non-owner read-only option falls back to global
    - ungranted `max` effort downgrades
    - `full-access` reverts to ask
    - the owner keeps their own values
    """
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
                # Owner has no exceptions; user's model is read-only.
                return {} if uid == OWNER else {"model": "readonly"}
            def allow_max_effort_of(self, uid, uname):
                return uid == OWNER          # only owner may use max effort
            def global_memory_of(self, *a):
                return False
            def tool_cap_of(self, *a):
                return None

        settings = SimpleNamespace(owner_id=OWNER, default_model="claude-opus-4-8")
        sm = sessions.SessionManager(bot=SimpleNamespace(), settings=settings,
                                     gate=SimpleNamespace(), allowlist=_AL())
        # Max step-down and withheld family come from the CLI catalog.
        monkeypatch.setattr(models, "_catalog", [
            {"value": "claude-opus-4-8", "resolvedModel": "claude-opus-4-8",
             "supportsEffort": True,
             "supportedEffortLevels": ["low", "medium", "high", "xhigh", "max"]},
            {"value": "fable", "resolvedModel": "claude-fable-5-1", "supportsEffort": True,
             "supportedEffortLevels": ["low", "medium", "high", "max"]},
        ])

        def _state(uid):
            return SimpleNamespace(
                thread_id=-1, chat_id=uid, created_by=uid, mode="code",
                model="claude-haiku-4-5", effort="max",
                permission_mode="bypassPermissions", max_turns=None, big_memory=True,
            )

        # Non-owner code user with stale, since-restricted overrides.
        eff = await sm._effective_settings(_state(5))
        assert eff["model"] == "claude-opus-4-8"        # read-only: global (soft revoke)
        assert eff["effort"] == "xhigh"                 # max not granted: CLI's next level
        # `full-access` is owner-only; a non-owner reverts to baseline.
        # - baseline is `acceptEdits`, the jail-backed default
        assert eff["permission_mode"] == "acceptEdits"   # owner-only: revert to baseline
        assert "big_memory" not in eff                  # 1M toggle is retired

        # The owner keeps their own values.
        effo = await sm._effective_settings(_state(OWNER))
        assert effo["model"] == "claude-haiku-4-5"
        assert effo["effort"] == "max"
        assert effo["permission_mode"] == "bypassPermissions"
        assert "big_memory" not in effo

        # A withheld family never runs, even for the owner.
        def _fable(uid):
            st = _state(uid)
            st.model = "fable"
            return st
        assert (await sm._effective_settings(_fable(OWNER)))["model"] == "claude-opus-4-8"
        # No catalog yet: ungranted max falls back to default.
        monkeypatch.setattr(models, "_catalog", [])
        assert (await sm._effective_settings(_state(5)))["effort"] is None

    asyncio.run(_run())


# --- Idle-client reaper and eviction ---


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
        assert sess.closed is True            # `aclose()` awaited
        assert rec.session is None            # client dropped
        assert rec.mode is None and rec.cwd is None   # snapshot cleared: rebuild and resume
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
        r_old.last_activity = now - 10_000               # idle past TTL: evicted
        a = _EvictSession()
        r_a = sessions._ThreadRecord(session=a)
        r_a.last_activity = now - 5                       # idle, recent (LRU of two)
        b = _EvictSession()
        r_b = sessions._ThreadRecord(session=b)
        r_b.last_activity = now - 1                       # idle, most recent: survives cap
        sm._records.update({-1: r_old, -2: r_a, -3: r_b})
        await sm._reap_once()
        assert old.closed is True             # TTL eviction
        assert a.closed is True               # over cap=1: LRU evicted
        assert b.closed is False              # most-recently-active survives
    asyncio.run(_run())


def test_reap_respects_per_record_idle_ttl():
    # A per-record idle TTL overrides the global default.
    # - 0 means infinite
    async def _run():
        sm = _sm_with_caps(max_live=10, idle_ttl=100)  # high cap: only TTL matters
        now = time.monotonic()
        never = _EvictSession()
        r_never = sessions._ThreadRecord(session=never)
        r_never.last_activity = now - 10_000
        r_never.idle_ttl = 0                  # infinite: never reaped on idle
        short = _EvictSession()
        r_short = sessions._ThreadRecord(session=short)
        r_short.last_activity = now - 10_000
        r_short.idle_ttl = 60                 # 60s TTL: reaped
        sm._records.update({-1: r_never, -2: r_short})
        await sm._reap_once()
        assert never.closed is False          # owner set infinite: survives idle
        assert short.closed is True           # per-record TTL evicts
    asyncio.run(_run())


# --- Persistent shell survives the client reap ---


class _FakeShell:
    def __init__(self, alive=True):
        self._alive = alive
        self.closed = False

    def alive(self):
        return self._alive

    async def close(self):
        self.closed = True


class _ShellSession(_EvictSession):
    """ClaudeSession stand-in that owns a detachable persistent shell."""

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
        assert sess.closed is True              # the ~500 MB client is freed
        assert shell.closed is False            # the ~3 MB shell is kept
        assert -1 in sm._detached_shells
        # Next rebuild re-attaches the preserved shell (cd/env/running cmd intact).
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
        sm._detached_shells[-2] = (fresh, now - 5)            # within TTL: kept
        dead = _FakeShell(alive=False)
        sm._detached_shells[-3] = (dead, now - 5)            # died: dropped regardless
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
    # On the Linux test box, /proc/meminfo parses to positive MiB.
    assert sessions.SessionManager._mem_available_mb() > 0


# --- Outbox file send-back ---


class _FakeBot:
    """Records send_photo, send_document and send_message calls from `_deliver_outbox`."""

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
    (outbox / "chart.png").write_bytes(b"img-bytes")          # image: photo
    (outbox / "report.txt").write_bytes(b"hello")             # other: document
    big = outbox / "huge.bin"
    big.write_bytes(b"x" * 101)                               # over the cap: skipped and noted

    bot = _FakeBot()
    sm = _sm_with_bot(bot)
    rec = sessions._ThreadRecord(session=SimpleNamespace(cwd=str(cwd)), mode="code")
    asyncio.run(sm._deliver_outbox(rec, 123, None))

    assert bot.photos == ["chart.png"]
    assert bot.docs == ["report.txt"]
    assert any("huge.bin" in m for m in bot.messages)          # too-big aggregated note
    # Every staging copy is removed, delivered or undeliverable.
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
    assert any("staged" in m or "outbox" in m for m in bot.messages)  # 'more pending' note


def test_outbox_no_dir_is_noop(tmp_path):
    # A chat session without outbox drains to nothing.
    bot = _FakeBot()
    sm = _sm_with_bot(bot)
    rec = sessions._ThreadRecord(session=SimpleNamespace(cwd=str(tmp_path)), mode="chat")
    asyncio.run(sm._deliver_outbox(rec, 123, None))
    assert bot.photos == [] and bot.docs == [] and bot.messages == []


# --- Queue status and backlog cap ---

def test_handle_text_queue_status_and_cap(monkeypatch):
    """`handle_text()` reports started, queued, or rejected prompts.

    - queued returns the waiting count
    - rejected at the per-session backlog cap
    - fake worker never drains, so session stays busy
    """
    import contextlib

    async def _noop(*a, **k):
        return None

    async def _ensure(*a, **k):
        return SimpleNamespace()

    async def _slow_worker(*a, **k):
        await asyncio.sleep(3600)  # never consumes queue: session stays busy

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
        # Idle session runs now.
        assert await sm.handle_text(chat, tid, "a") == sessions.SUBMIT_STARTED
        rec = sm._records[tid]
        # Simulate the worker pulling the running item off the queue.
        rec.queue.get_nowait()
        # Busy: each follow-up is queued and reports waiting count.
        assert await sm.handle_text(chat, tid, "b") == 1
        assert await sm.handle_text(chat, tid, "c") == 2
        last = None
        for _ in range(3):
            last = await sm.handle_text(chat, tid, "x")
        assert last == sessions.MAX_QUEUED_MESSAGES  # backlog now full (5 waiting)
        # Over the cap: rejected, not enqueued.
        assert await sm.handle_text(chat, tid, "y") == sessions.SUBMIT_QUEUE_FULL
        assert rec.queue.qsize() == sessions.MAX_QUEUED_MESSAGES
        rec.worker.cancel()
        with contextlib.suppress(BaseException):
            await rec.worker

    asyncio.run(_body())


# --- Full-screen TUI guard ---

def test_is_fullscreen_tui_cmd():
    """Only full-screen TUIs are refused; line-interactive commands run.

    - their input is forwarded via the await-input flow
    """
    tui = ["vim foo.py", "/usr/bin/nano x", "top", "htop", "less file", "man ls", "watch date"]
    ok = ["gh auth login", "sudo apt update", "python", "node", "ls -la", "pytest -q",
          "echo hi", "cat foo.txt", "git rebase -i HEAD~3", "read x"]
    for c in tui:
        assert sessions._is_fullscreen_tui_cmd(c) is True, c
    for c in ok:
        assert sessions._is_fullscreen_tui_cmd(c) is False, c


def test_shell_input_keys_parsing():
    """A pure key-token message maps to raw key bytes.

    - `.`-prefixed, not `:` (no emoji popup)
    - literal text returns None
    """
    assert sessions._shell_input_keys(".enter") == b"\r"
    assert sessions._shell_input_keys(".down .enter") == b"\x1b[B\r"
    assert sessions._shell_input_keys(".UP") == b"\x1b[A"    # case-insensitive
    assert sessions._shell_input_keys(".ctrl-c") == b"\x03"
    assert sessions._shell_input_keys("GitHub.com") is None  # literal text: typed as input
    assert sessions._shell_input_keys(".down foo") is None   # mixed: literal
    assert sessions._shell_input_keys("") is None


def test_shell_keypad_builds():
    """The inline keypad builds primary and 'more' layouts.

    - buttons use `shk:` callbacks
    - primary rows: Esc/Up/Enter, Left/Down/Right, Tab/^C/more
    """
    datas = [b.callback_data for row in sessions.shell_keypad().inline_keyboard for b in row]
    for cb in ("shk:esc", "shk:up", "shk:enter", "shk:left", "shk:down", "shk:right",
               "shk:tab", "shk:ctrlc", "shk:more"):
        assert cb in datas, cb
    mdatas = [b.callback_data for row in sessions.shell_keypad(more=True).inline_keyboard for b in row]
    assert "shk:space" in mdatas and "shk:less" in mdatas and "shk:pgup" in mdatas


# --- Session-name fallback when no ai-title exists ---

def test_topic_from_text_skips_thin_keeps_substantive():
    """Greetings, probes, acks and recap prompts are not topics.

    - a real message is kept, whitespace-collapsed
    - cut to button width (`_BUTTON_NAME_MAX`) on a word boundary
    - threshold is letter-count, so language-agnostic
    """
    tf = sessions._topic_from_text
    assert tf("hi") is None
    assert tf("you up?") is None          # 5 letters, under 10
    assert tf("  ok  ") is None
    assert tf("Recap our conversation so far in one short sentence.") is None
    assert tf("Compare the two SAP reports by aggregation totals") == (
        "Compare the two SAP reports by…"           # whole words up to button width
    )
    assert tf("first line of a real ask\nmore detail") == "first line of a real ask more detail"
    assert tf("name " + "z" * 200) == "name…"        # over-long single word is dropped
    assert len(tf("word " * 30)) <= sessions._BUTTON_NAME_MAX


def test_read_session_title_prefers_ai_title(tmp_path):
    """An engine-written ai-title wins over the fallback.

    - fallback is still computed in the same pass
    """
    cwd = _write_transcript(tmp_path, "s1", [
        _u("Compare the two SAP reports by aggregation totals"),
        {"type": "ai-title", "aiTitle": "SAP report comparison"},
        _a("..."),
        {"type": "ai-title", "aiTitle": "SAP report comparison (final)"},  # last wins
    ])
    ai, fb = sessions._read_session_title(cwd, "s1")
    assert ai == "SAP report comparison (final)"
    assert fb == "Compare the two SAP reports by…"   # button-width cut


def test_read_session_title_fallback_on_errored_trivial_opening(tmp_path):
    """Stuck session: fallback names it from first substantive message.

    - opener is contentless and early turns error (no ai-title)
    - greetings and API-error replies are skipped
    """
    cwd = _write_transcript(tmp_path, "s2", [
        _u("hi"),
        _a("API Error: 500 Internal server error"),
        _u("hi"),
        _a("API Error: 529 Overloaded"),
        _u("Compare the two SAP reports by aggregation totals"),
    ])
    ai, fb = sessions._read_session_title(cwd, "s2")
    assert ai is None
    assert fb == "Compare the two SAP reports by…"   # button-width cut


def test_read_session_title_all_trivial_stays_unnamed(tmp_path):
    """A contentless session (only a greeting) yields no name.

    - better unnamed than a junk label
    """
    cwd = _write_transcript(tmp_path, "s3", [_u("hi"), _a("Not asleep — how can I help?")])
    ai, fb = sessions._read_session_title(cwd, "s3")
    assert ai is None and fb is None


def test_read_session_title_missing_or_empty_args(tmp_path):
    assert sessions._read_session_title(None, None) == (None, None)
    assert sessions._read_session_title(str(tmp_path / "work"), "nope") == (None, None)
