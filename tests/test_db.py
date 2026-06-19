"""Unit tests for the db layer (#12).

Each test runs against a fresh temp SQLite file. We drive the async API with
asyncio.run() inside sync test functions, resetting the module-level connection
+ lock first so each test gets its own connection bound to its own event loop —
this avoids needing pytest-asyncio (and the cross-loop lock reuse it would risk).
"""

import asyncio
import tempfile

import db


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
        # #140: per-session working dir is named by the public sid, not the key.
        # #181: nested layout — the cwd is <sid>/work (state is the sibling).
        # was: assert sc.cwd.endswith(str(code))            # pre-#140
        # was: assert sc.cwd.endswith(db.session_sid(code))  # pre-#181
        assert sc.cwd.endswith(db.session_sid(code) + "/work")
        assert sh.cwd.endswith(db.session_sid(chat) + "/work")
        await db.close_db()

    _run(_t)


def test_user_default_roundtrip_and_clear():
    """#138 USER-scope storage: set/get a per-user default (JSON-encoded in kv),
    None clears it, and a garbled value degrades to None."""
    async def _t():
        await db.init_db(tempfile.mktemp(suffix=".db"))
        assert await db.get_user_default(7, "model") is None
        await db.set_user_default(7, "model", "claude-sonnet-4-6")
        assert await db.get_user_default(7, "model") == "claude-sonnet-4-6"
        # Non-string JSON values round-trip too (bool/int).
        await db.set_user_default(7, "memory", True)
        assert await db.get_user_default(7, "memory") is True
        # Isolated per uid.
        assert await db.get_user_default(8, "model") is None
        # Clearing deletes the row → back to None.
        await db.set_user_default(7, "model", None)
        assert await db.get_user_default(7, "model") is None
        # Garbled raw value degrades to None.
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
        await db.append_rate_history("seven_day", None, "allowed")  # None tolerated
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
    # A db that predates the post-release columns (only the original minimal
    # `threads` schema) must be migrated in place by init_db's guarded ALTER
    # block — get_thread should then return the newer fields at their defaults.
    async def _t():
        import aiosqlite

        path = tempfile.mktemp(suffix=".db")
        # Build a fresh db with ONLY the original minimal schema + one row.
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

        # Migrate the existing file and read the row back through get_thread.
        await db.init_db(path)
        st = await db.get_thread(-1)
        assert st is not None
        assert st.permission_mode == "default"
        assert st.big_memory is False
        assert st.stream_enabled is True
        assert st.favorite is False
        assert st.fork_pending is False
        assert st.add_dirs == []
        await db.close_db()

    _run(_t)


def test_favorite_flag_persists_and_sorts_first():
    async def _t():
        await db.init_db(tempfile.mktemp(suffix=".db"))
        a = await db.allocate_dm_session(7, "old", "m", "/tmp/wd")
        b = await db.allocate_dm_session(7, "new", "m", "/tmp/wd")
        # Default: not favorite; newest (b) listed first.
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


def test_usage_units_weighting_and_breakdown():
    """#165: weighted usage units bill model weight + output + cache, not just raw
    input+output, and the breakdown rolls up by the user's DM chat_id."""
    async def _t():
        await db.init_db(tempfile.mktemp(suffix=".db"))
        uid = 5
        key = await db.allocate_dm_session(uid, "s", "claude-opus-4-8", "/tmp", mode="code")
        # One Opus turn: input 1000, output 100, cache_creation 200, cache_read 10000.
        await db.add_usage(
            key,
            {"input_tokens": 1000, "output_tokens": 100,
             "cache_creation_input_tokens": 200, "cache_read_input_tokens": 10000},
            0.0, model="claude-opus-4-8", context_tokens=42000,
        )
        # Raw metric ignores cache + model weight: 1000 + 100 = 1100.
        assert await db.get_user_usage_tokens(uid) == 1100
        # Units = 5.0 * (1000 + 5*100 + 1.25*200 + 0.1*10000)
        #       = 5.0 * (1000 + 500 + 250 + 1000) = 13750.
        assert await db.get_user_usage_units(uid) == 13750
        # A NULL-model row weights at the default (Sonnet) baseline 1.0.
        await db.add_usage(key, {"input_tokens": 10, "output_tokens": 0}, 0.0)
        assert await db.get_user_usage_units(uid) == 13750 + 10
        bd = await db.get_user_units_breakdown(uid)
        assert bd["day"] == 13760 and bd["week"] == 13760 and bd["total"] == 13760
        # A different user sees none of it.
        assert await db.get_user_usage_units(999) == 0
        await db.close_db()

    _run(_t)


def test_claim_session_uid_stable_and_collision_free():
    """#221: the host-uid registry hands out the preferred hash uid when free, the SAME
    uid on repeat (stability), a DIFFERENT uid when two sids' hashes collide, and reuses
    a freed slot after release."""
    async def _t():
        await db.init_db(tempfile.mktemp(suffix=".db"))
        lo, hi = 700000, 700000 + 60000
        # preferred free → returns preferred, and is STABLE across calls.
        u1 = await db.claim_session_uid("aaaaaa", 700005, lo, hi)
        assert u1 == 700005
        assert await db.claim_session_uid("aaaaaa", 700005, lo, hi) == 700005
        # DIFFERENT sids with the SAME preferred must each get a DISTINCT uid (probe).
        u2 = await db.claim_session_uid("bbbbbb", 700005, lo, hi)
        u3 = await db.claim_session_uid("cccccc", 700005, lo, hi)
        assert len({u1, u2, u3}) == 3
        assert all(lo <= u < hi for u in (u2, u3))
        # release frees u1's slot → the next colliding sid reuses it.
        await db.release_session_uid("aaaaaa")
        assert await db.claim_session_uid("dddddd", 700005, lo, hi) == 700005
        await db.close_db()

    _run(_t)


def test_claim_session_uid_exhaustion_falls_back():
    """#221: when the whole window is taken, fall back to the clamped preferred rather
    than fail the session (collisions become possible again only here)."""
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
    """#221 doctor: group sids by uid, report only uids shared by >1 sid."""
    assert db._uid_collisions({"a": 700001, "b": 700002}) == {}
    assert db._uid_collisions({"a": 700001, "b": 700001, "c": 700002}) == {700001: ["a", "b"]}
    assert db._uid_collisions({}) == {}
    # #232: uid 0 (root) is the no-jail / unassigned default, never a collision — even
    # when shared by >1 sid it must be excluded (added in #231).
    assert db._uid_collisions({"a": 0, "b": 0}) == {}
    assert db._uid_collisions({"a": 0, "b": 0, "c": 700001, "d": 700001}) == {700001: ["c", "d"]}


def test_sandbox_uid_collisions_scan():
    """#221 doctor: two work dirs sharing an owner are reported; dirs without a work
    subdir and non-dir entries are skipped; a lone session is clean."""
    import os

    base = tempfile.mkdtemp()
    os.makedirs(os.path.join(base, "sidA", "work"))
    os.makedirs(os.path.join(base, "sidB", "work"))  # same owner (test uid) → collide
    os.makedirs(os.path.join(base, "sidC"))          # no work dir → skipped
    with open(os.path.join(base, "loose.txt"), "w") as fh:
        fh.write("x")                                # not a dir → skipped
    # was: assert db.sandbox_uid_collisions(base) == {os.getuid(): ["sidA", "sidB"]}
    #   — replaced for #232. The work dirs are owned by the test process's uid; under the
    #   #231 root-exclusion that owner only counts as a collision when it is NON-root. On a
    #   root host (this VPS runs as uid 0) the scan now correctly returns {}, so branch.
    if os.getuid() == 0:
        assert db.sandbox_uid_collisions(base) == {}     # root owner excluded (#231)
    else:
        assert db.sandbox_uid_collisions(base) == {os.getuid(): ["sidA", "sidB"]}

    solo = tempfile.mkdtemp()
    os.makedirs(os.path.join(solo, "sidX", "work"))
    assert db.sandbox_uid_collisions(solo) == {}
