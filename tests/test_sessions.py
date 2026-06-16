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
        assert eff["permission_mode"] == "default"      # full-access owner-only → revert
        assert eff["big_memory"] is False               # memory Hidden by default → off

        # The owner keeps their own values (always Delegated + full capability).
        effo = await sm._effective_settings(_state(OWNER))
        assert effo["model"] == "claude-haiku-4-5"
        assert effo["effort"] == "max"
        assert effo["permission_mode"] == "bypassPermissions"
        assert effo["big_memory"] is True

    asyncio.run(_run())
