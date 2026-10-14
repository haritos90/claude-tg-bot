# Configuration

Every setting is an environment variable read from `.env` at startup. Only
`TELEGRAM_BOT_TOKEN` and `OWNER_ID` are required; everything else has a default
derived from the host or a built-in constant. [`.env.example`](../.env.example)
is the annotated starting template; this file is the full reference.

The sandbox and containment flags (`SANDBOX_CODE`, `CRED_BROKER`,
`SANDBOX_EGRESS`, `SANDBOX_SECCOMP`, `SANDBOX_PER_SESSION_UID`, `SANDBOX_EXEC`,
the per-session uid range, the broker/proxy ports, the cgroup caps,
`EGRESS_ALLOW_HOSTS`) are specified in [isolation.md](isolation.md) and not
repeated here.

## Core

| Variable | Default | Meaning |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | BotFather token. Required. |
| `OWNER_ID` | — | Your numeric Telegram id — the always-allowed owner. Required. |
| `DEFAULT_MODEL` | `opus` | Model for new sessions: a Claude Code CLI family alias (`opus` / `sonnet` / `haiku` / …) that the CLI resolves to the newest model of that family, or a pinned id. Model versions are never hardcoded — see *Models and the CLI* below. |
| `BASE_WORKDIR` | `./workdirs` | Root of the per-session working trees and archives. Must sit outside `/root` when per-session uids are on (the deployment uses `/var/lib/claude-tg-bot/workdirs`). |
| `DB_PATH` | `./bot.db` | SQLite state file. |
| `ALLOWLIST_PATH` | `./allowlist.json` | Per-user access store. |
| `BLOCKED_PROMPT_KEYWORDS` | — | Extra prompt keywords to defuse, on top of the built-in `ultrathink` / `ultracode`. Comma- or space-separated. |

## Models and the CLI

No model, model version or effort level is hardcoded; the few deliberate exceptions are listed
under *Deliberate exceptions* below. The Claude Code CLI is the source of truth:

- **Models.** The CLI's model catalog (its `initialize` response) lists the family aliases
  (`opus`, `sonnet`, `haiku`, …), the CLI's own `default`, and pinned version ids, each with the
  concrete model it resolves to and a display name. The `/model` picker lists the aliases; a
  session stores the alias it was given, and the CLI resolves it to the newest model of that
  family, so a model release reaches every session with the next CLI update. A typed
  `/model claude-…` pins an exact version (shown with 📌). A throwaway probe of the host CLI (no
  prompt, no tokens) reads the catalog 20 s after startup and after every CLI update; it is
  persisted, so menus are correct right after a restart. The probe's catalog is authoritative: a
  sandboxed session's CLI sees only the credential broker's dummy token and reports a reduced list
  (family names without versions, no pinned ids), which only fills in before the first probe.
- **Effort.** The `/effort` picker lists the levels the CLI reports for the session's model (none
  for a model that takes no effort). With no explicit level the CLI's per-model default applies;
  it is read from the CLI (`get_settings`) and shown, for example, as "default (medium)". Level
  names are translated when the i18n catalog happens to have the name, otherwise shown as the CLI
  spells them.
- **Context window.** Each session runs its model's native context window, as the CLI knows it —
  1M on the current models (Opus 5.5, Sonnet 5.5, Opus 5, Fable…), 200K on Haiku 4.5. There is no
  1M switch: the CLI offers no size choice for a model whose 1M window is native. The CLI's
  auto-compaction keeps a long session within the window.
- **Display.** A new session confirms with its mode glyph and the model it runs on, its version
  and effort — `💬 Opus 5.5 · medium` — named by the CLI's display name of what the alias
  resolves to (the CLI's `default` shows as the model it currently means).
- **CLI updates.** Once a day at `CLI_UPDATE_AT_UTC` the bot runs the host CLI's own updater
  (`claude update`) and re-stages the sandbox copy at `/usr/local/bin/claude`. A run missed while
  the bot was down happens at the next start. When the binary changed, sessions move to it
  without cutting a reply: idle clients are closed at once and reconnect (resuming the
  conversation) on their next message; a client in the middle of a reply moves once that reply is
  done.
- **Migration.** On the first start with this scheme, concrete ids stored by earlier versions
  (`claude-opus-4-8` …) are rewritten once to their family alias.

| Variable | Default | Meaning |
|---|---|---|
| `MODEL_PICKER` | — | Comma-separated catalog values the `/model` picker may offer (e.g. `opus,sonnet,haiku`). Empty = every alias the CLI offers (minus withheld families). |
| `CLI_UPDATE_AT_UTC` | `12:00` | Daily time (UTC, `HH:MM`) of the CLI update round described above; `off` = never. The owner can change it at runtime in Settings → Admin → CLI update, which also offers "check now". Replaces `CLI_UPDATE_INTERVAL_HOURS`; a legacy `CLI_UPDATE_INTERVAL_HOURS=0` still disables updates when this variable is unset. |
| `THINKING_MODEL_LINE` | on | Experimental: the first line of the animated "Thinking…" indicator names the model, its version and the effort the reply runs at (`Opus 5.5 · medium`); `0` turns it off. A draft Telegram rejects with the line is retried without it. |
| `DRAFT_HOLD_OPEN_TABLES` | off | Opt-in workaround for the Telegram iOS client, which does not draw rows added to a table it has already rendered: a table enters the streaming draft only once complete (an animated "building a table" note stands in). Off = tables stream row by row. |
| `DRAFT_PUSH` | `all` | Telegram holds a message the user sends while a reply draft is streaming and delivers it only once the draft ends. The draft carries Telegram's own stop button; in this bot pressing it means **push**, not stop: the draft ends on the client (which lets the held message through), the reply carries on in a new draft and the message is folded into the running reply. Pressed with no message waiting (none arrives within 1 s — a held message comes 20–30 ms after the press), it stops the reply like `/stop`. The button's look and its press animation are Telegram's. `all` = every chat, `owner` = the owner's chat only, `off` = no button. |
| `DRAFT_RELEASE` | `off` | Withdrawn experiment: while only the "Thinking…" indicator showed, the bot periodically landed and deleted a tiny message to let a held message through; every such message raised a notification (silent delivery only drops the sound). `owner` / `all` turn it back on. |
| `DRAFT_RELEASE_SECS` | `3` | Period of that withdrawn cycle, in seconds. |

### Deliberate exceptions

Each item below is model-specific knowledge kept in code on purpose; everything else follows the
CLI.

| Exception | Where | Why |
|---|---|---|
| `max` effort is a per-user grant | `handlers._may_max_effort`, `SessionManager._effective_settings` | It is the most expensive setting against the shared subscription and a budget decision, not a model property. Without the grant `max` is hidden; a stored `max` runs one level lower in the CLI's list for that model. |
| The Fable family is withheld from everyone | `models._HIDDEN_FAMILIES` | Offering the CLI's top tier is a per-host, per-user budget decision (meant for hosts on a Max plan) that needs its own grant, like `max`. Until that grant exists nobody, the owner included, can pick it; a stored Fable value runs as the default model. |
| Only two account windows are tracked | `usage.ACCOUNT_WINDOWS` | The subscription has exactly two limits, the ~5-hour and the weekly window; the usage endpoint still returns transitional per-model windows that carry no data. A window added later stays hidden until listed. |
| Pinned ids are recognised by the `claude-` prefix | `models._PINNED_PREFIX` | The catalog carries no alias/pinned flag; every concrete id it lists starts with `claude-` and no alias does. |

Per-user usage caps count raw tokens (input + output) — no per-model weights, so a cap means the
same on every model.

## Concurrency and resources

Each active session holds a `claude` subprocess (~400–600 MB). The bot self-limits
on RAM and CPU and reaps idle subprocesses.

Rough capacity on Debian 12/13:

| RAM | Concurrent turns | Live clients |
|---|---|---|
| 2 GB | 2 | 2 |
| 4 GB | 4 | ~5 |
| 6 GB | 6 | ~9 |
| 8 GB | 8 | ~13 |

Defaults: `live = (RAM_MB − 900) / 550` and `turns = min(live, 2 × CPU)`.
Configure at least 2 GB of swap for safety.

| Variable | Default | Meaning |
|---|---|---|
| `MAX_LIVE_CLIENTS` | from RAM | Max simultaneously-live `claude` subprocesses (idle and busy). |
| `MAX_CONCURRENT_TURNS` | from RAM/CPU | Max turns generating at once; overflow queues. |
| `IDLE_TTL_SEC` | `360` | Reap a session's subprocess after this many seconds idle (the warm-cache window). |
| `IDLE_RESET_SEC` | `2700` | After this long idle, the next message starts a fresh session; `0` = never. |
| `SHELL_TTL_SEC` | `86400` | A persistent `/shell` outlives the subprocess reap; kept this long. `0` = until delete. |
| `MIN_FREE_MB` | `400` | Below this much free RAM, evict idle sessions before starting a turn. |
| `MAX_SESSIONS_PER_USER` | `500` | Default per-user session cap (owner-overridable per user and in Settings → Admin; `0` = unlimited). |
| `ARCHIVE_RETENTION_DAYS` | `180` | Purge a deleted session's archive after this many days (`0` = keep forever). |

## OAuth token refresh

The subscription access token lasts about 8 hours; a background loop renews it before expiry and
warns the owner before the monthly login credential expires.

| Variable | Meaning |
|---|---|
| `OAUTH_REFRESH` | Enable the refresh loop (on by default). |
| `OAUTH_REFRESH_INTERVAL_SEC` | Sweep interval. |
| `OAUTH_REFRESH_SKEW_SEC` | Renew this long before the token's stated expiry. |
| `OAUTH_REFRESH_SWEEP_DEADLINE_SEC` | Per-sweep deadline; an overrun flags a DNS/network wedge. |
| `OAUTH_REFRESH_HEARTBEAT_EVERY` | Emit a liveness log line every N sweeps; a gap means the loop died. |
| `LOGIN_EXPIRY_WARN_DAYS` | Warn the owner this many days before the login credential expires. |
| `OAUTH_ALERT_AFTER_FAILS` | Alert the owner in chat after this many consecutive failed sweeps (a login that died before its stated expiry). |
| `OAUTH_ALERT_REPEAT_SWEEPS` | Re-send that alert every N sweeps while the login stays broken. |

## Voice transcription

Set `VOICE_TRANSCRIPTION=1` and install the voice extras. Runs on-device on
CPU; the speech model (~150 MB) downloads once on first use. Model choice (`VOICE_MODEL`), the
length cap (`VOICE_MAX_SECONDS`), language, and the full picture are in [voice.md](voice.md).

## MAX messenger

Off by default. Set `MAX_BOT_TOKEN` (from the bot's settings at business.max.ru) and the same bot
serves MAX dialogs over long polling, with the full command set. MAX identities live in their own
id range (`app/max/ids.py`): a MAX user's sessions, allowlist entry, usage and defaults are
separate from any Telegram user's, the owner's own MAX account is an ordinary user to allow, and
admin stays on Telegram — owner commands, access-request notices (which arrive with the MAX user's
internal id and the one-tap Allow buttons) and code-mode tool approvals. Replies are sent whole
once complete; a "Thinking…" message stands in while the model works. Group chats and channels
are ignored. The platform has one global command list (no per-user or per-language scopes), so
it carries the whole shared menu — chat and code commands, no owner commands — in the default
language; the `/` hint list and the inline menus (`/settings`, `/sessions`, pickers) work as on
Telegram.

| Variable | Default | Meaning |
|---|---|---|
| `MAX_BOT_TOKEN` | — | MAX bot token; empty = MAX off. |
| `MAX_API_BASE` | `https://platform-api2.max.ru` | Platform API host. |
| `MAX_CA_BUNDLE` | bundled | PEM the MAX client trusts in addition to the OS store. Empty = `deploy/certs/russian_trusted_root_ca.pem` (the Russian Trusted Root CA that signs the API host); `system` = the OS store alone. Trusted by the MAX client only, never installed system-wide. |

## Additional dependencies

| Feature | Needs |
|---|---|
| Voice input | `ffmpeg` and `faster-whisper` (`requirements/voice.txt`), `VOICE_TRANSCRIPTION=1` |
| MAX messenger | `MAX_BOT_TOKEN`; no extra packages (the bundled CA covers TLS) |
| SVG diagrams in chat | `libcairo2` (`apt install libcairo2`) for `cairosvg`; without it the raw `.svg` is sent |
| Egress allowlist | `iptables` with the `xt_cgroup` module and cgroup v2 (on by default; set `SANDBOX_EGRESS=0` if the host lacks them) — see [isolation.md](isolation.md) |
