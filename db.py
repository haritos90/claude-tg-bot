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
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

import aiosqlite

logger = logging.getLogger("db")

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
        # #165: the per-turn MODEL and the live CONTEXT size are needed to compute the
        # weighted "usage units" metric (a cost-aware proxy for the official windows;
        # see get_user_usage_units). Older rows have NULL model / 0 context — they
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
            "COALESCE(shell_mode, 0) AS shell_mode, "
            "tools_enabled, "
            "COALESCE(hot_cache_timer, 0) AS hot_cache_timer, "
            "COALESCE(auto_compact, 0) AS auto_compact "
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


async def set_hot_cache_timer(thread_id: int, on: bool) -> None:
    """Persist the per-session warm-cache post-reply note toggle (#164)."""
    conn = _require_conn()
    async with _lock:
        await conn.execute(
            "UPDATE threads SET hot_cache_timer = ? WHERE thread_id = ?",
            (1 if on else 0, thread_id),
        )
        await conn.commit()


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
                (thread_id, ts, input_tokens, output_tokens, cache_read, cache_creation,
                 cost_usd, model, context_tokens)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                thread_id,
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


async def get_user_usage_units(user_id: int, since: float | None = None) -> int:
    """Total weighted usage UNITS a user has spent across all their sessions (#165) —
    the cost-aware basis for the rolling-window caps, replacing the raw input+output
    sum (which ignored cache tokens and model weight, so a user looked cheap while the
    owner's window drained). With ``since`` (epoch seconds), counts only at-or-after
    that time."""
    conn = _require_conn()
    query = (
        f"SELECT COALESCE(SUM({_units_sql_expr()}), 0) AS u "
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
    return int(row["u"] or 0)


async def get_user_units_breakdown(user_id: int) -> dict:
    """Weighted usage UNITS over the trailing day / week plus the lifetime total (#165),
    mirroring get_user_usage_breakdown but in cost-weighted units (feeds the per-user
    card + /limits)."""
    now = time.time()
    day_since = now - 86400
    week_since = now - 7 * 86400
    expr = _units_sql_expr()
    conn = _require_conn()
    async with _lock:
        cur = await conn.execute(
            f"SELECT "
            f"COALESCE(SUM(CASE WHEN u.ts >= ? THEN {expr} ELSE 0 END), 0) AS day, "
            f"COALESCE(SUM(CASE WHEN u.ts >= ? THEN {expr} ELSE 0 END), 0) AS week, "
            f"COALESCE(SUM({expr}), 0) AS total "
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
    }


async def get_all_users_usage() -> list[dict]:
    """Per-user token-usage aggregate for the owner stats dashboard (#164):
    trailing-day / trailing-week / lifetime input+output tokens, request count and
    last-activity ts — one row per DM user, busiest week first. The handler maps
    chat_id → username via the allowlist.

    Only DM users (``chat_id > 0`` == the user's Telegram id) count: a group /
    supergroup chat has a negative ``-100…`` chat_id and is NOT a person, so it is
    excluded (it would otherwise show up as a phantom 'user' — #164 follow-up)."""
    now = time.time()
    day_since = now - 86400
    week_since = now - 7 * 86400
    conn = _require_conn()
    async with _lock:
        cur = await conn.execute(
            "SELECT th.chat_id AS uid, "
            "COALESCE(SUM(CASE WHEN u.ts >= ? THEN u.input_tokens + u.output_tokens ELSE 0 END), 0) AS day, "
            "COALESCE(SUM(CASE WHEN u.ts >= ? THEN u.input_tokens + u.output_tokens ELSE 0 END), 0) AS week, "
            "COALESCE(SUM(u.input_tokens + u.output_tokens), 0) AS total, "
            "COUNT(*) AS requests, COALESCE(MAX(u.ts), 0) AS last_ts "
            "FROM usage u JOIN threads th ON u.thread_id = th.thread_id "
            "WHERE th.chat_id > 0 "          # DM users only; groups (chat_id<0) are not people
            "GROUP BY th.chat_id ORDER BY week DESC, total DESC",
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
        # #140: name the workdir by the stable PUBLIC sid, not the raw numeric
        # key, so the directory matches the id shown in /sessions and the export
        # filename and never leaks the internal numbering on disk.
        # was: cwd = str(Path(base_workdir) / str(key))  — replaced for #140
        # #181: nested layout — the session cwd is <sid>/work (state is the sibling).
        cwd = str(Path(base_workdir) / session_sid(key) / "work")
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
        await conn.execute("DELETE FROM session_uid WHERE sid = ?", (session_sid(key),))  # #221
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
    """Group sids by their host uid; return only the uids shared by MORE THAN ONE sid
    (a per-session isolation break). Pure + testable; the disk scan below feeds it."""
    by_uid: dict[int, list[str]] = {}
    for sid, uid in uid_by_sid.items():
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
