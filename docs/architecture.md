# Architecture

The bot is one Python package, `app`, run with `python -m app` (`app/__main__.py` calls
`app.bot.main`). It reaches Claude through the Claude Agent SDK, which drives a `claude` CLI
subprocess per session. All state is one SQLite database.

## Module map

| Path                            | Responsibility                                                                                                |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| Path                            | Responsibility                                                                                                |
| `app/bot.py`                    | Wiring, middleware, long polling, graceful shutdown.                                                          |
| `app/watchdog.py`               | systemd liveness watchdog: `READY=1` before any network I/O, `WATCHDOG=1` after a successful Telegram probe.  |
| `app/config.py`                 | `.env` → `Settings`; warns if `ANTHROPIC_API_KEY` is set.                                                     |
| `app/i18n.py`                   | Localization table + `t(key, lang, …)`.                                                                       |
| `app/core/engine.py`            | `ClaudeSession` over the Agent SDK. All SDK code lives here, including the sandbox launcher.                  |
| `app/core/sessions.py`          | `SessionManager`: per-session worker (messages sent mid-reply go into the running CLI turn; a turn the CLI starts for one renders as its own reply), `/stop`, usage accounting, idle reaping, session auto-naming and the untitled-session sweep, the daily CLI update with graceful client recycling (idle clients move to a new binary at once, busy ones after their reply). |
| `app/core/models.py`            | The model + effort catalog read from the Claude Code CLI (aliases, what each resolves to, display names, effort levels, per-model default effort); persisted in kv; a token-free probe of the host CLI. No model is hardcoded beyond the deliberate exceptions listed in [configuration.md](configuration.md) (the withheld Fable family, the `max` grant). |
| `app/core/cli_update.py`        | Keeps the CLI current: runs `claude update` and re-stages the jail copy at `/usr/local/bin/claude`.           |
| `app/core/token_refresh.py`     | Background refresh of the subscription OAuth credential before it expires.                                    |
| `app/core/schedules.py`         | Recurring / one-shot schedule runner.                                                                         |
| `app/core/transcribe.py`        | Optional on-device voice-note transcription (ffmpeg + faster-whisper), run host-side.                         |
| `app/core/agent_context.md`     | Agent self-description appended to both system prompts (runtime asset).                                       |
| `app/core/code_addendum.md`     | Code-only addendum to the self-description (shell mode, file delivery, `/secret`).                            |
| `app/storage/db.py`             | `aiosqlite` state: sessions, usage, conversation log, key-value store.                                        |
| `app/storage/archive.py`        | Cold storage: on delete, gzip a session's workdir + transcript into one archive.                              |
| `app/storage/usage.py`          | Formatters for the 5h / 7d subscription windows plus the account-usage fetch.                                 |
| `app/access/access.py`          | Middleware: allowlist (drops non-allowed updates) and per-user language.                                      |
| `app/access/allowlist.py`       | JSON-backed access store: levels, expiry, usage caps; owner always allowed; fail-closed.                      |
| `app/access/permissions.py`     | `PermissionGate`: the code-mode Allow/Deny approval gate.                                                     |
| `app/access/settings_schema.py` | Settings registry and resolver: each setting's type/default, storage tier, and access model.                  |
| `app/telegram/handlers.py`      | aiogram router: commands, text/photo/document routing, callbacks, the `/` menu.                               |
| `app/telegram/commands.py`      | Source of truth for the command set and localized menu labels; `/help` and `setMyCommands` derive from it.    |
| `app/telegram/streamer.py`      | Live reply: draft streaming in DM, code/table rendering, attachment interleaving, usage footer.               |
| `app/telegram/markup.py`        | Telegram formatting: Markdown→HTML, size-safe splitting, long-output-as-file.                                 |
| `app/telegram/rich_message.py`  | Binding for Bot API 10.1 `sendRichMessage` — native tables.                                                   |
| `app/telegram/svg_image.py`     | Rasterizes a reply's inline `<svg>` diagram to PNG (both modes).                                              |
| `app/telegram/table_image.py`   | PNG rendering for wide (>20-column) tables, sent as an image in place.                                        |
| `app/max/ids.py`                | The MAX identity namespace: a MAX user id is offset into its own integer range before it enters the dispatcher, so MAX and Telegram users, sessions, allowlist entries and usage never meet. Registries for MAX message ids and attachment URLs behind aiogram-shaped ints / file ids. |
| `app/max/client.py`             | Thin async client for the MAX Platform API (`platform-api2.max.ru`): token header, TLS against the bundled Russian Trusted Root CA, uploads, pacing under the platform's rate limit. |
| `app/max/html.py`               | Telegram HTML → MAX HTML, the 4000-character re-split, inline keyboard → MAX `inline_keyboard` attachment.    |
| `app/max/bridge.py`             | `MaxSession`: an aiogram `BaseSession` that translates outgoing Bot API methods into MAX calls (no streaming — the first draft becomes one "Thinking…" message that the finished reply replaces). `RoutingSession`: the bot's single session, routing each call to Telegram or MAX by its chat id. |
| `app/max/poller.py`             | MAX long-poller: rewrites `message_created` / `message_callback` / `bot_started` dialog updates as aiogram `Update`s and feeds the shared `Dispatcher`; the poll marker lives in kv. |
| `deploy/`                       | Out-of-process helpers: the systemd unit, the bubblewrap launcher, and the egress / broker / seccomp scripts, plus `certs/` (the Russian Trusted Root CA the MAX client trusts). |

The Agent SDK is pinned to `claude-agent-sdk==0.2.163`. The SDK's bundled CLI is used only by
an unjailed session; jailed sessions run the host's `claude` (staged at `/usr/local/bin/claude`
on start-up whenever the host CLI's resolved version path changed), so a model release that
needs a newer CLI takes effect with a host CLI update plus a service restart.

## Two messengers, one handler layer

The MAX messenger (max.ru) is served by the same `Dispatcher`, router, streamer, permission
gate and session manager as Telegram; nothing under `app/telegram/` or `app/core/` knows which
platform a chat belongs to. The seam is aiogram's own session: every outgoing Bot API call is a
typed method passed to `bot.session`, and the bot's session is a `RoutingSession` that forwards a
call to the real Telegram session or to `MaxSession` depending on the chat id. Inbound, the MAX
poller builds ordinary private-chat `Update` objects. MAX has no draft streaming, so a MAX reply is
delivered whole once complete, with a single "Thinking…" message standing in meanwhile. It has no
rich blocks either: the session reports `embeds_rich_media(chat_id) == False`, so the streamer
skips the embedded rich message and interleaves — the text is cut at each map pin, diagram or
wide table and that block is sent there as a location or photo message. Voice notes and
locations arrive through the same handlers as Telegram's. Identity
spaces are disjoint by construction (see `app/max/ids.py`): a MAX user is never the owner, owner
commands and access requests stay on Telegram, and a code session's tool-approval prompt is posted
to the owner's Telegram chat whoever owns the session.

## Data and isolation

What the bot persists, the on-disk layout, and the SQLite schema are in
[data-model.md](data-model.md). The sandbox that contains each session is in
[isolation.md](isolation.md). Message rendering is in [markup.md](markup.md).
