# Configuration

Every setting is an environment variable read from `.env` at startup. Only `TELEGRAM_BOT_TOKEN`
and `OWNER_ID` are required; everything else has a default derived from the host or a built-in
constant. [`.env.example`](../.env.example) is the annotated starting template; this file is the
full reference.

The sandbox and containment flags (`SANDBOX_CODE`, `CRED_BROKER`, `SANDBOX_EGRESS`,
`SANDBOX_SECCOMP`, `SANDBOX_PER_SESSION_UID`, `SANDBOX_EXEC`, the per-session uid range, the
broker/proxy ports, the cgroup caps, `EGRESS_ALLOW_HOSTS`) are specified in
[isolation.md](isolation.md) and not repeated here.

## Core

| Variable | Default | Meaning |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | BotFather token. Required. |
| `OWNER_ID` | — | Your numeric Telegram id — the always-allowed owner. Required. |
| `DEFAULT_MODEL` | `claude-opus-4-8` | Model for new sessions (`/model` aliases: opus / sonnet / haiku). |
| `BASE_WORKDIR` | `./workdirs` | Root of the per-session working trees and archives. Must sit outside `/root` when per-session uids are on (the deployment uses `/var/lib/claude-tg-bot/workdirs`). |
| `DB_PATH` | `./bot.db` | SQLite state file. |
| `ALLOWLIST_PATH` | `./allowlist.json` | Per-user access store. |
| `BLOCKED_PROMPT_KEYWORDS` | — | Extra prompt keywords to defuse, on top of the built-in `ultrathink` / `ultracode`. Comma- or space-separated. |

Do not set `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN`; either forces paid per-token billing
instead of the subscription. The bot strips them from the agent's environment and warns at startup
when `ANTHROPIC_API_KEY` is set.

## Concurrency and resources

Each active session holds a live `claude` subprocess (~400–600 MB RSS — the dominant memory cost;
the bot itself is ~130 MB, and `opus` with a 1M context sits at the high end). The bot self-limits
on RAM and CPU and reaps idle subprocesses: the process is closed, the transcript stays on disk,
and `resume` rebuilds it on the next message, so no history is lost. Only simultaneously-active
turns cost RAM, so a box serves many more users than its live-client count.

Rough capacity on Debian 12/13 (defaults auto-derived at startup):

| RAM | Concurrent turns | Live clients | Notes |
|---|---|---|---|
| 2 GB | 2 | 2 | tight — add 2–4 GB swap; prefer sonnet / haiku |
| 4 GB | 4 | ~5 | comfortable for a small group |
| 6 GB | 6 | ~9 | |
| 8 GB | 8 | ~13 | |

Defaults are `live = (RAM_MB − 900) / 550` and `turns = min(live, 2 × CPU)`. Configure swap as an
OOM backstop: with no swap, exhausting RAM is a hard kill.

| Variable | Default | Meaning |
|---|---|---|
| `MAX_LIVE_CLIENTS` | from RAM | Max simultaneously-live `claude` subprocesses (idle and busy). |
| `MAX_CONCURRENT_TURNS` | from RAM/CPU | Max turns generating at once; overflow queues. |
| `IDLE_TTL_SEC` | `360` | Reap a session's subprocess after this many seconds idle (the warm-cache window). |
| `IDLE_RESET_SEC` | `2700` | After this long idle, the next message starts a fresh session context instead of resuming (the previous transcript stays on disk); `0` = never. |
| `SHELL_TTL_SEC` | `86400` | A persistent `/shell` outlives the subprocess reap (~3 MB vs ~500 MB); kept this long. `0` = until delete. |
| `MIN_FREE_MB` | `400` | Below this much free RAM, evict idle sessions before starting a turn. |
| `MAX_SESSIONS_PER_USER` | `500` | Default per-user session cap (owner-overridable per user and in Settings → Admin; `0` = unlimited). |
| `ARCHIVE_RETENTION_DAYS` | `180` | Purge a deleted session's archive after this many days (`0` = keep forever). |

## OAuth token refresh

The subscription access token lasts about 8 hours; a background loop renews it before expiry and
warns the owner before the monthly login credential itself lapses. Subscription only — never an API
key.

| Variable | Meaning |
|---|---|
| `OAUTH_REFRESH` | Enable the refresh loop (on by default). |
| `OAUTH_REFRESH_INTERVAL_SEC` | Sweep interval. |
| `OAUTH_REFRESH_SKEW_SEC` | Renew this long before the token's stated expiry. |
| `OAUTH_REFRESH_SWEEP_DEADLINE_SEC` | Per-sweep deadline; an overrun flags a DNS/network wedge. |
| `OAUTH_REFRESH_HEARTBEAT_EVERY` | Emit a liveness log line every N sweeps; a gap means the loop died. |
| `LOGIN_EXPIRY_WARN_DAYS` | Warn the owner this many days before the login credential expires. |

## Voice transcription

Off by default. Set `VOICE_TRANSCRIPTION=1` and install the voice extras
(`pip install -r requirements/voice.txt` plus the `ffmpeg` system binary). Both run on-device on
CPU; the speech model (~150 MB) downloads once on first use. Model choice (`VOICE_MODEL`), the
length cap (`VOICE_MAX_SECONDS`), language, and the full picture are in [voice.md](voice.md).

## Additional dependencies

| Feature | Needs |
|---|---|
| Voice input | `ffmpeg` and `faster-whisper` (`requirements/voice.txt`), `VOICE_TRANSCRIPTION=1` |
| SVG diagrams in chat | `libcairo2` (`apt install libcairo2`) for `cairosvg`; without it the raw `.svg` is sent |
| Egress allowlist | `iptables` with the `xt_cgroup` module and cgroup v2 (on by default; set `SANDBOX_EGRESS=0` if the host lacks them) — see [isolation.md](isolation.md) |
