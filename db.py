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
import time
from dataclasses import dataclass, field
from pathlib import Path

import aiosqlite

# Module-level connection + serialization lock. Set by init_db().
_conn: aiosqlite.Connection | None = None
_lock = None  # type: ignore[assignment]  # lazily created asyncio.Lock in init_db


def session_sid(thread_id: int) -> str:
    """A stable, git-short-hash-style PUBLIC id for a session (#97).

    Derived purely from the immutable thread_id, so it needs no migration / new
    column and every existing session gets one immediately. Shown in /sessions,
    the session card, and /status so a session has a FIXED identifier instead of a
    list position that shifts as sessions are added/removed.
    """
    return hashlib.sha1(f"sess:{thread_id}".encode()).hexdigest()[:6]


@dataclass
class ThreadState:
    thread_id: int
    chat_id: int
    mode: str
    model: str
    cwd: str
    code_session_id: str | None
    name: str | None
    permission_mode: str = "default"
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
    # Per-session enabled tools (#129): None = the mode's full default universe
    # (chat → web tools, code → all); a list = exactly those (``[]`` = tool-free).
    tools_enabled: list[str] | None = None


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
        # Migrate threads: add any columns introduced after the first release.
        cur = await _conn.execute("PRAGMA table_info(threads)")
        columns = await cur.fetchall()
        await cur.close()
        existing = {col["name"] for col in columns}
        if "permission_mode" not in existing:
            await _conn.execute(
                "ALTER TABLE threads ADD COLUMN permission_mode TEXT DEFAULT 'default'"
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
        # Per-session enabled-tools list (#129): JSON array, or NULL = mode default
        # (chat → web tools, code → all). Distinct from [] which means tool-free.
        if "tools_enabled" not in existing:
            await _conn.execute("ALTER TABLE threads ADD COLUMN tools_enabled TEXT")
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
            "COALESCE(permission_mode, 'default') AS permission_mode, "
            "chat_session_id, "
            "COALESCE(big_memory, 0) AS big_memory, "
            "COALESCE(created_at, 0) AS created_at, created_by, "
            "COALESCE(stream_enabled, 1) AS stream_enabled, "
            "effort, max_turns, add_dirs, COALESCE(fork_pending, 0) AS fork_pending, "
            "COALESCE(favorite, 0) AS favorite, "
            "COALESCE(no_sandbox, 0) AS no_sandbox, "
            "tools_enabled "
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
        tools_enabled=_parse_tools_enabled(row["tools_enabled"]),
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
            VALUES (?, ?, 'chat', ?, ?, NULL, NULL, 'default', NULL, 0, ?)
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


async def set_session_name(thread_id: int, name: str) -> None:
    """Rename a session (the human label shown in /sessions)."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET name = ? WHERE thread_id = ?", (name, thread_id)
        )
        await conn.commit()


async def set_cwd(thread_id: int, cwd: str) -> None:
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET cwd = ? WHERE thread_id = ?", (cwd, thread_id)
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


async def set_no_sandbox(thread_id: int, on: bool) -> None:
    """Persist the owner-only per-session sandbox opt-out (#104)."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET no_sandbox = ? WHERE thread_id = ?",
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
    thread_id: int, usage: dict | None, cost_usd: float | None
) -> None:
    """Append one usage record. Missing keys default to 0."""
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

    conn = _require_conn()
    async with _lock:
        await conn.execute(
            """
            INSERT INTO usage
                (thread_id, ts, input_tokens, output_tokens, cache_read, cache_creation, cost_usd)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                thread_id,
                time.time(),
                input_tokens,
                output_tokens,
                cache_read,
                cache_creation,
                cost,
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


async def get_user_usage_tokens(user_id: int, since: float | None = None) -> int:
    """Total input+output tokens a user has spent across ALL their sessions. With
    ``since`` (epoch seconds), counts only usage at-or-after that time — the basis
    for the rolling-window rate limits (#120). A user owns the DM rows whose
    chat_id == their id, so we sum usage joined on that."""
    conn = _require_conn()
    query = (
        "SELECT COALESCE(SUM(u.input_tokens + u.output_tokens), 0) AS t "
        "FROM usage u JOIN threads th ON u.thread_id = th.thread_id "
        "WHERE th.chat_id = ?"
    )
    params: list = [user_id]
    if since is not None:
        query += " AND u.ts >= ?"
        params.append(since)
    async with _lock:
        cur = await conn.execute(query, params)
        row = await cur.fetchone()
        await cur.close()
    return int(row["t"] or 0)


async def get_user_usage_breakdown(user_id: int) -> dict:
    """Per-user input+output token usage over the trailing day / week plus the
    lifetime total and request count (feeds the per-user stats card, #120). Windows
    are computed from usage.ts, so no reset job is needed."""
    now = time.time()
    day_since = now - 86400
    week_since = now - 7 * 86400
    conn = _require_conn()
    async with _lock:
        cur = await conn.execute(
            "SELECT "
            "COALESCE(SUM(CASE WHEN u.ts >= ? THEN u.input_tokens + u.output_tokens ELSE 0 END), 0) AS day, "
            "COALESCE(SUM(CASE WHEN u.ts >= ? THEN u.input_tokens + u.output_tokens ELSE 0 END), 0) AS week, "
            "COALESCE(SUM(u.input_tokens + u.output_tokens), 0) AS total, "
            "COUNT(*) AS requests "
            "FROM usage u JOIN threads th ON u.thread_id = th.thread_id "
            "WHERE th.chat_id = ?",
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
            "COALESCE(favorite, 0) AS favorite "
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
        cwd = str(Path(base_workdir) / str(key))
        session_mode = "code" if mode == "code" else "chat"
        await conn.execute(
            "INSERT INTO threads (thread_id, chat_id, mode, model, cwd, "
            "code_session_id, name, permission_mode, chat_session_id, big_memory, "
            "created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, NULL, ?, 'default', NULL, 0, ?, ?)",
            (key, user_id, session_mode, default_model, cwd, name, user_id, time.time()),
        )
        await conn.commit()
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
    """Delete a DM session (and its usage + message rows). Returns True if a row
    was removed.

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
        await conn.execute("DELETE FROM usage WHERE thread_id = ?", (key,))
        await conn.execute("DELETE FROM messages WHERE thread_id = ?", (key,))
        await conn.commit()
    return removed > 0


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
