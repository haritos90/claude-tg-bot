# Architecture

The bot is one Python package, `app`, run with `python -m app` (`app/__main__.py` calls
`app.bot.main`). It reaches Claude through the Claude Agent SDK, which drives a `claude` CLI
subprocess per session. All state is one SQLite database; there is no external service.

## Module map

| Path | Responsibility |
|---|---|
| `app/bot.py` | Wiring, middleware, long polling, graceful shutdown. |
| `app/watchdog.py` | systemd liveness watchdog: `READY=1` before any network I/O, `WATCHDOG=1` after a successful Telegram probe, so a wedged connection auto-restarts the unit. No-op off systemd. |
| `app/config.py` | `.env` → `Settings`; warns if `ANTHROPIC_API_KEY` is set. |
| `app/i18n.py` | Localization table + `t(key, lang, …)`; `en` canonical, `ru` translation; per-user locale cache. |
| `app/core/engine.py` | `ClaudeSession` over the Agent SDK. All SDK code lives here, including the sandbox launcher. |
| `app/core/sessions.py` | `SessionManager`: per-session worker, the chaining queue, `/stop`, usage accounting, idle reaping. |
| `app/core/token_refresh.py` | Background refresh of the subscription OAuth credential before it expires. |
| `app/core/schedules.py` | Recurring / one-shot schedule runner. |
| `app/core/transcribe.py` | Optional on-device voice-note transcription (ffmpeg + faster-whisper), run host-side. |
| `app/core/agent_context.md` | Agent self-description appended to both system prompts (runtime asset). |
| `app/core/code_addendum.md` | Code-only addendum to the self-description (shell mode, file delivery, `/secret`). |
| `app/storage/db.py` | `aiosqlite` state: sessions, usage, conversation log, key-value store. |
| `app/storage/archive.py` | Cold storage: on delete, gzip a session's workdir + transcript into one archive. |
| `app/storage/usage.py` | Formatters for the 5h / 7d subscription windows plus the account-usage fetch. |
| `app/access/access.py` | Middleware: allowlist (drops non-allowed updates) and per-user language. |
| `app/access/allowlist.py` | JSON-backed access store: levels, expiry, usage caps; owner always allowed; fail-closed. |
| `app/access/permissions.py` | `PermissionGate`: the code-mode Allow/Deny approval gate. |
| `app/access/settings_schema.py` | Settings registry and resolver: each setting's type/default, storage tier, and access model. |
| `app/telegram/handlers.py` | aiogram router: commands, text/photo/document routing, callbacks, the `/` menu. |
| `app/telegram/commands.py` | Source of truth for the command set and localized menu labels; `/help` and `setMyCommands` derive from it. |
| `app/telegram/streamer.py` | Live reply: draft streaming in DM, code/table rendering, attachment interleaving, usage footer. |
| `app/telegram/markup.py` | Telegram formatting: Markdown→HTML, size-safe splitting, long-output-as-file. |
| `app/telegram/rich_message.py` | Binding for Bot API 10.1 `sendRichMessage` — native tables. |
| `app/telegram/svg_image.py` | Rasterizes a reply's inline `<svg>` diagram to PNG (both modes). |
| `app/telegram/table_image.py` | PNG rendering for wide (>20-column) tables, sent as an image in place. |
| `deploy/` | Out-of-process helpers: the systemd unit, the bubblewrap launcher, and the egress / broker / seccomp scripts. |

The Agent SDK is pinned to `claude-agent-sdk==0.2.101`; re-introspect the message and option types
before changing `engine.py` if you bump it.

## Data and isolation

What the bot persists, the on-disk layout, and the SQLite schema are in
[data-model.md](data-model.md). The sandbox that contains each session is in
[isolation.md](isolation.md). Message rendering is in [markup.md](markup.md).
