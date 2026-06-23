"""aiosqlite-based per-thread persistent state.

A single module-level connection is opened by init_db and reused by all
helpers. Access is serialized with an asyncio.Lock so concurrent handlers
never interleave on the same connection. Each forum topic (thread_id, with 0
representing the General topic) keeps its own isolated row of state plus a log
of usage records for accounting.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

import aiosqlite

logger = logging.getLogger("db")

# Module-level connection + serialization lock. Set by init_db().
_conn: aiosqlite.Connection | None = None
_lock = None  # type: ignore[assignment]  # lazily created asyncio.Lock in init_db


# #327 (decoupled): two ids per session. session_sid() is the INTERNAL stable workdir id (6-hex
# sha1) naming the on-disk workdir / transcript / jail-uid / secrets — it must NEVER move (resume
# is cwd-keyed). session_pubid() is the PUBLIC id shown in the UI: a stored ULID read from this
# cache (backfilled by migrate_sessions_to_ulid, set on create). The filesystem stays on the 6-hex
# id, so adding the ULID is a pure DB/display change that can't break resume.
_SID_BY_THREAD: dict[int, str] = {}  # thread_id -> public ULID

# Crockford base32 (no I, L, O, U) — the ULID alphabet.
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid() -> str:
    """#327: a ULID — 26-char Crockford base32, lexicographically time-sortable (48-bit ms
    timestamp in the high bits + 80-bit randomness). Fixed length, opaque, collision-resistant;
    no external dependency."""
    val = ((int(time.time() * 1000) & ((1 << 48) - 1)) << 80) | int.from_bytes(os.urandom(10), "big")
    out = bytearray(26)
    for i in range(25, -1, -1):
        out[i] = ord(_CROCKFORD[val & 0x1F])
        val >>= 5
    return out.decode("ascii")


def _derive_sid(thread_id: int) -> str:
    """The LEGACY derived sid (`sha1[:6]`) — used to locate a session's OLD on-disk name during the
    #327 migration, and as a transitional fallback for a thread not yet in the ULID cache."""
    return hashlib.sha1(f"sess:{thread_id}".encode()).hexdigest()[:6]


def session_sid(thread_id: int) -> str:
    """INTERNAL stable workdir id — the 6-hex `sha1[:6]`. Names the on-disk workdir / transcript /
    jail-uid / secrets, which must NEVER move (resume is cwd-keyed), so it is purely derived and
    never changes. NOT user-facing — the PUBLIC id is session_pubid() (#327)."""
    return _derive_sid(thread_id)


def session_pubid(thread_id: int) -> str:
    """#327: the PUBLIC session id shown in the UI — a stored ULID (opaque, fixed-length, time-
    sortable) from the cache (backfilled by migrate_sessions_to_ulid / set on create). Falls back to
    the 6-hex workdir id for a thread not yet backfilled."""
    return _SID_BY_THREAD.get(thread_id) or session_sid(thread_id)


@dataclass
class ThreadState:
    thread_id: int
    chat_id: int
    mode: str
    model: str
    cwd: str
    code_session_id: str | None
    name: str | None
    permission_mode: str = "acceptEdits"
    # Resumable chat-mode session id (persisted every chat turn). Resumed on
    # rebuild only when big_memory is on, so important topics survive restarts.
    chat_session_id: str | None = None
    # Per-topic "big memory": 1M context window in chat + durable chat session.
    big_memory: bool = False
    created_at: float = 0.0
    created_by: int | None = None
    # Live-streaming display preference (persisted so /stream survives restart).
    stream_enabled: bool = True
    # Pro-command per-session options (#23).
    effort: str | None = None
    max_turns: int | None = None
    add_dirs: list[str] = field(default_factory=list)
    fork_pending: bool = False
    # Favorite/pinned session — sorted first in /sessions so important ones are
    # easy to find without searching.
    favorite: bool = False
    # Owner-only per-session sandbox OPT-OUT (#104): when True, this code session's
    # claude runs WITHOUT the bubblewrap jail even if SANDBOX_CODE is on, so the
    # owner can compare sandboxed vs raw behaviour. Guests can never set it.
    no_sandbox: bool = False
    # #224: shell-mode overlay — a code session whose text messages route to a one-shot
    # command in its jail instead of the model. NOT a mode change (stays "code").
    shell_mode: bool = False
    # Per-session enabled tools (#129): None = the mode's full default universe
    # (chat → web tools, code → all); a list = exactly those (``[]`` = tool-free).
    tools_enabled: list[str] | None = None
    # #164: post-reply 5-min warm-cache note (delegated; user-toggleable) and SDK
    # auto-compaction (hidden/owner-only for now). See settings_schema + TODO #164.
    hot_cache_timer: bool = False
    auto_compact: bool = False
    # #229: live task-list card from the agent's TodoWrite events (delegated, code-only,
    # default OFF). See settings_schema + streamer.update_todo_card.
    todo_card: bool = False
    # #260: True (default) = auto-adopt Claude Code's transcript ai-title as the session
    # label; a manual /rename pins the name and clears this. See set_session_name.
    name_auto: bool = True
    # #261: epoch seconds of the last finished turn (durable last-activity); 0 = never ran.
    # Drives the idle-rotation-to-fresh-session check on the next message.
    last_active: float = 0.0


def _require_conn() -> aiosqlite.Connection:
    """Return the live connection or raise if init_db was never called."""
    if _conn is None:
        raise RuntimeError("db not initialized: call init_db() first")
    return _conn


async def init_db(db_path: str) -> None:
    """Open the connection and create tables if absent, then commit."""
    global _conn, _lock
    import asyncio

    if _lock is None:
        _lock = asyncio.Lock()

    if _conn is None:
        _conn = await aiosqlite.connect(db_path)
        _conn.row_factory = aiosqlite.Row
        # Enable WAL once: concurrent reads never block the single writer, and
        # synchronous=NORMAL is the safe/fast pairing for WAL. Best-effort — a
        # failure (e.g. a filesystem that can't do WAL) must not crash init.
        try:
            await _conn.execute("PRAGMA journal_mode=WAL")
            await _conn.execute("PRAGMA synchronous=NORMAL")
            # #332: wait up to 5s for a lock instead of erroring instantly, so a second
            # writer touching the file (backup tool, stray poller, watchdog) gets a brief
            # queue rather than an immediate "database is locked".
            await _conn.execute("PRAGMA busy_timeout=5000")
        except aiosqlite.Error:
            pass

    async with _lock:
        await _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS threads (
                thread_id INTEGER PRIMARY KEY,
                chat_id INTEGER,
                mode TEXT,
                model TEXT,
                cwd TEXT,
                code_session_id TEXT,
                name TEXT,
                created_at REAL
            )
            """
        )
        await _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id INTEGER,
                chat_id INTEGER,
                ts REAL,
                input_tokens INTEGER,
                output_tokens INTEGER,
                cache_read INTEGER,
                cache_creation INTEGER,
                cost_usd REAL
            )
            """
        )
        await _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kv (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        # Per-session conversation log (feeds /recap + /history). Stores the
        # prompt/response text the bot would otherwise never keep.
        await _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id INTEGER,
                ts REAL,
                role TEXT,
                text TEXT
            )
            """
        )
        await _conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id, id)"
        )
        # #285: the append-only `usage` table had NO index — every usage aggregate
        # (session stats, /users units, rate-limit window checks) full-scanned it, and it
        # grows forever. Index by (thread_id, ts) so per-thread + time-window scans are
        # range scans. Also index threads.chat_id (the per-user filter/join column used by
        # browse_threads and every per-user usage join).
        await _conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_usage_thread_ts ON usage(thread_id, ts)"
        )
        # #309: idx_usage_chat_ts is created LATER, in the migration block, AFTER the
        # chat_id column is guaranteed to exist — on an existing db the column is added by
        # an ALTER there, so an index here would hit "no such column: chat_id".
        await _conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_threads_chat ON threads(chat_id)"
        )
        # #188: recurring scheduled prompts. spec = JSON (schedules.parse_schedule); the
        # runner loop (sessions._schedule_loop) fires due+enabled rows into their session.
        await _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id INTEGER,
                chat_id INTEGER,
                owner_uid INTEGER,
                spec TEXT,
                prompt TEXT,
                next_run REAL,
                enabled INTEGER DEFAULT 1,
                created_at REAL,
                last_run REAL,
                last_status TEXT
            )
            """
        )
        await _conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_schedules_due ON schedules(enabled, next_run)"
        )
        # Append-only subscription rate-limit history (feeds the /status trend).
        await _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rate_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL,
                rate_type TEXT,
                utilization REAL,
                status TEXT
            )
            """
        )
        # #221: per-session host-uid registry — maps each session's sid to a UNIQUE
        # unprivileged host uid for its sandbox. The engine prefers the deterministic
        # hash uid but probes to a free one on collision and records it here, so two
        # sessions never share a uid (which would break per-session FS isolation).
        await _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_uid (
                sid TEXT PRIMARY KEY,
                uid INTEGER NOT NULL UNIQUE
            )
            """
        )
        # Migrate threads: add any columns introduced after the first release.
        cur = await _conn.execute("PRAGMA table_info(threads)")
        columns = await cur.fetchall()
        await cur.close()
        existing = {col["name"] for col in columns}
        if "permission_mode" not in existing:
            await _conn.execute(
                "ALTER TABLE threads ADD COLUMN permission_mode TEXT DEFAULT 'acceptEdits'"
            )
        # #327: stored PUBLIC session id (a ULID); backfilled by migrate_sessions_to_ulid.
        if "sid" not in existing:
            await _conn.execute("ALTER TABLE threads ADD COLUMN sid TEXT")
            await _conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_threads_sid ON threads(sid)"
            )
        if "chat_session_id" not in existing:
            await _conn.execute("ALTER TABLE threads ADD COLUMN chat_session_id TEXT")
        if "big_memory" not in existing:
            await _conn.execute(
                "ALTER TABLE threads ADD COLUMN big_memory INTEGER DEFAULT 0"
            )
        if "created_by" not in existing:
            await _conn.execute("ALTER TABLE threads ADD COLUMN created_by INTEGER")
        if "stream_enabled" not in existing:
            await _conn.execute(
                "ALTER TABLE threads ADD COLUMN stream_enabled INTEGER DEFAULT 1"
            )
        # Pro-command per-session options (#23): reasoning effort, agentic turn
        # cap, extra code dirs (JSON list), and a one-shot "fork on next turn" flag.
        if "effort" not in existing:
            await _conn.execute("ALTER TABLE threads ADD COLUMN effort TEXT")
        if "max_turns" not in existing:
            await _conn.execute("ALTER TABLE threads ADD COLUMN max_turns INTEGER")
        if "add_dirs" not in existing:
            await _conn.execute("ALTER TABLE threads ADD COLUMN add_dirs TEXT")
        if "fork_pending" not in existing:
            await _conn.execute(
                "ALTER TABLE threads ADD COLUMN fork_pending INTEGER DEFAULT 0"
            )
        if "favorite" not in existing:
            await _conn.execute(
                "ALTER TABLE threads ADD COLUMN favorite INTEGER DEFAULT 0"
            )
        if "no_sandbox" not in existing:
            await _conn.execute(
                "ALTER TABLE threads ADD COLUMN no_sandbox INTEGER DEFAULT 0"
            )
        # #224: shell-mode overlay for code sessions (routes text → jailed command).
        if "shell_mode" not in existing:
            await _conn.execute(
                "ALTER TABLE threads ADD COLUMN shell_mode INTEGER DEFAULT 0"
            )
        # Per-session enabled-tools list (#129): JSON array, or NULL = mode default
        # (chat → web tools, code → all). Distinct from [] which means tool-free.
        if "tools_enabled" not in existing:
            await _conn.execute("ALTER TABLE threads ADD COLUMN tools_enabled TEXT")
        # #164: warm-cache note toggle + SDK auto-compaction toggle (per session).
        if "hot_cache_timer" not in existing:
            await _conn.execute(
                "ALTER TABLE threads ADD COLUMN hot_cache_timer INTEGER DEFAULT 0"
            )
        if "auto_compact" not in existing:
            await _conn.execute(
                "ALTER TABLE threads ADD COLUMN auto_compact INTEGER DEFAULT 0"
            )
        # #229: per-session live task-list card toggle.
        if "todo_card" not in existing:
            await _conn.execute(
                "ALTER TABLE threads ADD COLUMN todo_card INTEGER DEFAULT 0"
            )
        # #260: auto-naming flag. 1 (default) = adopt Claude Code's own ai-title from
        # the transcript as the session label; a manual /rename pins the name and
        # flips this to 0 so the auto-namer stops touching it.
        if "name_auto" not in existing:
            await _conn.execute(
                "ALTER TABLE threads ADD COLUMN name_auto INTEGER DEFAULT 1"
            )
        # #261: wall-clock (epoch seconds) of the last finished turn. Read on the next
        # message to decide an idle-rotation to a fresh session; durable across restart
        # (unlike the in-memory monotonic last_activity the reaper uses). 0 = never ran.
        if "last_active" not in existing:
            await _conn.execute(
                "ALTER TABLE threads ADD COLUMN last_active REAL DEFAULT 0"
            )
        # #165: the per-turn MODEL and the live CONTEXT size are needed to compute the
        # weighted "usage units" metric (a cost-aware proxy for the official windows;
        # see get_user_usage_window). Older rows have NULL model / 0 context — they
        # simply weight as the default-model baseline with no context term.
        cur = await _conn.execute("PRAGMA table_info(usage)")
        ucols = {col["name"] for col in await cur.fetchall()}
        await cur.close()
        if "model" not in ucols:
            await _conn.execute("ALTER TABLE usage ADD COLUMN model TEXT")
        if "context_tokens" not in ucols:
            await _conn.execute(
                "ALTER TABLE usage ADD COLUMN context_tokens INTEGER DEFAULT 0"
            )
        # #309: usage is now owned by chat_id (the DM user / group), not just the thread, so
        # per-user totals + rolling-limit windows survive a session delete. Backfill existing
        # rows from their thread; a row whose thread is already gone stays NULL (unrecoverable
        # — it was already excluded from per-user totals by the old threads join).
        if "chat_id" not in ucols:
            await _conn.execute("ALTER TABLE usage ADD COLUMN chat_id INTEGER")
            await _conn.execute(
                "UPDATE usage SET chat_id = "
                "(SELECT th.chat_id FROM threads th WHERE th.thread_id = usage.thread_id) "
                "WHERE chat_id IS NULL"
            )
        # #309: index AFTER the column is guaranteed present (the ALTER above runs only on an
        # old db; on a fresh db chat_id comes from CREATE TABLE usage). Idempotent either way.
        await _conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_usage_chat_ts ON usage(chat_id, ts)"
        )
        # #278: the legacy permission_mode 'default' (pre-#212 = prompt for EVERY tool,
        # incl. file edits) is no longer a selectable mode — the #212 baseline is
        # 'acceptEdits' (the #119 jail is the containment layer). Migrate stale rows so a
        # code session auto-accepts file creation/edits instead of prompting.
        await _conn.execute(
            "UPDATE threads SET permission_mode = 'acceptEdits' "
            "WHERE permission_mode = 'default' OR permission_mode IS NULL"
        )
        await _conn.commit()


def _parse_dirs(raw) -> list[str]:
    """Parse the add_dirs JSON column to a list[str]; [] on missing/garbled."""
    if not raw:
        return []
    try:
        v = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return [str(x) for x in v] if isinstance(v, list) else []


def _parse_tools_enabled(raw):
    """Parse the tools_enabled JSON column to list[str] or None (#129). NULL → None
    (= the mode's full default tool set); a JSON list → that list (``[]`` = tool-free).
    A garbled value degrades to None (default) rather than silently disabling tools."""
    if raw is None:
        return None
    try:
        v = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return [str(x) for x in v] if isinstance(v, list) else None


async def get_thread(thread_id: int) -> ThreadState | None:
    """Return the stored state for a thread, or None if it does not exist."""
    conn = _require_conn()
    async with _lock:
        cur = await conn.execute(
            "SELECT thread_id, chat_id, mode, model, cwd, code_session_id, name, "
            "COALESCE(permission_mode, 'acceptEdits') AS permission_mode, "
            "chat_session_id, "
            "COALESCE(big_memory, 0) AS big_memory, "
            "COALESCE(created_at, 0) AS created_at, created_by, "
            "COALESCE(stream_enabled, 1) AS stream_enabled, "
            "effort, max_turns, add_dirs, COALESCE(fork_pending, 0) AS fork_pending, "
            "COALESCE(favorite, 0) AS favorite, "
            "COALESCE(no_sandbox, 0) AS no_sandbox, "
            "COALESCE(shell_mode, 0) AS shell_mode, "
            "tools_enabled, "
            "COALESCE(hot_cache_timer, 0) AS hot_cache_timer, "
            "COALESCE(auto_compact, 0) AS auto_compact, "
            "COALESCE(todo_card, 0) AS todo_card, "
            "COALESCE(name_auto, 1) AS name_auto, "
            "COALESCE(last_active, 0) AS last_active "
            "FROM threads WHERE thread_id = ?",
            (thread_id,),
        )
        row = await cur.fetchone()
        await cur.close()
    if row is None:
        return None
    return ThreadState(
        thread_id=row["thread_id"],
        chat_id=row["chat_id"],
        mode=row["mode"],
        model=row["model"],
        cwd=row["cwd"],
        code_session_id=row["code_session_id"],
        name=row["name"],
        permission_mode=row["permission_mode"],
        chat_session_id=row["chat_session_id"],
        big_memory=bool(row["big_memory"]),
        created_at=float(row["created_at"] or 0),
        created_by=row["created_by"],
        stream_enabled=bool(row["stream_enabled"]),
        effort=row["effort"],
        max_turns=row["max_turns"],
        add_dirs=_parse_dirs(row["add_dirs"]),
        fork_pending=bool(row["fork_pending"]),
        favorite=bool(row["favorite"]),
        no_sandbox=bool(row["no_sandbox"]),
        shell_mode=bool(row["shell_mode"]),
        tools_enabled=_parse_tools_enabled(row["tools_enabled"]),
        hot_cache_timer=bool(row["hot_cache_timer"]),
        auto_compact=bool(row["auto_compact"]),
        todo_card=bool(row["todo_card"]),
        name_auto=bool(row["name_auto"]),
        last_active=float(row["last_active"] or 0),
    )


async def ensure_thread(
    thread_id: int, chat_id: int, default_model: str, default_cwd: str
) -> ThreadState:
    """Insert the thread with mode='chat' if absent, then return its state."""
    existing = await get_thread(thread_id)
    if existing is not None:
        return existing

    conn = _require_conn()
    async with _lock:
        # Guard against a race where another coroutine inserted meanwhile.
        await conn.execute(
            """
            INSERT OR IGNORE INTO threads
                (thread_id, chat_id, mode, model, cwd, code_session_id, name, permission_mode, chat_session_id, big_memory, created_at)
            VALUES (?, ?, 'chat', ?, ?, NULL, NULL, 'acceptEdits', NULL, 0, ?)
            """,
            (thread_id, chat_id, default_model, default_cwd, time.time()),
        )
        await conn.commit()

    # Read back the authoritative row (handles the race cleanly).
    state = await get_thread(thread_id)
    assert state is not None  # just inserted (or pre-existing)
    return state


async def set_mode(thread_id: int, mode: str) -> None:
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET mode = ? WHERE thread_id = ?", (mode, thread_id)
        )
        await conn.commit()


async def switch_mode(thread_id: int, new_mode: str) -> None:
    """Change a session's TYPE and CARRY its conversation across the switch (#133):
    copy the resumable session id from the OLD mode's column into the NEW mode's, so
    chat↔code continue one conversation. Both modes now run in the per-session workdir
    (engine), so the transcript is findable from either. No-op if already new_mode."""
    st = await get_thread(thread_id)
    if st is None or st.mode == new_mode:
        return
    src_id = st.chat_session_id if st.mode == "chat" else st.code_session_id
    target_col = "code_session_id" if new_mode == "code" else "chat_session_id"
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET mode = ? WHERE thread_id = ?", (new_mode, thread_id)
        )
        if src_id:
            # target_col is a fixed literal (not user input) — safe to interpolate.
            await conn.execute(
                f"UPDATE threads SET {target_col} = ? WHERE thread_id = ?",
                (src_id, thread_id),
            )
        await conn.commit()


async def set_model(thread_id: int, model: str) -> None:
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET model = ? WHERE thread_id = ?", (model, thread_id)
        )
        await conn.commit()


async def set_session_name(thread_id: int, name: str, *, manual: bool = True) -> None:
    """Rename a session (the human label shown in /sessions).

    #260: ``manual=True`` (the /rename path) PINS the name and turns auto-naming OFF
    (``name_auto = 0``). ``manual=False`` is the auto-namer (Claude Code's transcript
    ai-title) and only writes WHILE still in auto mode — a no-op once the user has
    pinned a name, so a manual label is never clobbered."""
    conn = _require_conn()
    async with _lock:
        if manual:
            await conn.execute(
                "UPDATE threads SET name = ?, name_auto = 0 WHERE thread_id = ?",
                (name, thread_id),
            )
        else:
            await conn.execute(
                "UPDATE threads SET name = ? WHERE thread_id = ? AND name_auto = 1",
                (name, thread_id),
            )
        await conn.commit()


async def set_cwd(thread_id: int, cwd: str) -> None:
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET cwd = ? WHERE thread_id = ?", (cwd, thread_id)
        )
        await conn.commit()


async def set_last_active(thread_id: int, ts: float) -> None:
    """#261: stamp the wall-clock (epoch) time of the last finished turn — read on the
    next message to decide an idle-rotation. Durable across restart."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET last_active = ? WHERE thread_id = ?", (ts, thread_id)
        )
        await conn.commit()


async def get_user_last_active(user_id: int) -> float:
    """#329: the USER's overall last-active epoch time (across ALL their sessions). Idle rotation
    keys off the user's inactivity gap, NOT any single session's age — so a month-old session is
    fine to continue, and only a >window gap since the user's last activity starts a fresh one."""
    conn = _require_conn()
    async with _lock:
        cur = await conn.execute("SELECT value FROM kv WHERE key = ?", (f"ula:{user_id}",))
        row = await cur.fetchone()
        await cur.close()
    try:
        return float(row["value"]) if row else 0.0
    except (TypeError, ValueError):
        return 0.0


async def set_user_last_active(user_id: int, ts: float) -> None:
    """#329: record the user's overall last-active time — any message OR an explicit session
    switch counts (a switch must KEEP the chosen session, never idle-rotate it away)."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (f"ula:{user_id}", str(ts)),
        )
        await conn.commit()


async def rotate_session_for_idle(thread_id: int) -> None:
    """#261: start a FRESH conversation on the same session after a long idle gap —
    NULL the code + chat session ids so the next turn runs with no resumed context.

    Unlike reset_thread, this KEEPS the message log (recap/history) and never touches
    mode/model/cwd or usage; the old transcript stays on disk (resumable). The point is
    only to stop stale context from being re-ingested, not to wipe the session."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET code_session_id = NULL, chat_session_id = NULL "
            "WHERE thread_id = ?",
            (thread_id,),
        )
        await conn.commit()


async def set_stream_enabled(thread_id: int, on: bool) -> None:
    """Persist the per-session live-streaming preference (/stream)."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET stream_enabled = ? WHERE thread_id = ?",
            (1 if on else 0, thread_id),
        )
        await conn.commit()


async def set_hot_cache_timer(thread_id: int, on: bool) -> None:
    """Persist the per-session warm-cache post-reply note toggle (#164)."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET hot_cache_timer = ? WHERE thread_id = ?",
            (1 if on else 0, thread_id),
        )


async def set_todo_card(thread_id: int, on: bool) -> None:
    """Persist the per-session live task-list card toggle (#229)."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET todo_card = ? WHERE thread_id = ?",
            (1 if on else 0, thread_id),
        )


# ---------------------------------------------------------- schedules (#188)

async def add_schedule(thread_id: int, chat_id: int, owner_uid: int, spec_json: str,
                       prompt: str, next_run: float, created_at: float) -> int:
    """Insert a recurring schedule; returns its new id."""
    conn = _require_conn()
    async with _lock:
        cur = await conn.execute(
            "INSERT INTO schedules (thread_id, chat_id, owner_uid, spec, prompt, "
            "next_run, enabled, created_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
            (thread_id, chat_id, owner_uid, spec_json, prompt, next_run, created_at),
        )
        await conn.commit()
        return int(cur.lastrowid)


async def list_schedules(owner_uid: int) -> list[dict]:
    """All schedules owned by ``owner_uid``, oldest first."""
    conn = _require_conn()
    async with _lock:
        cur = await conn.execute(
            "SELECT * FROM schedules WHERE owner_uid = ? ORDER BY id", (owner_uid,)
        )
        rows = await cur.fetchall()
        await cur.close()
    return [dict(r) for r in rows]


async def count_schedules(owner_uid: int) -> int:
    """How many schedules ``owner_uid`` has (for the per-user cap)."""
    conn = _require_conn()
    async with _lock:
        cur = await conn.execute(
            "SELECT COUNT(*) AS n FROM schedules WHERE owner_uid = ?", (owner_uid,)
        )
        row = await cur.fetchone()
        await cur.close()
    return int(row["n"])


async def get_schedule(schedule_id: int) -> dict | None:
    """One schedule by id, or None."""
    conn = _require_conn()
    async with _lock:
        cur = await conn.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,))
        row = await cur.fetchone()
        await cur.close()
    return dict(row) if row else None


async def due_schedules(now: float) -> list[dict]:
    """Enabled schedules whose next_run has passed (the runner's work list)."""
    conn = _require_conn()
    async with _lock:
        cur = await conn.execute(
            "SELECT * FROM schedules WHERE enabled = 1 AND next_run <= ? ORDER BY next_run",
            (now,),
        )
        rows = await cur.fetchall()
        await cur.close()
    return [dict(r) for r in rows]


async def set_schedule_enabled(schedule_id: int, on: bool) -> None:
    """Pause/resume a schedule."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE schedules SET enabled = ? WHERE id = ?", (1 if on else 0, schedule_id)
        )
        await conn.commit()


async def update_schedule_run(schedule_id: int, next_run: float, last_run: float,
                              last_status: str) -> None:
    """Record a fire: advance next_run and stamp the last run + status."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE schedules SET next_run = ?, last_run = ?, last_status = ? WHERE id = ?",
            (next_run, last_run, last_status, schedule_id),
        )
        await conn.commit()


async def delete_schedule(schedule_id: int) -> None:
    """Remove a schedule for good."""
    conn = _require_conn()
    async with _lock:
        await conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
        await conn.commit()  # #257: dropped a duplicate second commit() here


async def set_auto_compact(thread_id: int, on: bool) -> None:
    """Persist the per-session SDK auto-compaction toggle (#164, hidden for now)."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET auto_compact = ? WHERE thread_id = ?",
            (1 if on else 0, thread_id),
        )
        await conn.commit()


async def set_no_sandbox(thread_id: int, on: bool) -> None:
    """Persist the owner-only per-session sandbox opt-out (#104)."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET no_sandbox = ? WHERE thread_id = ?",
            (1 if on else 0, thread_id),
        )
        await conn.commit()


async def set_shell_mode(thread_id: int, on: bool) -> None:
    """Persist the per-session shell-mode overlay toggle (#224)."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET shell_mode = ? WHERE thread_id = ?",
            (1 if on else 0, thread_id),
        )
        await conn.commit()


async def set_tools_enabled(thread_id: int, tools: list[str] | None) -> None:
    """Persist the per-session enabled-tools list (#129). None → NULL (mode default);
    a list is stored as JSON (``[]`` = tool-free)."""
    conn = _require_conn()
    raw = None if tools is None else json.dumps([str(t) for t in tools])
    async with _lock:
        await conn.execute(
            "UPDATE threads SET tools_enabled = ? WHERE thread_id = ?", (raw, thread_id)
        )
        await conn.commit()


async def set_favorite(thread_id: int, on: bool) -> None:
    """Pin/unpin a session as a favorite (sorted first in /sessions)."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET favorite = ? WHERE thread_id = ?",
            (1 if on else 0, thread_id),
        )
        await conn.commit()


async def set_effort(thread_id: int, effort: str | None) -> None:
    """Persist the reasoning-effort level (#23); None clears it (SDK default)."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET effort = ? WHERE thread_id = ?", (effort, thread_id)
        )
        await conn.commit()


async def set_max_turns(thread_id: int, n: int | None) -> None:
    """Persist the agentic turn cap (#23); None clears it (unlimited)."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET max_turns = ? WHERE thread_id = ?", (n, thread_id)
        )
        await conn.commit()


async def set_add_dirs(thread_id: int, dirs: list[str]) -> None:
    """Persist the extra code working dirs (#23) as a JSON list."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET add_dirs = ? WHERE thread_id = ?",
            (json.dumps(list(dirs)), thread_id),
        )
        await conn.commit()


async def set_fork_pending(thread_id: int, on: bool) -> None:
    """Set/clear the one-shot 'fork on next turn' flag (#23)."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET fork_pending = ? WHERE thread_id = ?",
            (1 if on else 0, thread_id),
        )
        await conn.commit()


async def set_code_session(thread_id: int, session_id: str | None) -> None:
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET code_session_id = ? WHERE thread_id = ?",
            (session_id, thread_id),
        )
        await conn.commit()


async def set_chat_session(thread_id: int, session_id: str | None) -> None:
    """Persist the resumable chat-mode session id for a thread."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET chat_session_id = ? WHERE thread_id = ?",
            (session_id, thread_id),
        )
        await conn.commit()


async def set_big_memory(thread_id: int, on: bool) -> None:
    """Toggle the per-topic big-memory flag (1M chat window + durable session)."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET big_memory = ? WHERE thread_id = ?",
            (1 if on else 0, thread_id),
        )
        await conn.commit()


async def set_permission_mode(thread_id: int, mode: str) -> None:
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET permission_mode = ? WHERE thread_id = ?",
            (mode, thread_id),
        )
        await conn.commit()


async def get_kv(key: str, default: str | None = None) -> str | None:
    """Return the stored value for a key, or default if absent."""
    conn = _require_conn()
    async with _lock:
        cur = await conn.execute("SELECT value FROM kv WHERE key = ?", (key,))
        row = await cur.fetchone()
        await cur.close()
    if row is None:
        return default
    return row["value"]


async def set_kv(key: str, value: str) -> None:
    """Upsert a key/value pair."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await conn.commit()


async def reset_thread(thread_id: int) -> None:
    """Clear the code + chat session ids (drop context); keep mode/model/cwd,
    the big_memory flag and usage intact."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET code_session_id = NULL, chat_session_id = NULL "
            "WHERE thread_id = ?",
            (thread_id,),
        )
        # /reset drops the conversation, so the recap/history log goes too.
        await conn.execute("DELETE FROM messages WHERE thread_id = ?", (thread_id,))
        await conn.commit()


async def add_usage(
    thread_id: int, usage: dict | None, cost_usd: float | None,
    model: str | None = None, context_tokens: int = 0,
) -> None:
    """Append one usage record. Missing keys default to 0. ``model`` and
    ``context_tokens`` (#165) are stored alongside the raw token counts so the
    weighted ``usage_units`` metric can be computed at query time from each turn's
    own data (concurrency-safe — no shared global gauge)."""
    usage = usage or {}

    def _int(key: str) -> int:
        value = usage.get(key, 0)
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    # These key names match the Anthropic API `usage` object, which the SDK
    # passes through unchanged: ResultMessage.usage = data["usage"] (verified in
    # claude_agent_sdk/_internal/message_parser.py). Keep them in sync with that
    # schema — wrong names would make every total silently read 0.
    input_tokens = _int("input_tokens")
    output_tokens = _int("output_tokens")
    cache_read = _int("cache_read_input_tokens")
    cache_creation = _int("cache_creation_input_tokens")
    cost = float(cost_usd) if cost_usd is not None else 0.0

    try:
        ctx_tokens = int(context_tokens or 0)
    except (TypeError, ValueError):
        ctx_tokens = 0

    conn = _require_conn()
    async with _lock:
        await conn.execute(
            """
            INSERT INTO usage
                (thread_id, chat_id, ts, input_tokens, output_tokens, cache_read,
                 cache_creation, cost_usd, model, context_tokens)
            VALUES (?, (SELECT chat_id FROM threads WHERE thread_id = ?), ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                thread_id,
                thread_id,   # #309: resolve + store the owning chat_id so the row outlives the thread
                time.time(),
                input_tokens,
                output_tokens,
                cache_read,
                cache_creation,
                cost,
                model,
                ctx_tokens,
            ),
        )
        await conn.commit()


async def get_usage_totals(thread_id: int) -> dict:
    """Aggregate usage for a thread: {input, output, cache_read, cache_creation, cost, requests}."""
    conn = _require_conn()
    async with _lock:
        cur = await conn.execute(
            """
            SELECT
                COALESCE(SUM(input_tokens), 0)   AS input,
                COALESCE(SUM(output_tokens), 0)  AS output,
                COALESCE(SUM(cache_read), 0)     AS cache_read,
                COALESCE(SUM(cache_creation), 0) AS cache_creation,
                COALESCE(SUM(cost_usd), 0.0)     AS cost,
                COUNT(*)                         AS requests
            FROM usage
            WHERE thread_id = ?
            """,
            (thread_id,),
        )
        row = await cur.fetchone()
        await cur.close()

    return {
        "input": int(row["input"]),
        "output": int(row["output"]),
        "cache_read": int(row["cache_read"]),
        "cache_creation": int(row["cache_creation"]),
        "cost": float(row["cost"]),
        "requests": int(row["requests"]),
    }


async def get_usage_totals_bulk(thread_ids: list[int]) -> dict[int, dict]:
    """#285: per-thread {input, output, requests} for MANY threads in ONE query — replaces
    the N+1 `get_usage_totals` loop in the /sessions render (one GROUP BY instead of N
    full scans). Threads with no usage are absent from the result (caller defaults to 0)."""
    ids = [int(t) for t in thread_ids]
    if not ids:
        return {}
    conn = _require_conn()
    placeholders = ",".join("?" * len(ids))
    async with _lock:
        cur = await conn.execute(
            f"""
            SELECT u.thread_id                       AS thread_id,
                   COALESCE(SUM(u.input_tokens), 0)  AS input,
                   COALESCE(SUM(u.output_tokens), 0) AS output,
                   COALESCE(SUM({_units_sql_expr()}), 0) AS units,
                   COUNT(*)                          AS requests
            FROM usage u
            WHERE u.thread_id IN ({placeholders})
            GROUP BY u.thread_id
            """,
            ids,
        )
        rows = await cur.fetchall()
        await cur.close()
    # #307: also return weighted "units" per thread (for the /sessions list stats line).
    return {int(r["thread_id"]): {"input": int(r["input"]), "output": int(r["output"]),
                                  "units": int(r["units"]),
                                  "requests": int(r["requests"])} for r in rows}


# #293: get_user_usage_tokens removed — dead since #165 (the raw-token scalar limit
# basis was superseded by weighted units; see get_user_usage_window(measure="units")).

# #264: per-user rolling-cap windows. The SHORT window now tracks Anthropic's real
# ~5-hour subscription reset (was a 24h "daily" window — too coarse to distribute the
# shared budget fairly across users); the long window stays 7 days. The breakdown dict
# keys are still "day"/"week" for back-compat, but "day" now means the trailing 5 HOURS.
SHORT_WINDOW_SEC = 5 * 3600    # 5h — Anthropic's short reset window (was 86400 = 24h)
WEEK_WINDOW_SEC = 7 * 86400    # 7 days — the long window


# #293: get_user_usage_breakdown / get_user_units_breakdown consolidated into
# get_user_breakdown(user_id, measure=...) — see the centralized family below.

# #165: weighted "usage units" — a cost-aware per-turn metric that mirrors how the
# shared subscription windows actually fill, so a user with a big WARM context (cheap
# input but a huge cache_read re-read every turn) is no longer under-counted by the
# raw input+output total. A unit is a cost-weighted token-equivalent, baselined on a
# Sonnet INPUT token; the coefficients track Anthropic list-price ratios:
#   unit = MODEL_WEIGHT * (input + OUT*output + CC*cache_creation + CR*cache_read)
# Computed at QUERY time from each row's stored raw columns + model, so the weights are
# tunable here with NO migration, and every turn's cost is derived only from its own
# numbers (concurrency-safe — not a before/after delta on a shared global gauge). The
# model is matched by substring, so a "[1m]" / dated suffix still resolves.
USAGE_OUTPUT_MULT = 5.0          # output tokens ≈ 5× input price
USAGE_CACHE_CREATE_MULT = 1.25   # cache write ≈ 1.25× input price
USAGE_CACHE_READ_MULT = 0.10     # cache read ≈ 0.1× input price
USAGE_MODEL_WEIGHT_OPUS = 5.0    # Opus ≈ 5× Sonnet input price
USAGE_MODEL_WEIGHT_SONNET = 1.0  # baseline
USAGE_MODEL_WEIGHT_HAIKU = 0.27  # Haiku ≈ 0.27× Sonnet input price
USAGE_MODEL_WEIGHT_DEFAULT = 1.0  # unknown / NULL model → Sonnet-equivalent baseline


def _units_sql_expr() -> str:
    """SQL sub-expression turning one ``usage u`` row into weighted units (#165). The
    numeric weights are trusted module constants formatted inline (never user input)."""
    return (
        "((CASE "
        f"WHEN u.model LIKE '%opus%'   THEN {USAGE_MODEL_WEIGHT_OPUS} "
        f"WHEN u.model LIKE '%sonnet%' THEN {USAGE_MODEL_WEIGHT_SONNET} "
        f"WHEN u.model LIKE '%haiku%'  THEN {USAGE_MODEL_WEIGHT_HAIKU} "
        f"ELSE {USAGE_MODEL_WEIGHT_DEFAULT} END) "
        f"* (COALESCE(u.input_tokens,0) + {USAGE_OUTPUT_MULT}*COALESCE(u.output_tokens,0) "
        f"+ {USAGE_CACHE_CREATE_MULT}*COALESCE(u.cache_creation,0) "
        f"+ {USAGE_CACHE_READ_MULT}*COALESCE(u.cache_read,0)))"
    )


# #293: centralized usage-aggregation family. The raw-token and weighted-unit reads
# used to be parallel twin functions doing the same query with a different summed
# expression; now ONE measure parameter selects the expression and the rest (windows,
# scope, grouping) is shared. `measure="raw"` = input+output tokens; `measure="units"`
# = cost-weighted units (#165). Consolidates the former get_user_usage_units,
# get_user_usage_breakdown, get_user_units_breakdown, get_all_users_units,
# get_all_users_usage (and the dead get_user_usage_tokens).
def _usage_measure_expr(measure: str) -> str:
    """The per-``usage u`` row SQL sum sub-expression for a measure. Numeric weights
    are trusted module constants (never user input); `measure` is a fixed literal from
    the call sites, validated here so a typo fails loudly instead of mis-summing."""
    if measure == "units":
        return _units_sql_expr()
    if measure == "raw":
        return "(COALESCE(u.input_tokens,0) + COALESCE(u.output_tokens,0))"
    raise ValueError(f"unknown usage measure: {measure!r}")


async def get_user_usage_window(user_id: int, since: float | None = None,
                                measure: str = "units") -> int:
    """Total usage one user has spent across ALL their sessions, in `measure`
    (default weighted "units" #165 — the cost-aware basis for the rolling-window caps).
    With ``since`` (epoch seconds), counts only usage at-or-after that time. Usage rows
    carry their owner's chat_id (#309), so the sum is over ``usage.chat_id`` directly and
    survives a session delete (a deleted session's spend still counts toward the cap)."""
    expr = _usage_measure_expr(measure)
    conn = _require_conn()
    query = (
        f"SELECT COALESCE(SUM({expr}), 0) AS v "
        "FROM usage u "                 # #309: by usage.chat_id, not a threads join
        "WHERE u.chat_id = ?"
    )
    params: list = [user_id]
    if since is not None:
        query += " AND u.ts >= ?"
        params.append(since)
    async with _lock:
        cur = await conn.execute(query, params)
        row = await cur.fetchone()
        await cur.close()
    return int(row["v"] or 0)


async def get_user_breakdown(user_id: int, measure: str = "raw") -> dict:
    """Per-user usage over the trailing 5h / week plus the lifetime total and request
    count, in `measure` ("raw" tokens or weighted "units" #165). Windows are computed
    from usage.ts, so no reset job is needed. Feeds the per-user stats card + /limits."""
    now = time.time()
    day_since = now - SHORT_WINDOW_SEC   # #264: "day" key = trailing 5h
    week_since = now - WEEK_WINDOW_SEC
    expr = _usage_measure_expr(measure)
    conn = _require_conn()
    async with _lock:
        cur = await conn.execute(
            f"SELECT "
            f"COALESCE(SUM(CASE WHEN u.ts >= ? THEN {expr} ELSE 0 END), 0) AS day, "
            f"COALESCE(SUM(CASE WHEN u.ts >= ? THEN {expr} ELSE 0 END), 0) AS week, "
            f"COALESCE(SUM({expr}), 0) AS total, "
            f"COUNT(*) AS requests "
            "FROM usage u "                       # #309: by usage.chat_id, not a threads join
            "WHERE u.chat_id = ?",
            (day_since, week_since, user_id),
        )
        row = await cur.fetchone()
        await cur.close()
    return {
        "day": int(row["day"] or 0),
        "week": int(row["week"] or 0),
        "total": int(row["total"] or 0),
        "requests": int(row["requests"] or 0),
    }


async def get_all_users_breakdown(measure: str = "raw") -> list[dict]:
    """#285: per-user usage aggregate for ALL DM users in ONE GROUP BY — trailing-5h /
    week / lifetime total in `measure` ("raw" tokens or weighted "units" #165), plus the
    request count and last-activity ts, busiest week first. Keyed-by-uid dicts are built
    by the caller when needed. Only DM users (``chat_id > 0`` == the Telegram id) count: a
    group/supergroup has a negative ``-100…`` chat_id and is NOT a person, so it is
    excluded (it would otherwise show up as a phantom 'user' — #164 follow-up)."""
    now = time.time()
    day_since = now - SHORT_WINDOW_SEC
    week_since = now - WEEK_WINDOW_SEC
    expr = _usage_measure_expr(measure)
    conn = _require_conn()
    async with _lock:
        cur = await conn.execute(
            f"SELECT u.chat_id AS uid, "
            f"COALESCE(SUM(CASE WHEN u.ts >= ? THEN {expr} ELSE 0 END), 0) AS day, "
            f"COALESCE(SUM(CASE WHEN u.ts >= ? THEN {expr} ELSE 0 END), 0) AS week, "
            f"COALESCE(SUM({expr}), 0) AS total, "
            f"COUNT(*) AS requests, COALESCE(MAX(u.ts), 0) AS last_ts "
            # #309: group by usage.chat_id (no threads join) so a deleted session's owner
            # still appears with their full lifetime totals.
            "FROM usage u "
            "WHERE u.chat_id > 0 "          # DM users only; groups (chat_id<0) are not people
            "GROUP BY u.chat_id ORDER BY week DESC, total DESC",
            (day_since, week_since),
        )
        rows = await cur.fetchall()
        await cur.close()
    return [
        {
            "uid": int(r["uid"]),
            "day": int(r["day"] or 0),
            "week": int(r["week"] or 0),
            "total": int(r["total"] or 0),
            "requests": int(r["requests"] or 0),
            "last_ts": float(r["last_ts"] or 0),
        }
        for r in rows
    ]


# --------------------------------------------------------------------------- #
# Conversation log (feeds /recap + /history)
# --------------------------------------------------------------------------- #
async def log_message(thread_id: int, role: str, text: str) -> None:
    """Append one conversation turn (role = 'user' | 'assistant') for a thread.

    Best-effort: empty text is skipped. Stored verbatim so /history exports and
    /recap can replay the exact exchange the bot would otherwise never keep.
    """
    if not text or not text.strip():
        return
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "INSERT INTO messages (thread_id, ts, role, text) VALUES (?, ?, ?, ?)",
            (thread_id, time.time(), role, text),
        )
        await conn.commit()


async def get_recent_messages(thread_id: int, limit: int = 200) -> list[dict]:
    """Return up to `limit` most recent messages for a thread, oldest-first:
    [{ts, role, text}, …]. Empty list when nothing is logged."""
    conn = _require_conn()
    async with _lock:
        cur = await conn.execute(
            "SELECT ts, role, text FROM (SELECT id, ts, role, text FROM messages "
            "WHERE thread_id = ? ORDER BY id DESC LIMIT ?) ORDER BY id ASC",
            (thread_id, limit),
        )
        rows = await cur.fetchall()
        await cur.close()
    return [{"ts": r["ts"], "role": r["role"], "text": r["text"]} for r in rows]


# --------------------------------------------------------------------------- #
# Subscription rate-limit history (feeds the /status trend)
# --------------------------------------------------------------------------- #
async def append_rate_history(rate_type: str, utilization, status: str) -> None:
    """Append one rate-limit datapoint; trims to the most recent 500 rows so the
    table can't grow unbounded. utilization may be None (the CLI often omits it)."""
    conn = _require_conn()
    util = float(utilization) if isinstance(utilization, (int, float)) else None
    async with _lock:
        await conn.execute(
            "INSERT INTO rate_history (ts, rate_type, utilization, status) "
            "VALUES (?, ?, ?, ?)",
            (time.time(), rate_type, util, status),
        )
        await conn.execute(
            "DELETE FROM rate_history WHERE id NOT IN "
            "(SELECT id FROM rate_history ORDER BY id DESC LIMIT 500)"
        )
        await conn.commit()


async def get_rate_history(rate_type: str, limit: int = 12) -> list[dict]:
    """Return up to `limit` most recent datapoints for a window, oldest-first."""
    conn = _require_conn()
    async with _lock:
        cur = await conn.execute(
            "SELECT ts, utilization, status FROM (SELECT id, ts, utilization, status "
            "FROM rate_history WHERE rate_type = ? ORDER BY id DESC LIMIT ?) "
            "ORDER BY id ASC",
            (rate_type, limit),
        )
        rows = await cur.fetchall()
        await cur.close()
    return [
        {"ts": r["ts"], "utilization": r["utilization"], "status": r["status"]}
        for r in rows
    ]


async def set_created_by(thread_id: int, user_id: int) -> None:
    """Record who first created a session (once; never overwritten)."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET created_by = ? "
            "WHERE thread_id = ? AND created_by IS NULL",
            (user_id, thread_id),
        )
        await conn.commit()


async def browse_threads(
    chat_id: int, keyword: str | None = None, limit: int = 8, offset: int = 0
) -> tuple[list[dict], int]:
    """Return (page_rows, total) of a chat's sessions, newest first.

    chat_id selects the surface: the supergroup id lists its topics; a user id
    lists that user's DM sessions. An optional keyword does a simple name search.
    """
    conn = _require_conn()
    where = "chat_id = ?"
    params: list = [chat_id]
    if keyword:
        where += " AND name LIKE ?"
        params.append(f"%{keyword}%")
    async with _lock:
        cur = await conn.execute(
            f"SELECT COUNT(*) AS n FROM threads WHERE {where}", params
        )
        total = int((await cur.fetchone())["n"])
        await cur.close()
        cur = await conn.execute(
            "SELECT thread_id, name, mode, created_at, created_by, "
            "COALESCE(favorite, 0) AS favorite, COALESCE(name_auto, 1) AS name_auto "
            f"FROM threads WHERE {where} "
            "ORDER BY favorite DESC, created_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        rows = await cur.fetchall()
        await cur.close()
    page = [
        {
            "thread_id": r["thread_id"],
            "name": r["name"],
            "mode": r["mode"],
            "created_at": r["created_at"],
            "created_by": r["created_by"],
            "favorite": bool(r["favorite"]),
            # #334: surface name_auto so the empty-session GC's "spare manually-renamed"
            # guard (handlers `_gc_untitled_empties`) actually sees it — it was SELECTed
            # (COALESCE above) but dropped from the page dict, so the guard's
            # `.get("name_auto", True)` always defaulted True and never fired.
            "name_auto": bool(r["name_auto"]),
        }
        for r in rows
    ]
    return page, total


async def allocate_dm_session(
    user_id: int, name: str, default_model: str, base_workdir: str, mode: str = "chat"
) -> int:
    """Create a new DM session (a negative key, chat_id = user_id); return its key.

    DM sessions use negative keys from a global counter so they never collide with
    supergroup topic ids (>= 0) or with another user's sessions. Each session gets
    its OWN code working directory, base_workdir/<key>, so code-mode work in one
    session never touches another's files (per-session isolation by id). The mode
    (chat/code) is fixed at creation — a session is one OR the other for its life.
    """
    conn = _require_conn()
    async with _lock:
        cur = await conn.execute("SELECT value FROM kv WHERE key = 'dm_seq'")
        row = await cur.fetchone()
        await cur.close()
        seq = (int(row["value"]) if row else 0) + 1
        await conn.execute(
            "INSERT INTO kv (key, value) VALUES ('dm_seq', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(seq),),
        )
        key = -seq
        # #332: name the workdir by the PUBLIC ULID — same id shown in the UI, collision-safe
        # (80-bit), and the on-disk dir == sid == session_pubid. The legacy 6-hex session_sid
        # is migration-only now. was: cwd = base / session_sid(key) / "work".
        # #181: nested layout — the session cwd is <ulid>/work (state is the sibling).
        pubid = new_ulid()
        _SID_BY_THREAD[key] = pubid  # so session_pubid(key) resolves while building the path
        cwd = str(Path(base_workdir) / pubid / "work")
        session_mode = "code" if mode == "code" else "chat"
        await conn.execute(
            "INSERT INTO threads (thread_id, chat_id, mode, model, cwd, "
            "code_session_id, name, permission_mode, chat_session_id, big_memory, "
            "created_by, created_at, sid) "
            "VALUES (?, ?, ?, ?, ?, NULL, ?, 'acceptEdits', NULL, 0, ?, ?, ?)",
            (key, user_id, session_mode, default_model, cwd, name, user_id, time.time(), pubid),
        )
        await conn.commit()
        _SID_BY_THREAD[key] = pubid
    return key


async def get_dm_current(user_id: int) -> int | None:
    """Return the user's current DM session key, or None if unset."""
    raw = await get_kv(f"dm_current:{user_id}")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


async def set_dm_current(user_id: int, key: int) -> None:
    """Set the user's current DM session key."""
    await set_kv(f"dm_current:{user_id}", str(key))


# --------------------------------------------------------------------------- #
# Per-USER default settings (#138)
# --------------------------------------------------------------------------- #
# The USER scope of the unified settings registry (settings_schema.py): a user's
# personal default for a setting, applied to their FUTURE sessions when the session
# itself has no explicit (SESSION-scope) value. Stored generically in `kv` under
# ``user_default:{uid}:{key}`` as a JSON-encoded value, so no schema migration is
# needed and any new registry key works without a column. Precedence is enforced by
# settings_schema.resolve(): SESSION → USER → GLOBAL → built-in default.
def _user_default_key(uid: int, key: str) -> str:
    return f"user_default:{uid}:{key}"


async def get_user_default(uid: int, key: str):
    """Return this user's personal default for ``key`` (the USER scope), or None if
    unset. Stored JSON-encoded in `kv`; a garbled value degrades to None (unset)."""
    raw = await get_kv(_user_default_key(uid, key))
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


async def set_user_default(uid: int, key: str, value) -> None:
    """Set (value JSON-encoded) or clear (value is None → delete the row) this
    user's personal default for ``key``. Clearing makes the USER scope fall through
    to GLOBAL/default in resolve()."""
    kvkey = _user_default_key(uid, key)
    if value is None:
        conn = _require_conn()
        async with _lock:
            await conn.execute("DELETE FROM kv WHERE key = ?", (kvkey,))
            await conn.commit()
        return
    await set_kv(kvkey, json.dumps(value))


# --------------------------------------------------------------------------- #
# Owner-configured per-option ACCESS overrides (#151, menu.md §4)
# --------------------------------------------------------------------------- #
# The owner may override an option's BASE access (Hidden / Read-only / Delegated)
# away from its built-in default (settings_schema.BASE_ACCESS_DEFAULTS). Stored as a
# single JSON blob in `kv` (key 'access_base') so any registry key works with no
# schema change. Effective access is DERIVED per prompt (settings_schema), so a
# change applies from the user's very next prompt — nothing per-user is cached here.
async def get_access_overrides() -> dict:
    """Return the owner's per-option base-access overrides {option: level_str}, or
    {} when none set. A garbled blob degrades to {} (fall back to built-in defaults)."""
    raw = await get_kv("access_base")
    if raw is None:
        return {}
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else {}
    except (ValueError, TypeError):
        return {}


async def set_access_override(option: str, level: str | None) -> None:
    """Set (or clear, ``level=None``) the owner's base-access override for one option."""
    cur = await get_access_overrides()
    if level is None:
        cur.pop(option, None)
    else:
        cur[option] = level
    await set_kv("access_base", json.dumps(cur))


async def get_user_lang(user_id: int) -> str | None:
    """Return the user's chosen interface locale, or None if never set.

    Stored in `kv` (key 'lang:<user_id>') like the DM-current pointer. None means
    "no explicit choice yet" — the caller auto-detects from the Telegram client
    language and may persist that as the default.
    """
    return await get_kv(f"lang:{user_id}")


async def set_user_lang(user_id: int, lang: str) -> None:
    """Persist the user's chosen interface locale."""
    await set_kv(f"lang:{user_id}", lang)


async def delete_dm_session(user_id: int, key: int) -> bool:
    """Delete a DM session (and its message + schedule rows). Returns True if a row
    was removed. NOTE (#309): the session's ``usage`` rows are deliberately KEPT — a
    user's recorded token spend must outlive deleting the session (it still feeds their
    lifetime totals + rolling-limit windows, keyed by chat_id).

    Scoped to (thread_id == key AND chat_id == user_id) so a user can only ever
    delete their OWN row. DM rows are owned by a real, positive user id, whereas a
    shared supergroup topic / General row is keyed by the supergroup's (negative)
    chat id — so the chat_id scope alone already prevents this path from dropping a
    shared row. We deliberately do NOT refuse key >= 0: an anomalous DM row minted
    outside allocate_dm_session (e.g. a legacy key 0) must still be deletable by its
    owner. The caller closes any live session and removes the workdir.
    """
    if user_id <= 0:
        return False
    conn = _require_conn()
    async with _lock:
        cur = await conn.execute(
            "DELETE FROM threads WHERE thread_id = ? AND chat_id = ?",
            (key, user_id),
        )
        removed = cur.rowcount or 0
        await cur.close()
        # #309: usage rows are NO LONGER deleted with the session — a user's per-session
        # token spend must survive deleting that session, so it still counts toward their
        # lifetime totals + rolling-limit windows (else deleting sessions silently shrinks
        # recorded spend and dodges the caps). Usage is keyed by chat_id and aggregated
        # without the threads join, so the orphaned rows still attribute to the right user.
        # was (removed for #309):
        # await conn.execute("DELETE FROM usage WHERE thread_id = ?", (key,))
        await conn.execute("DELETE FROM messages WHERE thread_id = ?", (key,))
        # #332: the session_uid registry is keyed by the on-disk dir name = the ULID (re-keyed
        # by migrate_workdirs_to_ulid). was: session_sid(key) — the legacy 6-hex.
        await conn.execute("DELETE FROM session_uid WHERE sid = ?", (session_pubid(key),))  # #221/#332
        # #254: cascade to schedules too — otherwise an orphaned schedule keeps firing and
        # _fire_schedule → handle_text → ensure_thread silently resurrects the deleted thread.
        await conn.execute("DELETE FROM schedules WHERE thread_id = ?", (key,))
        await conn.commit()
    return removed > 0


async def claim_session_uid(sid: str, preferred: int, lo: int, hi: int) -> int:
    """Return a STABLE, collision-free host uid for ``sid`` (#221). ``hi`` is exclusive.

    First call: record ``preferred`` (the deterministic hash uid) if free, else
    linear-probe ``[lo, hi)`` for the next unused uid and record THAT — so two sessions
    whose hashes collide get DISTINCT uids. Later calls return the recorded uid, so the
    on-disk chown stays valid across rebuilds. ``_lock`` serialises the probe and the
    UNIQUE(uid) constraint is the backstop that makes an already-taken slot fail.
    """
    conn = _require_conn()
    span = max(1, hi - lo)
    start = lo + ((preferred - lo) % span)            # clamp preferred into [lo, hi)
    async with _lock:
        cur = await conn.execute("SELECT uid FROM session_uid WHERE sid = ?", (sid,))
        row = await cur.fetchone()
        await cur.close()
        if row is not None:
            return int(row["uid"])
        for i in range(span):
            cand = lo + ((start - lo + i) % span)
            try:
                await conn.execute(
                    "INSERT INTO session_uid (sid, uid) VALUES (?, ?)", (sid, cand)
                )
                await conn.commit()
                return cand
            except sqlite3.IntegrityError:
                continue                              # uid taken by another sid → next slot
        # Space exhausted (>> any realistic session count): fall back to the bare hash
        # rather than fail the session. Collisions are possible again only in this case.
        return start


async def release_session_uid(sid: str) -> None:
    """Free a session's reserved uid (#221) so the uid space can be reused. No-op if
    absent. Called when a session is permanently deleted."""
    conn = _require_conn()
    async with _lock:
        await conn.execute("DELETE FROM session_uid WHERE sid = ?", (sid,))
        await conn.commit()


def _uid_collisions(uid_by_sid: dict[str, int]) -> dict[int, list[str]]:
    """Group sids by their host uid; return only the NON-ROOT uids shared by MORE THAN
    ONE sid (a genuine per-session isolation break). Pure + testable; the disk scan
    below feeds it.

    #231: uid 0 (root) is EXCLUDED — root ownership is the ROUTINE pre-launch / no-jail
    default, not a runtime collision, so it must not raise an owner alert. A workdir stays
    root-owned until a CODE session first runs and the launcher chowns it to its claimed
    per-session uid; chat sessions (no jail) and sandbox-off sessions stay root-owned for
    good. None of those is the birthday-collision this doctor exists to catch — two
    sessions whose uid hash maps to the SAME ASSIGNED non-root uid. A jailed session runs
    as a distinct non-root uid and cannot read another's root-owned 0700 dir anyway, so
    shared root ownership is not an isolation break. (Counting it fired a benign warning on
    every restart for chat sessions that can never self-heal.)
    # was: every shared uid (incl. uid 0) was reported — replaced for #231."""
    by_uid: dict[int, list[str]] = {}
    for sid, uid in uid_by_sid.items():
        if uid == 0:
            continue                      # root = unassigned / no-jail default, not a collision
        by_uid.setdefault(uid, []).append(sid)
    return {uid: sorted(sids) for uid, sids in by_uid.items() if len(sids) > 1}


def sandbox_uid_collisions(base_workdir: str) -> dict[int, list[str]]:
    """#221 doctor: scan on-disk session workdirs and return ``{uid: [sids]}`` for any
    host uid that owns more than one session's ``<sid>/work`` — the real isolation break.
    Empty dict = clean. With the uid registry this should always be empty; it surfaces a
    PRE-#221 collision not yet healed (it heals when the affected sessions next run and
    get re-chowned to their registry uid). Sync (filesystem stat); never raises."""
    uid_by_sid: dict[str, int] = {}
    try:
        for child in Path(base_workdir).iterdir():
            if not child.is_dir():
                continue
            try:
                uid_by_sid[child.name] = os.stat(child / "work").st_uid
            except OSError:
                continue                      # no work dir yet / unreadable → skip
    except OSError:
        return {}
    return _uid_collisions(uid_by_sid)


async def load_sid_cache() -> None:
    """#327: populate the thread_id -> ULID cache from the DB at startup (after the migration has
    backfilled `sid`). session_sid() reads this cache on the hot path."""
    conn = _require_conn()
    async with _lock:
        cur = await conn.execute("SELECT thread_id, sid FROM threads WHERE sid IS NOT NULL")
        rows = await cur.fetchall()
        await cur.close()
    _SID_BY_THREAD.clear()
    for r in rows:
        _SID_BY_THREAD[int(r["thread_id"])] = r["sid"]


async def migrate_sessions_to_ulid(base_workdir: str) -> int:
    """#327 (decoupled): backfill a stored PUBLIC ULID for every session that lacks one. DB-ONLY —
    the workdir / transcript / jail-uid stay on the stable 6-hex session_sid(), so the filesystem is
    NEVER touched and `resume` can't break. Idempotent (rows that already have a sid are skipped),
    safe to run every startup. ``base_workdir`` is unused now (kept for the call signature — no dirs
    are moved). Returns the count backfilled."""
    _ = base_workdir  # decoupled migration is DB-only; no directories are moved
    conn = _require_conn()
    backfilled = 0
    async with _lock:
        cur = await conn.execute("SELECT thread_id FROM threads WHERE sid IS NULL")
        rows = await cur.fetchall()
        await cur.close()
        for row in rows:
            tid = int(row["thread_id"])
            pubid = new_ulid()
            await conn.execute(
                "UPDATE threads SET sid = ? WHERE thread_id = ?", (pubid, tid)
            )
            _SID_BY_THREAD[tid] = pubid
            backfilled += 1
        if backfilled:
            await conn.commit()
    return backfilled


async def migrate_workdirs_to_ulid(base_workdir: str) -> int:
    """#332: rename each per-session workdir from the legacy 6-hex ``session_sid`` to the
    PUBLIC ULID, so the on-disk name matches the id shown in the UI and is collision-safe
    (80-bit) instead of the old 24-bit hash. For every session whose dir is still the 6-hex:

      * rename ``base/<6hex>`` -> ``base/<ulid>``;
      * re-encode the nested transcript dir ``<ulid>/state/<old-encoded-cwd>`` ->
        ``<ulid>/state/<new-encoded-cwd>`` — claude keys ``resume`` by the cwd-encoded path,
        so this MUST follow the rename or resume breaks (the #327/#140 trap);
      * re-key the ``session_uid`` registry row (keyed by the on-disk dir name) 6hex -> ulid,
        so the per-session host uid stays stable across the rename;
      * realign the stored ``cwd`` to the new ULID path.

    Idempotent (a session already on its ULID dir is skipped, incl. ones born ULID-named) and
    per-row fail-safe: an OSError on one dir is logged and skipped WITHOUT touching its cwd, so
    that session still runs off its old dir and the next startup retries. Must run AFTER the
    ULID backfill (every thread needs its `sid`). Returns the number of sessions migrated.
    """
    conn = _require_conn()
    base = Path(base_workdir)
    migrated = 0
    async with _lock:
        cur = await conn.execute("SELECT thread_id, cwd, sid FROM threads WHERE sid IS NOT NULL")
        rows = await cur.fetchall()
        await cur.close()
        for row in rows:
            tid = int(row["thread_id"])
            ulid = row["sid"]
            cwd = row["cwd"]
            if not ulid:
                continue
            # Already on the ULID dir (cwd's parent dir == the ULID) — skip. Covers sessions
            # born ULID-named and a re-run after a prior migration.
            if cwd and os.path.basename(os.path.dirname(os.path.normpath(cwd))) == ulid:
                continue
            legacy = _derive_sid(tid)            # the old 6-hex on-disk name
            old = base / legacy
            new = base / ulid
            new_cwd = str(new / "work")
            try:
                if old.is_dir() and not new.exists():
                    os.rename(old, new)
                    # Re-encode the nested transcript dir so `resume` survives the rename.
                    # #335: this regex MUST stay in sync with archive.encode_workdir (the
                    # shared cwd→project-dir encoder the runtime readers use); leaf db.py
                    # keeps its own copy rather than import archive for one migration line.
                    old_enc = re.sub(r"[^A-Za-z0-9]", "-", str(old / "work"))
                    new_enc = re.sub(r"[^A-Za-z0-9]", "-", str(new / "work"))
                    state = new / "state"
                    if (state / old_enc).is_dir() and not (state / new_enc).exists():
                        os.rename(state / old_enc, state / new_enc)
                    logger.info("migrate_workdirs_to_ulid: thread %s %s -> %s", tid, old, new)
                elif old.is_dir() and new.is_dir():
                    # #338: both exist — keep the ULID dir, realign cwd. Remove the orphaned
                    # legacy dir ONLY if it is empty (os.rmdir fails on a non-empty dir → a
                    # legacy dir still holding files is LEFT IN PLACE, never silently deleted).
                    try:
                        os.rmdir(old)
                        logger.info(
                            "migrate_workdirs_to_ulid: both %s and %s existed for thread %s; "
                            "removed empty legacy dir, realigned cwd", old, new, tid)
                    except OSError:
                        logger.warning(
                            "migrate_workdirs_to_ulid: both %s and %s exist for thread %s; "
                            "kept new dir, legacy dir not empty — left in place, cwd realigned",
                            old, new, tid)
                # else: no live dir yet (lazy) or new-only — just realign cwd + uid below.
                # Re-key the uid registry (keyed by the on-disk dir name) so the uid is stable.
                await conn.execute("UPDATE session_uid SET sid = ? WHERE sid = ?", (ulid, legacy))
                if cwd != new_cwd:
                    await conn.execute(
                        "UPDATE threads SET cwd = ? WHERE thread_id = ?", (new_cwd, tid))
                migrated += 1
            except OSError as exc:
                logger.warning(
                    "migrate_workdirs_to_ulid: thread %s (%s -> %s) failed: %s — left as-is",
                    tid, old, new, exc)
        if migrated:
            await conn.commit()
    return migrated


async def migrate_workdirs_to_sid(base_workdir: str) -> int:
    """One-time, idempotent rename of per-session workdirs from the raw numeric
    thread_id to the stable PUBLIC sid (#140).

    Historically a session's working directory was ``base_workdir/<thread_id>``
    (and its sandbox state ``base_workdir/<thread_id>.sbxstate``). #140 names them
    by ``session_sid(thread_id)`` instead so on-disk names match the id shown in
    /sessions and never leak the internal numbering. For every thread row we:

      * compute old = base_workdir/<thread_id>, new = base_workdir/<sid>;
      * if old != new and old exists and new does NOT, os.rename(old, new) and,
        if present, rename "old.sbxstate" -> "new.sbxstate";
      * UPDATE the row's cwd column to the new ABSOLUTE path.

    Rows already migrated (cwd basename already == sid) are skipped, so this is
    safe to run on every startup. Returns the number of rows migrated; never
    raises for an individual row (logs and continues) so a single bad dir can't
    block the rest.
    """
    # #181: RETIRED — return early so the legacy #140 rename can't CLOBBER the new
    # nested layout (<sid>/work). Its skip-check keys on basename==sid, but the new
    # cwd basename is "work", so re-running it would strip "/work" off every startup.
    # This deployment is long-migrated and the nested move was done by hand (no new
    # migration tooling, per the owner). Original body kept below (unreachable) for
    # history per the audit convention.
    return 0
    conn = _require_conn()
    base = Path(base_workdir)
    migrated = 0
    async with _lock:
        cur = await conn.execute("SELECT thread_id, cwd FROM threads")
        rows = await cur.fetchall()
        await cur.close()
        for row in rows:
            thread_id = int(row["thread_id"])
            sid = session_sid(thread_id)
            cur_cwd = row["cwd"]
            # Already on the new scheme (the stored cwd ends in the sid) — skip.
            if cur_cwd and os.path.basename(os.path.normpath(cur_cwd)) == sid:
                continue
            old = base / str(thread_id)
            new = base / sid
            if old == new:
                continue
            try:
                # Rename the dir (+ its .sbxstate sidecar) if it still lives at the
                # OLD numeric name and the sid name is free.
                if old.exists() and not new.exists():
                    os.rename(old, new)
                    old_sbx = Path(f"{old}.sbxstate")
                    new_sbx = Path(f"{new}.sbxstate")
                    if old_sbx.exists() and not new_sbx.exists():
                        os.rename(old_sbx, new_sbx)
                    logger.info(
                        "Migrated workdir for thread %s: %s -> %s", thread_id, old, new
                    )
                elif old.exists() and new.exists():
                    # Both present (e.g. a half-finished prior run) — don't clobber
                    # the new dir; the cwd realignment below settles it.
                    logger.warning(
                        "Workdir migration: both %s and %s exist for thread %s; "
                        "kept new dir, realigned cwd only",
                        old,
                        new,
                        thread_id,
                    )
                # In EVERY case the canonical dir is now the sid path, so realign the
                # stored cwd whenever it still differs. #140-fix: this UPDATE must
                # also bump `migrated` so the guarded commit below isn't skipped — the
                # realign-only branches previously updated cwd but left migrated=0, so
                # `if migrated: commit()` dropped the change and it re-ran forever.
                # Also covers a crash BETWEEN a prior rename and its commit (old gone,
                # new exists, cwd still stale) and a never-started session (no dir yet).
                if cur_cwd != str(new):
                    await conn.execute(
                        "UPDATE threads SET cwd = ? WHERE thread_id = ?",
                        (str(new), thread_id),
                    )
                    migrated += 1
            except OSError as exc:
                logger.warning(
                    "Workdir migration failed for thread %s (%s -> %s): %s",
                    thread_id,
                    old,
                    new,
                    exc,
                )
        if migrated:
            await conn.commit()
    return migrated


async def close_db() -> None:
    """Close the module-level connection if open."""
    global _conn
    if _conn is not None:
        if _lock is not None:
            async with _lock:
                await _conn.close()
                _conn = None
        else:
            await _conn.close()
            _conn = None
