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
        assert sc.cwd.endswith(str(code))  # per-session working dir
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
