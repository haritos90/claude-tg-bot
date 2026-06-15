"""Integration tests for sessions._run_one live code-block splitting (#93).

Guards the audit-found double-post regression: with include_partial_messages the
engine streams the text as deltas AND then emits a terminal CUMULATIVE text_full
snapshot (engine.py). Once a fenced block has been live-split off the running
text, that snapshot must NOT resurrect and re-flush it as a duplicate message.

Async tests wrap asyncio.run (no pytest-asyncio), matching the suite convention.
"""
import asyncio
from types import SimpleNamespace

import db
import sessions


class _FakeStreamer:
    """Records the commit calls _run_one makes, without touching Telegram."""

    def __init__(self):
        self.chat_id = 12345
        self.thread_id = None
        self.flushed = []          # flush_segment(text) payloads (live splits)
        self.segment_breaks = 0    # segment_break() count (tool boundaries)
        self.finished_with = None  # finish(full_text) payload
        self.cancelled = False

    async def start(self, placeholder=None):
        pass

    async def update(self, full_text):
        pass

    async def segment_break(self):
        self.segment_breaks += 1

    async def flush_segment(self, text):
        self.flushed.append(text)

    async def finish(self, full_text, footer="", notify=True):
        self.finished_with = full_text

    def cancel(self):
        self.cancelled = True


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
    )


def _make(monkeypatch, events, mode="code"):
    async def _noop(*a, **k):
        return None
    for name in ("log_message", "add_usage", "set_code_session",
                 "set_chat_session", "set_fork_pending"):
        monkeypatch.setattr(db, name, _noop)
    sm = sessions.SessionManager(
        bot=SimpleNamespace(), settings=SimpleNamespace(), gate=SimpleNamespace()
    )
    monkeypatch.setattr(sm, "usage_footer", lambda lang: "")
    rec = sessions._ThreadRecord(
        session=_FakeSession(events), mode=mode, stream_enabled=True
    )
    streamer = _FakeStreamer()
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
