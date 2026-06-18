# Data model

The complete picture of what the bot persists, where it lives on disk, and who owns
it. The security mechanism that enforces the isolation described here is specified
separately in [`isolation.md`](isolation.md).

All state is local to the host running the bot; there is no external datastore.

## Storage locations

| Path | Contents | Owner / mode |
|---|---|---|
| `<repo>/` | Application code, `.env`, `allowlist.json`, `bot.db` | service user (root) |
| `<repo>/.env` | `TELEGRAM_BOT_TOKEN`, `OWNER_ID`, knobs | root, gitignored |
| `<repo>/allowlist.json` | Per-user access records (below) | root `0600`, gitignored |
| `<repo>/bot.db` (+ `-wal`, `-shm`) | SQLite state (below) | root, gitignored |
| `BASE_WORKDIR` = `/var/lib/claude-tg-bot/workdirs/` | Per-session working trees + archives | root, `0711` |
| `~/.claude/.credentials.json` | The subscription OAuth token | root `0600` |
| `/usr/local/bin/claude` | Staged copy of the CLI for unprivileged jails | root `0755` |

`BASE_WORKDIR` lives under `/var/lib` (not the repo, which is under the root-only
`/root`) so that a per-session **unprivileged** jail uid can traverse to its own
working directory — a non-root uid cannot enter `/root` (mode `0700`). The base and
each session directory are `0711` (traversable, not listable); a session's own files
are `0700` and owned by that session's uid.

## Per-session directory layout

Each session owns one directory named by its **public session id** (`<sid>` =
`sha1("sess:"+thread_id)[:6]`). Nothing for a session is stored outside it.

```
/var/lib/claude-tg-bot/workdirs/
├── <sid>/                         0711, root            ← one per session
│   ├── work/                      0700, session uid     ← the agent's cwd (bound into the jail, writable)
│   ├── state/                     0700, session uid     ← jail HOME → ~/.claude/projects: the transcript
│   │   └── <encoded-cwd>/….jsonl                          (NOT bound into the jail; unreachable by the agent)
│   └── secrets.env                0600, root            ← optional per-session user creds (#119d), env-injected
└── _archive/<owner_id>/<sid>-<stamp>.tar.gz   0700, root  ← cold storage on delete; auto-purged after retention
```

- `work/` is the only path bind-mounted writable into the jail.
- `state/` is a sibling, deliberately **not** bound into the jail, so the agent cannot
  reach its own transcript (or any other session) through its tools. The subdirectory
  name encodes the in-jail cwd (`/`→`-`); it must track the cwd or `resume` cannot find
  the history.
- `secrets.env` holds `KEY=VALUE` lines the user supplied via `/secret`; the launcher
  injects them as environment variables into that session's jail only. It is root-owned
  and never bound in (the values reach the jail as process env, not as a readable file).

## SQLite schema (`bot.db`, WAL mode)

Created on `db.init` and migrated **forward in place** — only additive, guarded
`ALTER TABLE … ADD COLUMN` (never a destructive rewrite or drop).

| Table | Key | Holds |
|---|---|---|
| `threads` | `thread_id` (PK) | One row per session: `chat_id`, `mode` (`chat`/`code`), `model`, `cwd`, the resumable `code_session_id` / `chat_session_id`, `name`, `created_by`, `created_at`, and per-session toggles added by migration (`permission_mode`, `effort`, `max_turns`, `big_memory`, `favorite`, `no_sandbox`, `tools_enabled`, `add_dirs`, `fork_pending`, `auto_compact`, `hot_cache_timer`). |
| `usage` | `id` (PK) | One row per turn: `thread_id`, `ts`, `input_tokens`, `output_tokens`, `cache_read`, `cache_creation`, `cost_usd`, `model`, `context_tokens`. Per-user totals roll up via `JOIN threads ON chat_id`. |
| `messages` | `id` (PK) | Conversation log (`thread_id`, `ts`, `role`, `text`) feeding `/last` / `/recap` / `/history`; indexed `(thread_id, id)`. |
| `kv` | `key` (PK) | Small key-value state: per-user current session (`dm_current:<uid>`), `dm_seq`, usage-display mode, pinned-message id, per-user `lang:<uid>`, access overrides, user defaults, `archive_retention_days`, `max_sessions_default`. |
| `rate_history` | `id` (PK) | Append-only subscription rate-limit snapshots (`ts`, `rate_type`, `utilization`, `status`) feeding the `/status` trend. |

A DM session's `thread_id` is a synthetic **negative** id minted from `kv.dm_seq` with
`chat_id == user_id == created_by`; supergroup topics are `>= 0` (0 = General, frozen).
`thread_id` is the only stable id; `<sid>` is its public render.

### Per-user access records (`allowlist.json`)

One record per allowlisted user (the owner is synthesised in memory, never written):
`level` (`chat`/`code`), `expires_at`, `token_grant`, `rate` (`{day, week}`),
`max_sessions` (per-user session cap; `null` = inherit the global default,
`0` = unlimited), `global_memory`, `allow_max_effort`, `tool_cap`, `access`
(per-option exceptions), `friendly_name`. The owner's self-imposed equivalents live
under `owner_prefs`.

## Credentials — where the token lives

The subscription OAuth token is **never** in `bot.db`, never in `allowlist.json`, and
never copied into a session directory.

- It lives only in `~/.claude/.credentials.json` (service user, `0600`), refreshed
  before expiry by `token_refresh.py`.
- With the credential broker on, it is **never placed in a jail**: the jail receives a
  `BROKER-PLACEHOLDER` dummy, and a host-side broker injects the real token on the
  outbound request. Without the broker, the real token is bind-mounted read-only into
  the jail.

A session's own files are owned by its per-session host uid (escape-hardening), so even
a jail that escapes its mount namespace cannot read another session's files. The full
mechanism — broker, egress allowlist, per-session uid, seccomp, cgroup limits — is in
[`isolation.md`](isolation.md).
