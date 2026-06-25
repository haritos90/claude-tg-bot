"""Unit tests for the db layer (#12).

Each test runs against a fresh temp SQLite file. We drive the async API with
asyncio.run() inside sync test functions, resetting the module-level connection
+ lock first so each test gets its own connection bound to its own event loop —
this avoids needing pytest-asyncio (and the cross-loop lock reuse it would risk).
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
        # #140: per-session working dir is named by the public id, not the key.
        # #181: nested layout — the cwd is <id>/work (state is the sibling).
        # #332: that public id is the ULID (was the 6-hex session_sid).
        # was: assert sc.cwd.endswith(str(code))                 # pre-#140
        # was: assert sc.cwd.endswith(db.session_sid(code))       # pre-#181
        # was: assert sc.cwd.endswith(db.session_sid(code)+"/work")  # pre-#332 (6-hex)
        assert sc.cwd.endswith(db.session_pubid(code) + "/work")
        assert sh.cwd.endswith(db.session_pubid(chat) + "/work")
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


def test_session_name_auto_then_manual_pin(tmp_path):
    # #260: a new session is auto-namable; the auto-namer (manual=False) writes the
    # label and leaves name_auto on; a manual /rename (manual=True) pins the name and
    # turns auto OFF, after which the auto-namer is a no-op.
    async def _t():
        # #292: tmp_path (pytest auto-cleans) instead of tempfile.mktemp (leaks .db files).
        await db.init_db(str(tmp_path / "names.db"))
        k = await db.allocate_dm_session(1, "s", "m", "/tmp", mode="code")
        st = await db.get_thread(k)
        assert st.name_auto is True          # default: auto on
        await db.set_session_name(k, "Auto title", manual=False)
        st = await db.get_thread(k)
        assert st.name == "Auto title" and st.name_auto is True
        # #345: a LATER auto write (the agent's ai-title) overrides an earlier auto name
        # (the #345 message fallback) while still auto — i.e. agent name > fallback.
        await db.set_session_name(k, "Better auto title", manual=False)
        st = await db.get_thread(k)
        assert st.name == "Better auto title" and st.name_auto is True
        await db.set_session_name(k, "My name")   # manual /rename (default)
        st = await db.get_thread(k)
        assert st.name == "My name" and st.name_auto is False
        await db.set_session_name(k, "Late auto", manual=False)  # no-op once pinned
        st = await db.get_thread(k)
        assert st.name == "My name"
        await db.close_db()

    _run(_t)


def test_browse_threads_surfaces_name_auto_for_gc_guard(tmp_path):
    # #334: the empty-session GC (_gc_untitled_empties) spares a MANUALLY-renamed session via
    # `r.get("name_auto", True)` — which only works if browse_threads actually RETURNS name_auto
    # in its page dicts. It was SELECTed but dropped from the dict, so the guard always saw the
    # default True and a renamed-but-empty session was wrongly reset + archived. Lock the field
    # in, and mirror the GC's candidate predicate to prove the renamed session is now spared.
    async def _t():
        await db.init_db(str(tmp_path / "gc.db"))
        uid = 5
        auto = await db.allocate_dm_session(uid, "Auto", "m", "/tmp", mode="chat")
        named = await db.allocate_dm_session(uid, "Auto2", "m", "/tmp", mode="chat")
        await db.set_session_name(named, "My project")   # manual /rename → name_auto False
        page, _ = await db.browse_threads(uid, None, limit=100, offset=0)
        await db.close_db()
        return page, auto, named
    page, auto, named = _run(_t)
    by_id = {r["thread_id"]: r for r in page}
    # The field is surfaced and reflects the manual rename (KeyError here pre-#334).
    assert by_id[auto]["name_auto"] is True
    assert by_id[named]["name_auto"] is False
    # The GC's candidate filter (handlers `_gc_untitled_empties`) now spares the renamed one.
    keep = auto  # pretend `auto` is the current/target session, never a candidate
    cands = {r["thread_id"] for r in page
             if r["thread_id"] != keep and r["thread_id"] < 0
             and not r.get("favorite") and r.get("name_auto", True)}
    assert named not in cands   # manually-renamed empty session is NOT collected by the GC
    assert auto not in cands    # the kept/current session is never a candidate either


def test_last_active_and_idle_rotation_keeps_messages(tmp_path):
    # #261: last_active roundtrips; rotate_session_for_idle drops the resume ids but
    # keeps the message log + cwd (unlike reset_thread, which wipes messages).
    async def _t():
        # #292: tmp_path (pytest auto-cleans) instead of tempfile.mktemp (leaks .db files).
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
        # #278: the legacy/added 'default' permission mode is migrated to the acceptEdits
        # baseline (so a code session auto-accepts file edits instead of prompting).
        assert st.permission_mode == "acceptEdits"
        assert st.big_memory is False
        assert st.stream_enabled is True
        assert st.favorite is False
        assert st.fork_pending is False
        assert st.add_dirs == []
        await db.close_db()

    _run(_t)


def test_legacy_default_permission_mode_migrated_to_accept_edits(tmp_path):
    # #278: a code session stored with the legacy 'default' (ask-for-EVERY-tool) is
    # migrated to 'acceptEdits' on init, so file creation/edits stop prompting.
    async def _t():
        path = str(tmp_path / "perm.db")
        await db.init_db(path)
        await db._require_conn().execute(
            "INSERT INTO threads (thread_id, chat_id, mode, model, cwd, permission_mode, created_at) "
            "VALUES (-9, 7, 'code', 'm', '/tmp', 'default', 0)"
        )
        await db._require_conn().commit()
        await db.close_db()
        # Re-open → the data migration runs.
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
        # #293: raw metric ignores cache + model weight: 1000 + 100 = 1100.
        assert await db.get_user_usage_window(uid, measure="raw") == 1100
        # Units = 5.0 * (1000 + 5*100 + 1.25*200 + 0.1*10000)
        #       = 5.0 * (1000 + 500 + 250 + 1000) = 13750.
        assert await db.get_user_usage_window(uid) == 13750   # default measure = units
        # A NULL-model row weights at the default (Sonnet) baseline 1.0.
        await db.add_usage(key, {"input_tokens": 10, "output_tokens": 0}, 0.0)
        assert await db.get_user_usage_window(uid) == 13750 + 10
        bd = await db.get_user_breakdown(uid, "units")
        assert bd["day"] == 13760 and bd["week"] == 13760 and bd["total"] == 13760
        # The raw breakdown over the same rows: 1100 + 10 = 1110, 2 requests.
        rawbd = await db.get_user_breakdown(uid)   # default measure = raw
        assert rawbd["total"] == 1110 and rawbd["requests"] == 2
        # A different user sees none of it.
        assert await db.get_user_usage_window(999) == 0
        await db.close_db()

    _run(_t)


def test_usage_survives_session_delete(tmp_path):
    """#309: a user's token usage must OUTLIVE deleting the session it was spent in —
    it still feeds their lifetime totals + rolling-limit windows (keyed by chat_id), so
    deleting a session can't silently shrink recorded spend or dodge the caps."""
    async def _t():
        # #337: tmp_path (pytest auto-cleans) instead of tempfile.mktemp (leaks .db files).
        await db.init_db(str(tmp_path / "usage.db"))
        uid = 7
        key = await db.allocate_dm_session(uid, "s", "m", "/tmp", mode="code")
        await db.add_usage(key, {"input_tokens": 1000, "output_tokens": 100}, 0.0)
        # Baseline: the spend is attributed to the user across all three aggregations.
        assert await db.get_user_usage_window(uid, measure="raw") == 1100
        assert (await db.get_user_breakdown(uid))["total"] == 1100
        assert any(r["uid"] == uid for r in await db.get_all_users_breakdown())
        # Delete the session the usage was spent in.
        assert await db.delete_dm_session(uid, key) is True
        assert await db.get_thread(key) is None            # session gone…
        # …but the usage still counts toward the user's totals + rolling window.
        assert await db.get_user_usage_window(uid, measure="raw") == 1100
        bd = await db.get_user_breakdown(uid)
        assert bd["total"] == 1100 and bd["requests"] == 1
        assert any(r["uid"] == uid for r in await db.get_all_users_breakdown())
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


def test_user_last_active_roundtrip_default_zero():
    # #329: per-USER idle clock (not per-session) — defaults to 0, set/get roundtrips durably.
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
    # #327: 26-char Crockford base32, collision-free, timestamp prefix monotonic (sortable).
    ids = [db.new_ulid() for _ in range(64)]
    assert all(len(u) == 26 for u in ids)
    assert all(c in db._CROCKFORD for u in ids for c in u)
    assert len(set(ids)) == 64
    prefixes = [u[:10] for u in ids]                 # the 48-bit ms timestamp portion
    assert prefixes == sorted(prefixes)              # generated in time order → non-decreasing


def test_session_sid_is_6hex_and_pubid_uses_cache():
    # #327 (decoupled): session_sid is ALWAYS the stable 6-hex workdir id; session_pubid is the
    # public ULID from the cache (falling back to the 6-hex id when not yet backfilled).
    db._SID_BY_THREAD.pop(-424242, None)
    wid = db.session_sid(-424242)
    assert len(wid) == 6 and all(c in "0123456789abcdef" for c in wid)
    assert db.session_pubid(-424242) == wid  # uncached → falls back to the 6-hex id
    db._SID_BY_THREAD[-424242] = "01KVQGK3G01ZH0J9CQZBW3EFD3"
    assert db.session_pubid(-424242) == "01KVQGK3G01ZH0J9CQZBW3EFD3"  # cached → ULID
    assert db.session_sid(-424242) == wid  # session_sid stays the 6-hex id (never the cache)
    db._SID_BY_THREAD.pop(-424242, None)


def test_allocate_names_workdir_by_ulid(tmp_path):
    # #332: a new session's WORKDIR is named by the PUBLIC ULID (= the sid column = the id shown
    # in the UI), NOT the legacy 6-hex session_sid. was: test_allocate_public_ulid_but_workdir_
    # stays_6hex (the #327-decoupled, pre-#332 behaviour).
    async def _t():
        # #337: tmp_path (pytest auto-cleans) instead of tempfile.mktemp/mkdtemp (leaks).
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
    assert cwd.endswith(sid + "/work")                      # #332: workdir on the ULID
    assert not cwd.endswith(db.session_sid(key) + "/work")  # NOT the legacy 6-hex
    assert db._SID_BY_THREAD.get(key) == sid                # cached as the public id
    assert db.session_pubid(key) == sid


def test_migrate_backfills_public_ulid_db_only_and_idempotent(tmp_path):
    # #327 (decoupled): a legacy row (no stored sid) is backfilled with a public ULID — DB ONLY, the
    # cwd/workdir is UNCHANGED. A 2nd run is a no-op.
    async def _t():
        # #337: tmp_path (pytest auto-cleans) instead of tempfile.mktemp/mkdtemp (leaks).
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
    assert cwd == cwd_before  # cwd UNCHANGED — migrate_sessions_to_ulid is DB-only
    # #332: the workdir is ULID-named at allocation; the DB-only ULID backfill never touches the
    # cwd, so it still ends in the allocate-time ULID dir (a 26-char id).
    assert len(Path(cwd).parent.name) == 26
    assert db._SID_BY_THREAD.get(key) == sid


def test_migrate_workdirs_to_ulid_renames_reencodes_rekeys_idempotent(tmp_path):
    # #332: migrate_workdirs_to_ulid renames a legacy 6-hex workdir to the ULID, re-encodes the
    # nested transcript dir (so `resume` survives), re-keys the session_uid registry, realigns
    # cwd, SKIPS an already-ULID session, and is idempotent.
    def _enc(p):
        return re.sub(r"[^A-Za-z0-9]", "-", str(p))

    async def _t():
        # #337: tmp_path (pytest auto-cleans) instead of tempfile.mktemp/mkdtemp (leaks).
        await db.init_db(str(tmp_path / "workdirs.db"))
        base = tmp_path / "base"
        # A legacy session: allocate, then force its on-disk layout to the 6-hex name (simulating
        # a pre-#332 session) and repoint cwd at it.
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
        # An already-ULID session (born ULID-named per #332) must be left untouched.
        key2 = await db.allocate_dm_session(7, "m", "opus", str(base), mode="chat")
        cwd2_before = (await db.get_thread(key2)).cwd

        n1 = await db.migrate_workdirs_to_ulid(str(base))
        n2 = await db.migrate_workdirs_to_ulid(str(base))   # idempotency

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
    assert r["n1"] == 1 and r["n2"] == 0            # migrated the legacy one; idempotent re-run
    assert r["cwd"] == r["expect"]                  # cwd realigned to the ULID path
    assert r["new_work"] and r["old_gone"]          # dir renamed 6hex -> ULID
    assert r["new_tx"]                              # transcript re-encoded under the ULID path
    assert r["new_uid"] == 700123 and r["old_uid_gone"]  # session_uid re-keyed, old key dropped
    assert r["cwd2_same"]                           # the already-ULID session was untouched
