"""Unit tests for the #188 schedule RUNNER gates in sessions._fire_schedule:
orphan guard (#254), allowlist re-check (#255), the no-swap memory deferral, and the
db cascade-delete of schedules on session delete (#254).

Async tests wrap asyncio.run (no pytest-asyncio), matching the suite convention.
"""
import asyncio
import json
import time
from types import SimpleNamespace

from app.storage import db
from app.core import sessions


class _AL:
    """Allowlist stand-in with a toggleable verdict."""

    def __init__(self, allowed=True):
        self.allowed = allowed

    def is_allowed(self, uid, uname):
        return self.allowed


def _mgr(allowlist=None, min_free_mb=400):
    settings = SimpleNamespace(default_model="claude-opus-4-8", min_free_mb=min_free_mb)
    sm = sessions.SessionManager(
        bot=SimpleNamespace(send_message=_noop), settings=settings,
        gate=SimpleNamespace(), allowlist=allowlist,
    )
    sm._fired = []  # record handle_text dispatches
    async def _fake_handle_text(chat_id, thread_id, prompt):
        sm._fired.append((chat_id, thread_id, prompt))
        return 0
    sm.handle_text = _fake_handle_text
    return sm


async def _noop(*a, **kw):
    return None


async def _seed(spec, *, with_thread=True, owner_uid=42, past=True):
    """Fresh in-memory db with one schedule (next_run already due if past)."""
    await db.init_db(":memory:")
    if with_thread:
        await db.ensure_thread(7, 100, "claude-opus-4-8", "/tmp")
    now = time.time()
    nxt = now - 5 if past else now + 3600
    sid = await db.add_schedule(7, 100, owner_uid, json.dumps(spec), "do it", nxt, now)
    return sid, nxt


def test_fire_dispatches_and_advances_next_run():
    async def run():
        sid, old_next = await _seed({"kind": "interval", "seconds": 3600})
        sm = _mgr(allowlist=_AL(True))
        sm._mem_available_mb = staticmethod(lambda: 1 << 20)  # plenty
        row = (await db.due_schedules(time.time()))[0]
        await sm._fire_schedule(row)
        assert sm._fired == [(100, 7, "do it")]
        sched = await db.get_schedule(sid)
        assert sched["last_status"] == "ok"          # dispatched
        assert sched["next_run"] > old_next          # advanced
        assert sched["enabled"] == 1
        await db.close_db()
    asyncio.run(run())


def test_low_memory_defers_without_advancing():
    async def run():
        sid, old_next = await _seed({"kind": "interval", "seconds": 3600})
        sm = _mgr(allowlist=_AL(True), min_free_mb=400)
        sm._mem_available_mb = staticmethod(lambda: 50)  # below floor, stays below
        row = (await db.due_schedules(time.time()))[0]
        await sm._fire_schedule(row)
        assert sm._fired == []                        # NOT dispatched
        sched = await db.get_schedule(sid)
        assert sched["next_run"] == old_next          # next_run UNTOUCHED → retried next sweep
        assert sched["enabled"] == 1                  # still active
        await db.close_db()
    asyncio.run(run())


def test_orphan_thread_disables_schedule():
    async def run():
        sid, _ = await _seed({"kind": "interval", "seconds": 3600}, with_thread=False)
        sm = _mgr(allowlist=_AL(True))
        sm._mem_available_mb = staticmethod(lambda: 1 << 20)
        row = (await db.due_schedules(time.time()))[0]
        await sm._fire_schedule(row)
        assert sm._fired == []                        # did NOT resurrect the thread
        sched = await db.get_schedule(sid)
        assert sched["enabled"] == 0
        assert sched["last_status"] == "orphaned"
        await db.close_db()
    asyncio.run(run())


def test_revoked_owner_disables_schedule():
    async def run():
        sid, _ = await _seed({"kind": "interval", "seconds": 3600})
        sm = _mgr(allowlist=_AL(False))               # owner no longer allowed
        sm._mem_available_mb = staticmethod(lambda: 1 << 20)
        row = (await db.due_schedules(time.time()))[0]
        await sm._fire_schedule(row)
        assert sm._fired == []
        sched = await db.get_schedule(sid)
        assert sched["enabled"] == 0
        assert sched["last_status"] == "revoked"
        await db.close_db()
    asyncio.run(run())


def test_delete_dm_session_cascades_to_schedules():
    async def run():
        await db.init_db(":memory:")
        # delete_dm_session scopes to (thread_id == key AND chat_id == user_id).
        await db.ensure_thread(55, 55, "claude-opus-4-8", "/tmp")
        now = time.time()
        sid = await db.add_schedule(55, 55, 55, json.dumps(
            {"kind": "interval", "seconds": 3600}), "p", now + 10, now)
        assert await db.get_schedule(sid) is not None
        assert await db.delete_dm_session(55, 55) is True
        assert await db.get_schedule(sid) is None     # cascade removed it (#254)
        await db.close_db()
    asyncio.run(run())
