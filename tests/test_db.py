"""Unit tests for the db layer.

- each test uses a fresh temp SQLite file
- async API driven by `asyncio.run()` in sync tests
- module-level connection and lock reset per test
- avoids `pytest-asyncio` and cross-loop lock reuse
"""

import asyncio
import re
import tempfile
from pathlib import Path

from app.storage import db


def _run(coro_factory):
    db._conn = None
    db._lock = None
    return asyncio.run(coro_factory())


def test_allocate_dm_session_negative_key_and_mode():
    async def _t():
        await db.init_db(tempfile.mktemp(suffix=".db"))
        code = await db.allocate_dm_session(123, "Proj", "m", "/tmp/wd", mode="code")
        chat = await db.allocate_dm_session(123, "Talk", "m", "/tmp/wd", mode="chat")
        assert code < 0 and chat < 0 and code != chat
        sc, sh = await db.get_thread(code), await db.get_thread(chat)
        assert sc.mode == "code" and sh.mode == "chat"
        # Per-session working dir is named by the public id.
        # - nested layout: cwd is `<id>/work`, state is the sibling
        # - the public id is the ULID
        assert sc.cwd.endswith(db.session_pubid(code) + "/work")
        assert sh.cwd.endswith(db.session_pubid(chat) + "/work")
        await db.close_db()

    _run(_t)


def test_user_default_roundtrip_and_clear():
    """User-scope storage: per-user default stored JSON-encoded in kv.

    - `None` clears it; a garbled value degrades to `None`
    """
    async def _t():
        await db.init_db(tempfile.mktemp(suffix=".db"))
        assert await db.get_user_default(7, "model") is None
        await db.set_user_default(7, "model", "claude-sonnet-4-6")
        assert await db.get_user_default(7, "model") == "claude-sonnet-4-6"
        # Non-string JSON values (bool, int) round-trip too.
        await db.set_user_default(7, "memory", True)
        assert await db.get_user_default(7, "memory") is True
        # Isolated per uid.
        assert await db.get_user_default(8, "model") is None
        # Clearing deletes the row, giving `None`.
        await db.set_user_default(7, "model", None)
        assert await db.get_user_default(7, "model") is None
        # A garbled raw value degrades to `None`.
        await db.set_kv("user_default:7:bad", "{not json")
        assert await db.get_user_default(7, "bad") is None
        await db.close_db()

    _run(_t)


def test_stream_flag_persists():
    async def _t():
        await db.init_db(tempfile.mktemp(suffix=".db"))
        k = await db.allocate_dm_session(1, "s", "m", "/tmp", mode="chat")
        assert (await db.get_thread(k)).stream_enabled is True
        await db.set_stream_enabled(k, False)
        assert (await db.get_thread(k)).stream_enabled is False
        await db.close_db()

    _run(_t)


def test_session_name_auto_then_manual_pin(tmp_path):
    # A new session is auto-namable.
    # - auto-namer writes the label and keeps `name_auto` on
    # - manual rename pins the name and turns auto off
    # - afterwards the auto-namer is a no-op
    async def _t():
        # `tmp_path` auto-cleans, unlike `tempfile.mktemp` which leaks db files.
        await db.init_db(str(tmp_path / "names.db"))
        k = await db.allocate_dm_session(1, "s", "m", "/tmp", mode="code")
        st = await db.get_thread(k)
        assert st.name_auto is True          # default: auto on
        await db.set_session_name(k, "Auto title", manual=False)
        st = await db.get_thread(k)
        assert st.name == "Auto title" and st.name_auto is True
        # A later auto write overrides an earlier auto name.
        # - agent title beats the message fallback
        await db.set_session_name(k, "Better auto title", manual=False)
        st = await db.get_thread(k)
        assert st.name == "Better auto title" and st.name_auto is True
        await db.set_session_name(k, "My name")   # manual rename (default)
        st = await db.get_thread(k)
        assert st.name == "My name" and st.name_auto is False
        await db.set_session_name(k, "Late auto", manual=False)  # no-op once pinned
        st = await db.get_thread(k)
        assert st.name == "My name"
        await db.close_db()

    _run(_t)


def test_browse_threads_surfaces_name_auto_for_gc_guard(tmp_path):
    # The empty-session GC spares manually renamed sessions via `name_auto`.
    # - works only if `browse_threads` returns `name_auto`
    # - mirror the GC candidate predicate to prove it
    async def _t():
        await db.init_db(str(tmp_path / "gc.db"))
        uid = 5
        auto = await db.allocate_dm_session(uid, "Auto", "m", "/tmp", mode="chat")
        named = await db.allocate_dm_session(uid, "Auto2", "m", "/tmp", mode="chat")
        await db.set_session_name(named, "My project")   # manual rename: `name_auto` False
        page, _ = await db.browse_threads(uid, None, limit=100, offset=0)
        await db.close_db()
        return page, auto, named
    page, auto, named = _run(_t)
    by_id = {r["thread_id"]: r for r in page}
    # The field is surfaced and reflects the manual rename.
    assert by_id[auto]["name_auto"] is True
    assert by_id[named]["name_auto"] is False
    # The GC candidate filter now spares the renamed one.
    keep = auto  # `auto` is current, never a candidate
    cands = {r["thread_id"] for r in page
             if r["thread_id"] != keep and r["thread_id"] < 0
             and not r.get("favorite") and r.get("name_auto", True)}
    assert named not in cands   # renamed empty session is not collected
    assert auto not in cands    # kept session is never a candidate


def test_browse_threads_orders_by_last_activity_not_creation(tmp_path):
    # Writing in an existing session floats it to the top.
    # - order by `max(last_active, created_at)`
    # - never-completed session (`last_active=0`) uses `created_at`
    async def _t():
        await db.init_db(str(tmp_path / "order.db"))
        uid = 9
        a = await db.allocate_dm_session(uid, "Italy trip", "m", "/tmp", mode="chat")
        b = await db.allocate_dm_session(uid, "Groceries", "m", "/tmp", mode="chat")
        c = await db.allocate_dm_session(uid, "Fresh", "m", "/tmp", mode="chat")
        # `last_active` is wall-clock; use values well past `created_at`.
        # - `a` was created first but is active most recently: top
        await db.set_last_active(a, 9_000_000_100.0)
        await db.set_last_active(b, 9_000_000_050.0)
        # `c` never completed a turn, so it sorts by `created_at`.
        # - it must land last: a and b have real activity
        page, _ = await db.browse_threads(uid, None, limit=100, offset=0)
        await db.close_db()
        return [r["thread_id"] for r in page], a, b, c
    order, a, b, c = _run(_t)
    assert order == [a, b, c]   # most recently active first; never-active oldest


def test_last_active_and_idle_rotation_keeps_messages(tmp_path):
    # `last_active` roundtrips; idle rotation drops resume ids.
    # - keeps the message log and cwd
    # - unlike `reset_thread`, which wipes messages
    async def _t():
        # `tmp_path` auto-cleans, unlike `tempfile.mktemp` which leaks db files.
        await db.init_db(str(tmp_path / "idle.db"))
        k = await db.allocate_dm_session(1, "s", "m", "/tmp/wd", mode="code")
        cwd_before = (await db.get_thread(k)).cwd
        assert (await db.get_thread(k)).last_active == 0.0
        await db.set_last_active(k, 12345.0)
        assert (await db.get_thread(k)).last_active == 12345.0
        await db.set_code_session(k, "code-1")
        await db.set_chat_session(k, "chat-1")
        await db.log_message(k, "user", "remember me")
        await db.rotate_session_for_idle(k)
        st = await db.get_thread(k)
        assert st.code_session_id is None and st.chat_session_id is None  # context dropped
        assert st.cwd == cwd_before                                       # workdir kept
        msgs = await db.get_recent_messages(k)
        assert [(m["role"], m["text"]) for m in msgs] == [("user", "remember me")]
        await db.close_db()

    _run(_t)


def test_message_log_recall_and_reset():
    async def _t():
        await db.init_db(tempfile.mktemp(suffix=".db"))
        k = await db.allocate_dm_session(1, "s", "m", "/tmp", mode="chat")
        await db.log_message(k, "user", "hi")
        await db.log_message(k, "assistant", "yo")
        await db.log_message(k, "user", "")  # empty is skipped
        msgs = await db.get_recent_messages(k)
        assert [(m["role"], m["text"]) for m in msgs] == [
            ("user", "hi"), ("assistant", "yo")
        ]
        await db.reset_thread(k)  # clears the log too
        assert await db.get_recent_messages(k) == []
        await db.close_db()

    _run(_t)


def test_rate_history_append_and_trim():
    async def _t():
        await db.init_db(tempfile.mktemp(suffix=".db"))
        await db.append_rate_history("seven_day", 0.5, "allowed")
        await db.append_rate_history("seven_day", None, "allowed")  # `None` tolerated
        hist = await db.get_rate_history("seven_day")
        assert len(hist) == 2 and hist[0]["utilization"] == 0.5
        await db.close_db()

    _run(_t)


def test_pro_command_options_roundtrip():
    async def _t():
        await db.init_db(tempfile.mktemp(suffix=".db"))
        k = await db.allocate_dm_session(1, "s", "m", "/tmp", mode="code")
        await db.set_effort(k, "max")
        await db.set_max_turns(k, 7)
        await db.set_add_dirs(k, ["/a", "/b"])
        await db.set_fork_pending(k, True)
        st = await db.get_thread(k)
        assert st.effort == "max" and st.max_turns == 7
        assert st.add_dirs == ["/a", "/b"] and st.fork_pending is True
        await db.set_fork_pending(k, False)
        assert (await db.get_thread(k)).fork_pending is False
        await db.close_db()

    _run(_t)


def test_delete_dm_session_scoped_and_clears_messages():
    async def _t():
        await db.init_db(tempfile.mktemp(suffix=".db"))
        k = await db.allocate_dm_session(42, "s", "m", "/tmp", mode="chat")
        await db.log_message(k, "user", "x")
        # Wrong user can't delete; positive keys refused.
        assert await db.delete_dm_session(999, k) is False
        assert await db.delete_dm_session(42, 5) is False
        assert await db.delete_dm_session(42, k) is True
        assert await db.get_thread(k) is None
        assert await db.get_recent_messages(k) == []
        await db.close_db()

    _run(_t)


def test_forward_migration_adds_columns_with_defaults():
    # A pre-release db is migrated in place by `init_db`.
    # - only the original minimal `threads` schema
    # - `get_thread` then returns newer fields at defaults
    async def _t():
        import aiosqlite

        path = tempfile.mktemp(suffix=".db")
        # Build a fresh db with the original schema, one row.
        conn = await aiosqlite.connect(path)
        await conn.execute(
            "CREATE TABLE threads ("
            "thread_id INTEGER PRIMARY KEY, chat_id INTEGER, mode TEXT, "
            "model TEXT, cwd TEXT, code_session_id TEXT, name TEXT, created_at REAL)"
        )
        await conn.execute(
            "INSERT INTO threads (thread_id, chat_id, mode, model, cwd, "
            "code_session_id, name, created_at) "
            "VALUES (-1, 7, 'chat', 'm', '/tmp', NULL, 'legacy', 0)"
        )
        await conn.commit()
        await conn.close()

        # Migrate the existing file and read the row back.
        await db.init_db(path)
        st = await db.get_thread(-1)
        assert st is not None
        # Legacy `default` permission mode migrates to `acceptEdits`.
        # - code sessions then auto-accept file edits
        assert st.permission_mode == "acceptEdits"
        assert st.big_memory is False
        assert st.stream_enabled is True
        assert st.favorite is False
        assert st.fork_pending is False
        assert st.add_dirs == []
        await db.close_db()

    _run(_t)


def test_legacy_default_permission_mode_migrated_to_accept_edits(tmp_path):
    # A code session stored as legacy `default` migrates on init.
    # - file creation and edits then stop prompting
    async def _t():
        path = str(tmp_path / "perm.db")
        await db.init_db(path)
        await db._require_conn().execute(
            "INSERT INTO threads (thread_id, chat_id, mode, model, cwd, permission_mode, created_at) "
            "VALUES (-9, 7, 'code', 'm', '/tmp', 'default', 0)"
        )
        await db._require_conn().commit()
        await db.close_db()
        # Re-open: the data migration runs.
        await db.init_db(path)
        st = await db.get_thread(-9)
        assert st.permission_mode == "acceptEdits"
        await db.close_db()

    _run(_t)


def test_favorite_flag_persists_and_sorts_first():
    async def _t():
        await db.init_db(tempfile.mktemp(suffix=".db"))
        a = await db.allocate_dm_session(7, "old", "m", "/tmp/wd")
        b = await db.allocate_dm_session(7, "new", "m", "/tmp/wd")
        # Default: not favorite; newest listed first.
        rows, total = await db.browse_threads(7)
        assert total == 2 and rows[0]["thread_id"] == b
        assert rows[0]["favorite"] is False
        # Favoriting the older one floats it to the top.
        await db.set_favorite(a, True)
        assert (await db.get_thread(a)).favorite is True
        rows, _ = await db.browse_threads(7)
        assert rows[0]["thread_id"] == a and rows[0]["favorite"] is True
        await db.close_db()

    _run(_t)


def test_usage_is_tokens_only_and_breakdown():
    """Usage and cap basis are input plus output tokens.

    - no model weight, no cache multipliers
    - breakdown rolls up by the user's DM `chat_id`
    - the retired "units" measure fails loudly
    """
    import pytest

    async def _t():
        await db.init_db(tempfile.mktemp(suffix=".db"))
        uid = 5
        key = await db.allocate_dm_session(uid, "s", "opus", "/tmp", mode="code")
        # One turn: input 1000, output 100, cache_creation 200, cache_read 10000.
        await db.add_usage(
            key,
            {"input_tokens": 1000, "output_tokens": 100,
             "cache_creation_input_tokens": 200, "cache_read_input_tokens": 10000},
            0.0, model="claude-opus-5-5", context_tokens=42000,
        )
        assert await db.get_user_usage_window(uid) == 1100          # default: tokens
        await db.add_usage(key, {"input_tokens": 10, "output_tokens": 0}, 0.0)
        assert await db.get_user_usage_window(uid) == 1110
        bd = await db.get_user_breakdown(uid)
        assert bd["day"] == bd["week"] == bd["total"] == 1110 and bd["requests"] == 2
        assert "units" not in (await db.get_usage_totals_bulk([key]))[key]
        with pytest.raises(ValueError):
            await db.get_user_usage_window(uid, measure="units")
        assert await db.get_user_usage_window(999) == 0              # another user: nothing
        await db.close_db()

    _run(_t)


def test_usage_survives_session_delete(tmp_path):
    """Token usage outlives deleting the session it was spent in.

    - still feeds lifetime totals and rolling-limit windows
    - keyed by `chat_id`, so deletion can't dodge caps
    """
    async def _t():
        # `tmp_path` auto-cleans, unlike `tempfile.mktemp` which leaks db files.
        await db.init_db(str(tmp_path / "usage.db"))
        uid = 7
        key = await db.allocate_dm_session(uid, "s", "m", "/tmp", mode="code")
        await db.add_usage(key, {"input_tokens": 1000, "output_tokens": 100}, 0.0)
        # Baseline: spend counts for the user in all aggregations.
        assert await db.get_user_usage_window(uid, measure="raw") == 1100
        assert (await db.get_user_breakdown(uid))["total"] == 1100
        assert any(r["uid"] == uid for r in await db.get_all_users_breakdown())
        # Delete the session the usage was spent in.
        assert await db.delete_dm_session(uid, key) is True
        assert await db.get_thread(key) is None            # session gone
        # Usage still counts toward totals and the rolling window.
        assert await db.get_user_usage_window(uid, measure="raw") == 1100
        bd = await db.get_user_breakdown(uid)
        assert bd["total"] == 1100 and bd["requests"] == 1
        assert any(r["uid"] == uid for r in await db.get_all_users_breakdown())
        await db.close_db()

    _run(_t)


def test_claim_session_uid_stable_and_collision_free():
    """Host-uid registry: preferred hash uid, stable, collision-free.

    - same uid on repeat; distinct uid on hash collision
    - a freed slot is reused after release
    """
    async def _t():
        await db.init_db(tempfile.mktemp(suffix=".db"))
        lo, hi = 700000, 700000 + 60000
        # Preferred is free: returned, and stable across calls.
        u1 = await db.claim_session_uid("aaaaaa", 700005, lo, hi)
        assert u1 == 700005
        assert await db.claim_session_uid("aaaaaa", 700005, lo, hi) == 700005
        # Different sids with the same preferred get distinct uids.
        u2 = await db.claim_session_uid("bbbbbb", 700005, lo, hi)
        u3 = await db.claim_session_uid("cccccc", 700005, lo, hi)
        assert len({u1, u2, u3}) == 3
        assert all(lo <= u < hi for u in (u2, u3))
        # Release frees a slot; the next colliding sid reuses it.
        await db.release_session_uid("aaaaaa")
        assert await db.claim_session_uid("dddddd", 700005, lo, hi) == 700005
        await db.close_db()

    _run(_t)


def test_claim_session_uid_exhaustion_falls_back():
    """A full window falls back to the clamped preferred uid.

    - collisions become possible again only here
    """
    async def _t():
        await db.init_db(tempfile.mktemp(suffix=".db"))
        lo, hi = 1000, 1002  # span = 2
        a = await db.claim_session_uid("a", 1000, lo, hi)
        b = await db.claim_session_uid("b", 1000, lo, hi)
        assert {a, b} == {1000, 1001}
        assert await db.claim_session_uid("c", 1000, lo, hi) == 1000
        await db.close_db()

    _run(_t)


def test_uid_collisions_pure():
    """Doctor groups sids by uid, reporting only shared uids."""
    assert db._uid_collisions({"a": 700001, "b": 700002}) == {}
    assert db._uid_collisions({"a": 700001, "b": 700001, "c": 700002}) == {700001: ["a", "b"]}
    assert db._uid_collisions({}) == {}
    # uid 0 (root) is never a collision, even when shared.
    assert db._uid_collisions({"a": 0, "b": 0}) == {}
    assert db._uid_collisions({"a": 0, "b": 0, "c": 700001, "d": 700001}) == {700001: ["c", "d"]}


def test_sandbox_uid_collisions_scan():
    """Doctor reports work dirs sharing an owner.

    - dirs without `work` and non-dir entries are skipped
    - a lone session is clean
    """
    import os

    base = tempfile.mkdtemp()
    os.makedirs(os.path.join(base, "sidA", "work"))
    os.makedirs(os.path.join(base, "sidB", "work"))  # same owner (test uid): collide
    os.makedirs(os.path.join(base, "sidC"))          # no work dir: skipped
    with open(os.path.join(base, "loose.txt"), "w") as fh:
        fh.write("x")                                # not a dir: skipped
    # Work dirs belong to the test process uid.
    # - a root owner is excluded: root hosts return `{}`
    # - the assertion branches on root
    if os.getuid() == 0:
        assert db.sandbox_uid_collisions(base) == {}     # root owner excluded
    else:
        assert db.sandbox_uid_collisions(base) == {os.getuid(): ["sidA", "sidB"]}

    solo = tempfile.mkdtemp()
    os.makedirs(os.path.join(solo, "sidX", "work"))
    assert db.sandbox_uid_collisions(solo) == {}


def test_user_last_active_roundtrip_default_zero():
    # Per-user idle clock defaults to 0; set/get roundtrips durably.
    async def _t():
        await db.init_db(tempfile.mktemp(suffix=".db"))
        before = await db.get_user_last_active(777)
        await db.set_user_last_active(777, 12345.0)
        after = await db.get_user_last_active(777)
        await db.close_db()
        return before, after
    before, after = _run(_t)
    assert before == 0.0
    assert after == 12345.0


def test_new_ulid_format_uniqueness_and_time_sortable():
    # ULID: 26-char Crockford base32, collision-free, sortable timestamp prefix.
    ids = [db.new_ulid() for _ in range(64)]
    assert all(len(u) == 26 for u in ids)
    assert all(c in db._CROCKFORD for u in ids for c in u)
    assert len(set(ids)) == 64
    prefixes = [u[:10] for u in ids]                 # the 48-bit ms timestamp portion
    assert prefixes == sorted(prefixes)              # generated in time order: non-decreasing


def test_session_sid_is_6hex_and_pubid_uses_cache():
    # `session_sid` is always the stable 6-hex id.
    # - `session_pubid` is the public ULID from the cache
    # - falls back to the 6-hex id when not backfilled
    db._SID_BY_THREAD.pop(-424242, None)
    wid = db.session_sid(-424242)
    assert len(wid) == 6 and all(c in "0123456789abcdef" for c in wid)
    assert db.session_pubid(-424242) == wid  # uncached: falls back to 6-hex id
    db._SID_BY_THREAD[-424242] = "01KVQGK3G01ZH0J9CQZBW3EFD3"
    assert db.session_pubid(-424242) == "01KVQGK3G01ZH0J9CQZBW3EFD3"  # cached: ULID
    assert db.session_sid(-424242) == wid  # `session_sid` stays 6-hex, never the cache
    db._SID_BY_THREAD.pop(-424242, None)


def test_allocate_names_workdir_by_ulid(tmp_path):
    # A new session's workdir is named by the public ULID.
    # - same as the `sid` column and the UI id
    # - not the legacy 6-hex `session_sid`
    async def _t():
        # `tmp_path` auto-cleans, unlike `tempfile.mktemp` which leaks.
        await db.init_db(str(tmp_path / "alloc.db"))
        base = str(tmp_path / "base")
        key = await db.allocate_dm_session(7, "n", "opus", base, mode="code")
        cur = await db._conn.execute(
            "SELECT sid, cwd FROM threads WHERE thread_id=?", (key,))
        row = await cur.fetchone()
        await cur.close()
        await db.close_db()
        return key, row["sid"], row["cwd"]
    key, sid, cwd = _run(_t)
    assert len(sid) == 26 and all(c in db._CROCKFORD for c in sid)  # public id = ULID
    assert cwd.endswith(sid + "/work")                      # workdir on the ULID
    assert not cwd.endswith(db.session_sid(key) + "/work")  # not the legacy 6-hex
    assert db._SID_BY_THREAD.get(key) == sid                # cached as the public id
    assert db.session_pubid(key) == sid


def test_migrate_backfills_public_ulid_db_only_and_idempotent(tmp_path):
    # A legacy row with no sid gets a backfilled ULID.
    # - database only; the cwd is unchanged
    # - a second run is a no-op
    async def _t():
        # `tmp_path` auto-cleans, unlike `tempfile.mktemp` which leaks.
        await db.init_db(str(tmp_path / "backfill.db"))
        base = str(tmp_path / "base")
        key = await db.allocate_dm_session(7, "n", "opus", base, mode="chat")
        row0 = await (await db._conn.execute(
            "SELECT cwd FROM threads WHERE thread_id=?", (key,))).fetchone()
        cwd_before = row0["cwd"]
        await db._conn.execute("UPDATE threads SET sid=NULL WHERE thread_id=?", (key,))
        await db._conn.commit()
        db._SID_BY_THREAD.pop(key, None)
        n1 = await db.migrate_sessions_to_ulid(base)
        await db.load_sid_cache()
        cur = await db._conn.execute(
            "SELECT sid, cwd FROM threads WHERE thread_id=?", (key,))
        row = await cur.fetchone()
        await cur.close()
        n2 = await db.migrate_sessions_to_ulid(base)
        await db.close_db()
        return key, n1, n2, row["sid"], row["cwd"], cwd_before
    key, n1, n2, sid, cwd, cwd_before = _run(_t)
    assert n1 == 1 and n2 == 0
    assert len(sid) == 26 and all(c in db._CROCKFORD for c in sid)  # backfilled public ULID
    assert cwd == cwd_before  # cwd unchanged: DB-only migration
    # The workdir is ULID-named at allocation.
    # - the DB-only backfill never touches cwd
    # - cwd still ends in the 26-char ULID dir
    assert len(Path(cwd).parent.name) == 26
    assert db._SID_BY_THREAD.get(key) == sid


def test_migrate_workdirs_to_ulid_renames_reencodes_rekeys_idempotent(tmp_path):
    # Workdir migration renames legacy 6-hex dirs to the ULID.
    # - re-encodes the transcript dir so `resume` survives
    # - re-keys the `session_uid` registry and realigns cwd
    # - skips already-ULID sessions; idempotent
    def _enc(p):
        return re.sub(r"[^A-Za-z0-9]", "-", str(p))

    async def _t():
        # `tmp_path` auto-cleans, unlike `tempfile.mktemp` which leaks.
        await db.init_db(str(tmp_path / "workdirs.db"))
        base = tmp_path / "base"
        # A legacy session: allocate, force the 6-hex layout, repoint cwd.
        key = await db.allocate_dm_session(7, "n", "opus", str(base), mode="code")
        ulid = db.session_pubid(key)
        legacy = db._derive_sid(key)
        work = base / legacy / "work"
        work.mkdir(parents=True)
        (work / "f.txt").write_text("x")
        tx = base / legacy / "state" / _enc(work)
        tx.mkdir(parents=True)
        (tx / "t.jsonl").write_text("{}")
        await db._conn.execute("UPDATE threads SET cwd=? WHERE thread_id=?", (str(work), key))
        await db._conn.execute("INSERT INTO session_uid (sid, uid) VALUES (?,?)", (legacy, 700123))
        await db._conn.commit()
        # An already-ULID session must be left untouched.
        key2 = await db.allocate_dm_session(7, "m", "opus", str(base), mode="chat")
        cwd2_before = (await db.get_thread(key2)).cwd

        n1 = await db.migrate_workdirs_to_ulid(str(base))
        n2 = await db.migrate_workdirs_to_ulid(str(base))   # second run is a no-op

        st = await db.get_thread(key)
        new_uid = await (await db._conn.execute(
            "SELECT uid FROM session_uid WHERE sid=?", (ulid,))).fetchone()
        old_uid = await (await db._conn.execute(
            "SELECT uid FROM session_uid WHERE sid=?", (legacy,))).fetchone()
        cwd2_after = (await db.get_thread(key2)).cwd
        await db.close_db()
        new_work = base / ulid / "work"
        new_tx = base / ulid / "state" / _enc(new_work) / "t.jsonl"
        return dict(
            n1=n1, n2=n2, cwd=st.cwd, expect=str(new_work),
            new_work=new_work.exists(), old_gone=not (base / legacy).exists(),
            new_tx=new_tx.exists(), new_uid=(new_uid["uid"] if new_uid else None),
            old_uid_gone=(old_uid is None), cwd2_same=(cwd2_after == cwd2_before))

    r = _run(_t)
    assert r["n1"] == 1 and r["n2"] == 0            # legacy one migrated; re-run idempotent
    assert r["cwd"] == r["expect"]                  # cwd realigned to the ULID path
    assert r["new_work"] and r["old_gone"]          # dir renamed from 6-hex to ULID
    assert r["new_tx"]                              # transcript re-encoded under ULID path
    assert r["new_uid"] == 700123 and r["old_uid_gone"]  # `session_uid` re-keyed, old key dropped
    assert r["cwd2_same"]                           # already-ULID session untouched
