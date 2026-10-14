"""aiosqlite-based per-thread persistent state.

- One module-level connection shared by all helpers
- Access serialized with an `asyncio.Lock`
- Each forum topic keeps its own isolated state row
- General topic uses `thread_id` 0
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

# Module-level connection and lock, set by `init_db()`.
_conn: aiosqlite.Connection | None = None
_lock = None  # type: ignore[assignment]  # lazily created asyncio.Lock in init_db


# Two ids per session: internal workdir id, public ULID.
# - `session_sid()`: stable 6-hex sha1; never moves (resume is cwd-keyed)
# - `session_pubid()`: stored ULID shown in the UI
# - Adding the ULID is display-only; can't break resume
_SID_BY_THREAD: dict[int, str] = {}  # thread_id to public ULID

# Crockford base32 alphabet (no I, L, O, U).
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid() -> str:
    """Generate a ULID: 26-char time-sortable Crockford base32 id.

    - 48-bit ms timestamp plus 80-bit randomness
    - No external dependency
    """
    val = ((int(time.time() * 1000) & ((1 << 48) - 1)) << 80) | int.from_bytes(os.urandom(10), "big")
    out = bytearray(26)
    for i in range(25, -1, -1):
        out[i] = ord(_CROCKFORD[val & 0x1F])
        val >>= 5
    return out.decode("ascii")


def _derive_sid(thread_id: int) -> str:
    """Legacy derived sid (`sha1[:6]`).

    - Locates a session's old on-disk name
    - Fallback for threads not yet in the ULID cache
    """
    return hashlib.sha1(f"sess:{thread_id}".encode()).hexdigest()[:6]


def session_sid(thread_id: int) -> str:
    """Internal stable workdir id: 6-hex `sha1[:6]`.

    - Names workdir, transcript, jail uid, secrets
    - Must never change; resume is cwd-keyed
    - Not user-facing; see `session_pubid()`
    """
    return _derive_sid(thread_id)


def session_pubid(thread_id: int) -> str:
    """Public session id shown in the UI.

    - Stored ULID read from the cache
    - Falls back to the 6-hex workdir id if not backfilled
    """
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
    # Resumable chat session id, persisted every chat turn.
    # - Resumed on rebuild only when `big_memory` is on
    chat_session_id: str | None = None
    # Per-topic big memory: 1M window plus durable chat session.
    big_memory: bool = False
    # Per-topic agent-saved session memory notes.
    # - Saved via the in-process `remember` tool
    # - Re-injected into the system prompt each build
    # - Size-capped in the engine; cleared by /forget
    session_notes: str = ""
    created_at: float = 0.0
    created_by: int | None = None
    # Live-streaming display preference, persisted across restarts.
    stream_enabled: bool = True
    # Per-session pro-command options.
    effort: str | None = None
    max_turns: int | None = None
    add_dirs: list[str] = field(default_factory=list)
    fork_pending: bool = False
    # Favorite session, sorted first in /sessions.
    favorite: bool = False
    # Owner-only per-session sandbox opt-out.
    # - Runs the code session's claude without the jail
    # - Guests can never set it
    no_sandbox: bool = False
    # Shell-mode overlay: text routes to a jailed command.
    # - Not a mode change; session stays "code"
    shell_mode: bool = False
    # Per-session enabled tools.
    # - None means the mode's full default set
    # - A list means exactly those; `[]` is tool-free
    tools_enabled: list[str] | None = None
    # Post-reply warm-cache note and SDK auto-compaction toggles.
    # - Note is user-toggleable; auto-compaction owner-only
    hot_cache_timer: bool = False
    auto_compact: bool = False
    # Live task-list card from TodoWrite events.
    # - Code-only, default off
    todo_card: bool = False
    # Auto-adopt Claude Code's transcript ai-title as session label.
    # - A manual /rename pins the name and clears this
    name_auto: bool = True
    # Epoch seconds of the last finished turn; 0 means never.
    # - Drives the idle-rotation check on the next message
    last_active: float = 0.0


def _require_conn() -> aiosqlite.Connection:
    """Return the live connection or raise if uninitialized."""
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
        # Enable WAL once: reads never block the single writer.
        # - `synchronous=NORMAL` is the safe pairing for WAL
        # - Best-effort; failure must not crash init
        try:
            await _conn.execute("PRAGMA journal_mode=WAL")
            await _conn.execute("PRAGMA synchronous=NORMAL")
            # Wait up to 5s on a lock instead of erroring.
            # - Gives a second writer a brief queue
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
        # Per-session conversation log feeding /recap and /history.
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
        # Index usage for range scans; the table grows forever.
        # - Index `(thread_id, ts)` for per-thread and time-window scans
        # - Index `threads.chat_id`, the per-user filter column
        await _conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_usage_thread_ts ON usage(thread_id, ts)"
        )
        # Create `idx_usage_chat_ts` in the migration block.
        # - Needs `chat_id` to exist; ALTER adds it on old dbs
        await _conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_threads_chat ON threads(chat_id)"
        )
        # Recurring scheduled prompts.
        # - `spec` is JSON from `schedules.parse_schedule`
        # - The runner loop fires due, enabled rows into their session
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
        # Append-only rate-limit history feeding the /status trend.
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
        # Per-session host-uid registry mapping sid to a unique uid.
        # - Engine prefers the hash uid, probes on collision
        # - Prevents two sessions sharing a uid (breaks FS isolation)
        await _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_uid (
                sid TEXT PRIMARY KEY,
                uid INTEGER NOT NULL UNIQUE
            )
            """
        )
        # Add columns introduced after the first release.
        cur = await _conn.execute("PRAGMA table_info(threads)")
        columns = await cur.fetchall()
        await cur.close()
        existing = {col["name"] for col in columns}
        if "permission_mode" not in existing:
            await _conn.execute(
                "ALTER TABLE threads ADD COLUMN permission_mode TEXT DEFAULT 'acceptEdits'"
            )
        # Stored public session id (ULID), backfilled at startup.
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
        if "session_notes" not in existing:
            await _conn.execute("ALTER TABLE threads ADD COLUMN session_notes TEXT")
        if "created_by" not in existing:
            await _conn.execute("ALTER TABLE threads ADD COLUMN created_by INTEGER")
        if "stream_enabled" not in existing:
            await _conn.execute(
                "ALTER TABLE threads ADD COLUMN stream_enabled INTEGER DEFAULT 1"
            )
        # Per-session pro options: effort, turn cap, extra dirs, fork flag.
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
        # Shell-mode overlay for code sessions.
        if "shell_mode" not in existing:
            await _conn.execute(
                "ALTER TABLE threads ADD COLUMN shell_mode INTEGER DEFAULT 0"
            )
        # Per-session enabled-tools JSON array.
        # - NULL means mode default; `[]` means tool-free
        if "tools_enabled" not in existing:
            await _conn.execute("ALTER TABLE threads ADD COLUMN tools_enabled TEXT")
        # Warm-cache note toggle and SDK auto-compaction toggle.
        if "hot_cache_timer" not in existing:
            await _conn.execute(
                "ALTER TABLE threads ADD COLUMN hot_cache_timer INTEGER DEFAULT 0"
            )
        if "auto_compact" not in existing:
            await _conn.execute(
                "ALTER TABLE threads ADD COLUMN auto_compact INTEGER DEFAULT 0"
            )
        # Per-session live task-list card toggle.
        if "todo_card" not in existing:
            await _conn.execute(
                "ALTER TABLE threads ADD COLUMN todo_card INTEGER DEFAULT 0"
            )
        # Auto-naming flag; 1 adopts Claude Code's ai-title as label.
        # - A manual /rename sets it to 0
        if "name_auto" not in existing:
            await _conn.execute(
                "ALTER TABLE threads ADD COLUMN name_auto INTEGER DEFAULT 1"
            )
        # Wall-clock epoch seconds of the last finished turn.
        # - Durable across restart, unlike in-memory monotonic activity
        # - 0 means never ran
        if "last_active" not in existing:
            await _conn.execute(
                "ALTER TABLE threads ADD COLUMN last_active REAL DEFAULT 0"
            )
        # Per-turn model and live context size stored with usage.
        # - Older rows have NULL model and 0 context
        cur = await _conn.execute("PRAGMA table_info(usage)")
        ucols = {col["name"] for col in await cur.fetchall()}
        await cur.close()
        if "model" not in ucols:
            await _conn.execute("ALTER TABLE usage ADD COLUMN model TEXT")
        if "context_tokens" not in ucols:
            await _conn.execute(
                "ALTER TABLE usage ADD COLUMN context_tokens INTEGER DEFAULT 0"
            )
        # Usage is owned by `chat_id`, not just the thread.
        # - Totals and limit windows survive a session delete
        # - Existing rows backfilled from their thread
        # - Rows whose thread is gone stay NULL
        if "chat_id" not in ucols:
            await _conn.execute("ALTER TABLE usage ADD COLUMN chat_id INTEGER")
            await _conn.execute(
                "UPDATE usage SET chat_id = "
                "(SELECT th.chat_id FROM threads th WHERE th.thread_id = usage.thread_id) "
                "WHERE chat_id IS NULL"
            )
        # Create the index after `chat_id` is guaranteed present.
        # - Idempotent; fresh dbs get the column from CREATE TABLE
        await _conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_usage_chat_ts ON usage(chat_id, ts)"
        )
        # Migrate legacy permission_mode 'default' to 'acceptEdits'.
        # - 'default' is no longer selectable
        # - The jail is the containment layer
        await _conn.execute(
            "UPDATE threads SET permission_mode = 'acceptEdits' "
            "WHERE permission_mode = 'default' OR permission_mode IS NULL"
        )
        await _conn.commit()


def _parse_dirs(raw) -> list[str]:
    """Parse the `add_dirs` JSON column into a list.

    - Returns [] on missing or garbled
    """
    if not raw:
        return []
    try:
        v = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return [str(x) for x in v] if isinstance(v, list) else []


def _parse_tools_enabled(raw):
    """Parse the `tools_enabled` JSON column.

    - NULL gives None (the mode's default tool set)
    - A list is used as-is; `[]` means tool-free
    - Garbled value degrades to None
    """
    if raw is None:
        return None
    try:
        v = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return [str(x) for x in v] if isinstance(v, list) else None


async def get_thread(thread_id: int) -> ThreadState | None:
    """Stored state for a thread, or None if absent."""
    conn = _require_conn()
    async with _lock:
        cur = await conn.execute(
            "SELECT thread_id, chat_id, mode, model, cwd, code_session_id, name, "
            "COALESCE(permission_mode, 'acceptEdits') AS permission_mode, "
            "chat_session_id, "
            "COALESCE(big_memory, 0) AS big_memory, "
            "COALESCE(session_notes, '') AS session_notes, "
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
        session_notes=row["session_notes"] or "",
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
    """Insert the thread as chat if absent; return its state."""
    existing = await get_thread(thread_id)
    if existing is not None:
        return existing

    conn = _require_conn()
    async with _lock:
        # Guard against a coroutine inserting the row meanwhile.
        await conn.execute(
            """
            INSERT OR IGNORE INTO threads
                (thread_id, chat_id, mode, model, cwd, code_session_id, name, permission_mode, chat_session_id, big_memory, created_at)
            VALUES (?, ?, 'chat', ?, ?, NULL, NULL, 'acceptEdits', NULL, 0, ?)
            """,
            (thread_id, chat_id, default_model, default_cwd, time.time()),
        )
        await conn.commit()

    # Read back the authoritative row (handles the race).
    state = await get_thread(thread_id)
    assert state is not None  # just inserted or pre-existing
    return state


async def set_mode(thread_id: int, mode: str) -> None:
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET mode = ? WHERE thread_id = ?", (mode, thread_id)
        )
        await conn.commit()


async def switch_mode(thread_id: int, new_mode: str) -> None:
    """Change a session's type, carrying its conversation across.

    - Copies the resumable session id into the new mode's column
    - No-op if already `new_mode`
    """
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
            # `target_col` is a fixed literal, so interpolation is safe.
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
    """Rename a session (the label shown in /sessions).

    - `manual=True` pins the name and disables auto-naming
    - `manual=False` writes only while still in auto mode
    """
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
    """Stamp the epoch time of the last finished turn.

    - Read on the next message for idle rotation
    """
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET last_active = ? WHERE thread_id = ?", (ts, thread_id)
        )
        await conn.commit()


async def get_user_last_active(user_id: int) -> float:
    """Return the user's last-active epoch time across all sessions.

    - Idle rotation keys off the user's gap, not session age
    """
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
    """Record the user's overall last-active time.

    - Messages and explicit session switches both count
    - A switch must keep the chosen session
    """
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (f"ula:{user_id}", str(ts)),
        )
        await conn.commit()


async def rotate_session_for_idle(thread_id: int) -> None:
    """Start a fresh conversation on the same session.

    - NULLs code and chat session ids
    - Keeps message log, mode, model, cwd, usage
    - Old transcript stays on disk
    """
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET code_session_id = NULL, chat_session_id = NULL "
            "WHERE thread_id = ?",
            (thread_id,),
        )
        await conn.commit()


async def set_stream_enabled(thread_id: int, on: bool) -> None:
    """Persist the per-session live-streaming preference."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET stream_enabled = ? WHERE thread_id = ?",
            (1 if on else 0, thread_id),
        )
        await conn.commit()


async def set_hot_cache_timer(thread_id: int, on: bool) -> None:
    """Persist the per-session warm-cache post-reply note toggle."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET hot_cache_timer = ? WHERE thread_id = ?",
            (1 if on else 0, thread_id),
        )


async def set_todo_card(thread_id: int, on: bool) -> None:
    """Persist the per-session live task-list card toggle."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET todo_card = ? WHERE thread_id = ?",
            (1 if on else 0, thread_id),
        )


# ---- schedules ----

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
    """All schedules owned by `owner_uid`, oldest first."""
    conn = _require_conn()
    async with _lock:
        cur = await conn.execute(
            "SELECT * FROM schedules WHERE owner_uid = ? ORDER BY id", (owner_uid,)
        )
        rows = await cur.fetchall()
        await cur.close()
    return [dict(r) for r in rows]


async def count_schedules(owner_uid: int) -> int:
    """Count schedules owned by `owner_uid` (for the per-user cap)."""
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
    """Enabled schedules whose `next_run` has passed."""
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
    """Pause or resume a schedule."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE schedules SET enabled = ? WHERE id = ?", (1 if on else 0, schedule_id)
        )
        await conn.commit()


async def update_schedule_run(schedule_id: int, next_run: float, last_run: float,
                              last_status: str) -> None:
    """Record a fire: advance `next_run`, stamp last run and status."""
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
        await conn.commit()


async def set_auto_compact(thread_id: int, on: bool) -> None:
    """Persist the per-session SDK auto-compaction toggle."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET auto_compact = ? WHERE thread_id = ?",
            (1 if on else 0, thread_id),
        )
        await conn.commit()


async def set_no_sandbox(thread_id: int, on: bool) -> None:
    """Persist the owner-only per-session sandbox opt-out."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET no_sandbox = ? WHERE thread_id = ?",
            (1 if on else 0, thread_id),
        )
        await conn.commit()


async def set_shell_mode(thread_id: int, on: bool) -> None:
    """Persist the per-session shell-mode overlay toggle."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET shell_mode = ? WHERE thread_id = ?",
            (1 if on else 0, thread_id),
        )
        await conn.commit()


async def set_tools_enabled(thread_id: int, tools: list[str] | None) -> None:
    """Persist the per-session enabled-tools list.

    - None stores NULL (mode default)
    - A list is stored as JSON; `[]` is tool-free
    """
    conn = _require_conn()
    raw = None if tools is None else json.dumps([str(t) for t in tools])
    async with _lock:
        await conn.execute(
            "UPDATE threads SET tools_enabled = ? WHERE thread_id = ?", (raw, thread_id)
        )
        await conn.commit()


async def set_favorite(thread_id: int, on: bool) -> None:
    """Pin or unpin a session as a favorite (sorted first)."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET favorite = ? WHERE thread_id = ?",
            (1 if on else 0, thread_id),
        )
        await conn.commit()


async def set_effort(thread_id: int, effort: str | None) -> None:
    """Persist the reasoning-effort level; None clears it."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET effort = ? WHERE thread_id = ?", (effort, thread_id)
        )
        await conn.commit()


async def set_max_turns(thread_id: int, n: int | None) -> None:
    """Persist the agentic turn cap; None means unlimited."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET max_turns = ? WHERE thread_id = ?", (n, thread_id)
        )
        await conn.commit()


async def set_add_dirs(thread_id: int, dirs: list[str]) -> None:
    """Persist the extra code working dirs as a JSON list."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET add_dirs = ? WHERE thread_id = ?",
            (json.dumps(list(dirs)), thread_id),
        )
        await conn.commit()


async def set_fork_pending(thread_id: int, on: bool) -> None:
    """Set or clear the one-shot fork-on-next-turn flag."""
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
    """Toggle the per-topic big-memory flag (1M window, durable session)."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET big_memory = ? WHERE thread_id = ?",
            (1 if on else 0, thread_id),
        )
        await conn.commit()


async def set_session_notes(thread_id: int, notes: str) -> None:
    """Replace the per-topic session-memory blob.

    - Written by the `remember` tool and /forget
    - Engine caps size beforehand; stored verbatim
    """
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET session_notes = ? WHERE thread_id = ?",
            (notes, thread_id),
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
    """Stored value for a key, or default if absent."""
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
    """Clear code and chat session ids (drop context).

    - Keeps mode, model, cwd, `big_memory` and usage
    """
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET code_session_id = NULL, chat_session_id = NULL "
            "WHERE thread_id = ?",
            (thread_id,),
        )
        # /reset drops the conversation, so the recap log goes too.
        await conn.execute("DELETE FROM messages WHERE thread_id = ?", (thread_id,))
        await conn.commit()


async def add_usage(
    thread_id: int, usage: dict | None, cost_usd: float | None,
    model: str | None = None, context_tokens: int = 0,
) -> None:
    """Append one usage record; missing keys default to 0.

    - Stores `model` and `context_tokens` with raw counts
    - Metrics are computed per turn at query time
    """
    usage = usage or {}

    def _int(key: str) -> int:
        value = usage.get(key, 0)
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    # Key names match the Anthropic API `usage` object.
    # - The SDK passes it through unchanged
    # - Wrong names would make every total silently read 0
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
                thread_id,   # owning `chat_id` outlives the thread
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
    """Aggregate usage for a thread.

    - Returns {input, output, cache_read, cache_creation, cost, requests}
    """
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
    """Per-thread usage totals for many threads in one query.

    - Returns {input, output, requests} per thread
    - Threads without usage are absent; caller defaults to 0
    """
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
                   COUNT(*)                          AS requests
            FROM usage u
            WHERE u.thread_id IN ({placeholders})
            GROUP BY u.thread_id
            """,
            ids,
        )
        rows = await cur.fetchall()
        await cur.close()
    return {int(r["thread_id"]): {"input": int(r["input"]), "output": int(r["output"]),
                                  "requests": int(r["requests"])} for r in rows}


# Rolling-cap windows: short is 5h, long is 7 days.
# - Breakdown keys stay "day"/"week"; "day" means trailing 5 hours
SHORT_WINDOW_SEC = 5 * 3600    # 5h: Anthropic's short reset window
WEEK_WINDOW_SEC = 7 * 86400    # 7 days, the long window


# Usage is tokens only: input plus output.


# Centralized usage-aggregation family.
# - One `measure` parameter selects the summed expression
# - Windows, scope and grouping are shared
# - `measure="raw"` is input plus output tokens
def _usage_measure_expr(measure: str) -> str:
    """SQL sum sub-expression per `usage u` row for a measure.

    - `measure` is validated so a typo fails loudly
    - Only "raw" (input plus output tokens) exists
    """
    if measure == "raw":
        return "(COALESCE(u.input_tokens,0) + COALESCE(u.output_tokens,0))"
    raise ValueError(f"unknown usage measure: {measure!r}")


async def get_user_usage_window(user_id: int, since: float | None = None,
                                measure: str = "raw") -> int:
    """Total tokens a user spent across all sessions.

    - Input plus output tokens; basis for rolling-window caps
    - `since` (epoch seconds) counts only usage at or after it
    - Summed by `usage.chat_id`; survives session deletes
    """
    expr = _usage_measure_expr(measure)
    conn = _require_conn()
    query = (
        f"SELECT COALESCE(SUM({expr}), 0) AS v "
        "FROM usage u "                 # by `usage.chat_id`, not a join
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
    """Per-user usage over trailing 5h and week, plus lifetime.

    - Includes request count; windows computed from `usage.ts`
    - Needs no reset job
    """
    now = time.time()
    day_since = now - SHORT_WINDOW_SEC   # "day" key is trailing 5h
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
            "FROM usage u "                       # by `usage.chat_id`, not a join
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
    """Per-user usage aggregate for all DM users, one query.

    - 5h, week, lifetime tokens, requests, last-activity ts
    - Busiest week first
    - Only DM users (`chat_id > 0`); groups excluded
    """
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
            # Group by `usage.chat_id`, no `threads` join.
            # - A deleted session's owner keeps lifetime totals
            "FROM usage u "
            "WHERE u.chat_id > 0 "          # DM users only; groups excluded
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


# ---- Conversation log (feeds /recap and /history) ----
async def log_message(thread_id: int, role: str, text: str) -> None:
    """Append one conversation turn for a thread.

    - Role is 'user' or 'assistant'; empty text skipped
    - Stored verbatim for /history and /recap
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
    """Return recent messages for a thread, oldest-first.

    - Each item is `{ts, role, text}`; empty if none
    """
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


# ---- Rate-limit history (feeds /status trend) ----
async def append_rate_history(rate_type: str, utilization, status: str) -> None:
    """Append one rate-limit datapoint, trimming to 500 rows.

    - utilization may be None (CLI often omits it)
    """
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
    """Return recent datapoints for a window, oldest-first."""
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
    """Return (page_rows, total) of a chat's sessions, newest-active first.

    - Supergroup id lists topics; user id lists DM sessions
    - Optional keyword does a simple name search
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
            # Order by most recent activity, not creation time.
            # - `last_active` is stamped at each turn end
            # - Never-run sessions have 0, so `max()` falls back to `created_at`
            # - Favorites sort first
            "ORDER BY favorite DESC, "
            "max(COALESCE(last_active, 0), COALESCE(created_at, 0)) DESC "
            "LIMIT ? OFFSET ?",
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
            # Surface `name_auto` so the empty-session GC guard sees it.
            # - The guard spares manually renamed sessions
            "name_auto": bool(r["name_auto"]),
        }
        for r in rows
    ]
    return page, total


async def allocate_dm_session(
    user_id: int, name: str, default_model: str, base_workdir: str, mode: str = "chat"
) -> int:
    """Create a new DM session; return its key.

    - Keys are negative, from a global counter
    - Each session gets its own working directory
    - Mode (chat/code) is fixed at creation
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
        # Workdir is named by the public ULID.
        # - On-disk dir equals sid equals `session_pubid`
        # - Nested layout: cwd is `<ulid>/work`, state is the sibling
        # - Legacy 6-hex `session_sid` is migration-only
        pubid = new_ulid()
        _SID_BY_THREAD[key] = pubid  # so `session_pubid(key)` resolves for path
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


async def dm_user_ids() -> list[int]:
    """Every user owning at least one DM session.

    - DM sessions: negative `thread_id`, positive owner `chat_id`
    """
    conn = _require_conn()
    async with _lock:
        cur = await conn.execute(
            "SELECT DISTINCT chat_id FROM threads WHERE thread_id < 0 AND chat_id > 0")
        rows = await cur.fetchall()
        await cur.close()
    return [int(r[0]) for r in rows]


async def get_dm_current(user_id: int) -> int | None:
    """Return the user's current DM session key, or None."""
    raw = await get_kv(f"dm_current:{user_id}")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


async def set_dm_current(user_id: int, key: int) -> None:
    """Set the user's current DM session key."""
    await set_kv(f"dm_current:{user_id}", str(key))


# ---- Per-user default settings ----
# - User scope of the settings registry
# - Applies to future sessions lacking an explicit session value
# - Stored in `kv` as `user_default:{uid}:{key}` JSON
# - Precedence: session, user, global, built-in default (`resolve()`)
def _user_default_key(uid: int, key: str) -> str:
    return f"user_default:{uid}:{key}"


async def get_user_default(uid: int, key: str):
    """Return the user's personal default for a key, or None.

    - Stored JSON-encoded in `kv`; garbled degrades to None
    """
    raw = await get_kv(_user_default_key(uid, key))
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


async def set_user_default(uid: int, key: str, value) -> None:
    """Set or clear a user's personal default for a key.

    - Value JSON-encoded; None deletes the row
    - Clearing falls through to global/default in `resolve()`
    """
    kvkey = _user_default_key(uid, key)
    if value is None:
        conn = _require_conn()
        async with _lock:
            await conn.execute("DELETE FROM kv WHERE key = ?", (kvkey,))
            await conn.commit()
        return
    await set_kv(kvkey, json.dumps(value))


_MODEL_ALIAS_MIGRATION_KV = "model_alias_migrated"


async def migrate_model_ids_to_aliases(family_of) -> int:
    """One-time move of stored model ids onto family aliases.

    - Rewrites `threads.model` and per-user default model values
    - The CLI resolves an alias to the family's newest model
    - Runs once (kv `model_alias_migrated`); later pins survive
    - Usage rows keep historical model; returns rows rewritten
    """
    if await get_kv(_MODEL_ALIAS_MIGRATION_KV):
        return 0

    def _target(model) -> str | None:
        alias = family_of(model) if isinstance(model, str) else None
        return alias if alias and alias != model else None

    conn = _require_conn()
    changed = 0
    async with _lock:
        cur = await conn.execute("SELECT DISTINCT model FROM threads WHERE model IS NOT NULL")
        stored = [r[0] for r in await cur.fetchall()]
        await cur.close()
        for model in stored:
            target = _target(model)
            if target:
                res = await conn.execute(
                    "UPDATE threads SET model = ? WHERE model = ?", (target, model))
                changed += res.rowcount or 0
        cur = await conn.execute(
            "SELECT key, value FROM kv WHERE key LIKE 'user_default:%:model'")
        defaults = await cur.fetchall()
        await cur.close()
        for kvkey, raw in defaults:
            try:
                model = json.loads(raw)
            except (ValueError, TypeError):
                continue
            target = _target(model)
            if target:
                await conn.execute(
                    "UPDATE kv SET value = ? WHERE key = ?", (json.dumps(target), kvkey))
                changed += 1
        await conn.execute(
            "INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)",
            (_MODEL_ALIAS_MIGRATION_KV, "1"))
        await conn.commit()
    return changed


# ---- Owner per-option access overrides ----
# - Overrides an option's base access from its built-in default
# - Levels: Hidden, Read-only, Delegated
# - Stored as one JSON blob in `kv` key 'access_base'
# - Effective access derived per prompt; nothing cached per-user
async def get_access_overrides() -> dict:
    """Return the owner's per-option base-access overrides.

    - `{option: level_str}`, or `{}` when none set
    - Garbled blob degrades to `{}` (built-in defaults)
    """
    raw = await get_kv("access_base")
    if raw is None:
        return {}
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else {}
    except (ValueError, TypeError):
        return {}


async def set_access_override(option: str, level: str | None) -> None:
    """Set or clear the owner's base-access override for an option."""
    cur = await get_access_overrides()
    if level is None:
        cur.pop(option, None)
    else:
        cur[option] = level
    await set_kv("access_base", json.dumps(cur))


async def get_user_lang(user_id: int) -> str | None:
    """Return the user's chosen interface locale, or None.

    - Stored in `kv` as 'lang:<user_id>'
    - None means no explicit choice; caller may auto-detect
    """
    return await get_kv(f"lang:{user_id}")


async def set_user_lang(user_id: int, lang: str) -> None:
    """Persist the user's chosen interface locale."""
    await set_kv(f"lang:{user_id}", lang)


async def delete_dm_session(user_id: int, key: int) -> bool:
    """Delete a DM session and its message and schedule rows.

    - Returns True if a row was removed
    - `usage` rows are kept so spend still counts toward caps
    - Scoped to (`thread_id`, `chat_id`): only the owner's row
    - Anomalous legacy keys (e.g. 0) stay deletable by owner
    - Caller closes the live session and removes the workdir
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
        # Usage rows are kept when the session is deleted.
        # - Spend must still count toward lifetime totals and caps
        # - Rows are keyed by `chat_id`, aggregated without a join
        await conn.execute("DELETE FROM messages WHERE thread_id = ?", (key,))
        # `session_uid` registry is keyed by the on-disk dir name (ULID).
        await conn.execute("DELETE FROM session_uid WHERE sid = ?", (session_pubid(key),))
        # Cascade to schedules too.
        # - An orphaned schedule would resurrect the deleted thread
        await conn.execute("DELETE FROM schedules WHERE thread_id = ?", (key,))
        await conn.commit()
    return removed > 0


async def claim_session_uid(sid: str, preferred: int, lo: int, hi: int) -> int:
    """Return a stable, collision-free host uid for `sid`.

    - First call records `preferred`, else probes `[lo, hi)`
    - Later calls return the recorded uid
    - `hi` is exclusive; UNIQUE(uid) is the backstop
    - `_lock` serialises the probe
    """
    conn = _require_conn()
    span = max(1, hi - lo)
    start = lo + ((preferred - lo) % span)            # clamp `preferred` into range
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
                continue                              # taken by another sid: next slot
        # Space exhausted: fall back to the bare hash.
        # - Collisions become possible again only here
        return start


async def release_session_uid(sid: str) -> None:
    """Free a session's reserved uid; no-op if absent."""
    conn = _require_conn()
    async with _lock:
        await conn.execute("DELETE FROM session_uid WHERE sid = ?", (sid,))
        await conn.commit()


def _uid_collisions(uid_by_sid: dict[str, int]) -> dict[int, list[str]]:
    """Return non-root uids shared by more than one sid.

    - Pure; the disk scan feeds it
    - uid 0 excluded: root ownership is the routine pre-launch default
    - Only a shared assigned non-root uid is an isolation break
    """
    by_uid: dict[int, list[str]] = {}
    for sid, uid in uid_by_sid.items():
        if uid == 0:
            continue                      # root means unassigned, not a collision
        by_uid.setdefault(uid, []).append(sid)
    return {uid: sorted(sids) for uid, sids in by_uid.items() if len(sids) > 1}


def sandbox_uid_collisions(base_workdir: str) -> dict[int, list[str]]:
    """Scan session workdirs for host uids owning multiple sessions.

    - Returns `{uid: [sids]}`; empty means clean
    - Sync filesystem stat; never raises
    - Heals when affected sessions next run
    """
    uid_by_sid: dict[str, int] = {}
    try:
        for child in Path(base_workdir).iterdir():
            if not child.is_dir():
                continue
            try:
                uid_by_sid[child.name] = os.stat(child / "work").st_uid
            except OSError:
                continue                      # no work dir yet or unreadable: skip
    except OSError:
        return {}
    return _uid_collisions(uid_by_sid)


async def load_sid_cache() -> None:
    """Populate the thread_id to ULID cache from the DB.

    - Run at startup after the `sid` backfill
    - `session_sid()` reads this cache on the hot path
    """
    conn = _require_conn()
    async with _lock:
        cur = await conn.execute("SELECT thread_id, sid FROM threads WHERE sid IS NOT NULL")
        rows = await cur.fetchall()
        await cur.close()
    _SID_BY_THREAD.clear()
    for r in rows:
        _SID_BY_THREAD[int(r["thread_id"])] = r["sid"]


async def migrate_sessions_to_ulid(base_workdir: str) -> int:
    """Backfill a stored public ULID for sessions lacking one.

    - DB-only; filesystem never touched, so resume can't break
    - Idempotent, safe every startup
    - `base_workdir` is unused (signature only)
    - Returns the count backfilled
    """
    _ = base_workdir  # DB-only; no directories are moved
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
    """Rename per-session workdirs from 6-hex sid to ULID.

    - Re-encodes the transcript dir so resume survives
    - Re-keys the `session_uid` row; realigns stored `cwd`
    - Idempotent; per-row fail-safe, retried next startup
    - Must run after the ULID backfill; returns count
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
            # Already on the ULID dir: skip.
            # - Covers ULID-born sessions and re-runs
            if cwd and os.path.basename(os.path.dirname(os.path.normpath(cwd))) == ulid:
                continue
            legacy = _derive_sid(tid)            # the old 6-hex on-disk name
            old = base / legacy
            new = base / ulid
            new_cwd = str(new / "work")
            try:
                if old.is_dir() and not new.exists():
                    os.rename(old, new)
                    # Re-encode the transcript dir so `resume` survives the rename.
                    # - Regex must stay in sync with `archive.encode_workdir`
                    # - `db.py` keeps its own copy to stay a leaf
                    old_enc = re.sub(r"[^A-Za-z0-9]", "-", str(old / "work"))
                    new_enc = re.sub(r"[^A-Za-z0-9]", "-", str(new / "work"))
                    state = new / "state"
                    if (state / old_enc).is_dir() and not (state / new_enc).exists():
                        os.rename(state / old_enc, state / new_enc)
                    logger.info("migrate_workdirs_to_ulid: thread %s %s -> %s", tid, old, new)
                elif old.is_dir() and new.is_dir():
                    # Both dirs exist: keep the ULID dir, realign cwd.
                    # - Remove the legacy dir only if empty
                    # - A non-empty legacy dir is left in place (`os.rmdir` fails)
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
                # No live dir yet: just realign cwd and uid.
                # - Re-key the uid registry so the uid stays stable
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
    """Retired migration renaming workdirs from thread_id to sid.

    - Returns early to avoid clobbering the nested layout
    - Renamed the `.sbxstate` sidecar and updated stored `cwd`
    """
    # Retired: return early to protect the nested layout.
    # - Old skip-check keys on basename==sid, but cwd basename is "work"
    # - Re-running would strip "/work" on every startup
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
            # Already on the new scheme (cwd ends in sid): skip.
            if cur_cwd and os.path.basename(os.path.normpath(cur_cwd)) == sid:
                continue
            old = base / str(thread_id)
            new = base / sid
            if old == new:
                continue
            try:
                # Rename dir and sidecar if still at old name.
                # - Only when the sid name is free
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
                    # Both present: don't clobber the new dir.
                    # - The cwd realignment below settles it
                    logger.warning(
                        "Workdir migration: both %s and %s exist for thread %s; "
                        "kept new dir, realigned cwd only",
                        old,
                        new,
                        thread_id,
                    )
                # Always realign stored cwd to the sid path.
                # - The UPDATE must bump `migrated` so the commit isn't skipped
                # - Covers a crash between rename and commit
                # - Covers a never-started session (no dir yet)
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
