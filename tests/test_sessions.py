"""Integration tests for sessions._run_one live code-block splitting (#93).

Guards the audit-found double-post regression: with include_partial_messages the
engine streams the text as deltas AND then emits a terminal CUMULATIVE text_full
snapshot (engine.py). Once a fenced block has been live-split off the running
text, that snapshot must NOT resurrect and re-flush it as a duplicate message.

Async tests wrap asyncio.run (no pytest-asyncio), matching the suite convention.
"""
import asyncio
import time
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
    monkeypatch.setattr(sm, "usage_footer", lambda lang, chat_id=None: "")
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
