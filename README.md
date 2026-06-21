# Telegram bot for Claude via Claude Agent SDK

A private, multi-user Telegram bot that fronts Claude and Claude Code. The owner uses
it and can share access with other Telegram users; each user talks to the bot in a DM
and keeps named, isolated sessions (histories never cross). A session starts as chat
and can be upgraded to code and back — same conversation:

- chat — a Claude conversation with web tools (search + fetch); no terminal or files.
- code — a Claude Code agent with a working directory on the server; it runs shell
  commands and edits files (risky tools wait for an Allow/Deny tap, or run freely with
  `/auto on`). `/code` upgrades a chat (needs code access); `/chat` downgrades, keeping
  the files.

Everything runs on a Claude Pro/Max subscription via the
[Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk/overview) — no Anthropic
API key, no per-token billing.

[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)

---

## Features

- Streaming: native Telegram draft streaming (`sendRichMessageDraft`), DM only.
- Web-capable chat: chat sessions use `WebSearch`/`WebFetch`; code sessions add the
  full agent toolset (Bash, file edits, notebooks).
- Diagrams in chat: when a chat reply contains an inline SVG (a schematic, chart, or
  floor plan), the bot rasterizes it to PNG and sends it as an image. Claude has no
  image generator, so this is vector diagrams, not photos.
- Isolated sessions: each is its own Claude session (context, working dir, resume id),
  born chat and upgradeable to code (`/code` ⇄ `/chat`). Nothing leaks between them.
  Browse, switch, rename, star, and delete via `/sessions`.
- Allowlist access: only the owner and explicitly allowed users can talk to the bot.
  Each user has a level (chat or code), an optional expiry, and optional rolling usage
  caps (5h/week). The list lives in a gitignored `allowlist.json`. If you only have
  someone's phone or name, have them message the bot — the owner gets a one-tap access
  request with the person's id.
- Owner control from Telegram: `/settings` is a scope-tabbed hub (this session / my
  defaults / global). Open Users and tap a person to set their access, expiry, usage
  caps, global memory, max-effort, tools, and per-option access exceptions, and to see
  their usage. Per-session tools are set with `/tools`.
- Access model: every setting (model, effort, permissions, memory, language, …) has an
  owner-set base access — Delegated (user can change it), Read-only, or Hidden.
  Per-user exceptions live on the user card. Effective values are resolved per prompt
  (session → personal default → global), so a change applies on the next message.
- Approvals: code mode defaults to auto-edits — file edits and ordinary in-jail
  commands run without asking; only risky actions (push/publish, destructive deletes,
  web fetches) pause for an Allow/Deny tap. `/auto on` runs everything; `/permissions`
  switches auto-edits / plan / full-access.
- Usage display: `/usage` and `/status` show the subscription's 5h and 7d windows as
  "% left", in a footer or a pinned live message.
- Task chaining: a follow-up sent during or after a run queues into the same session,
  reusing context and the warm cache.
- Localized UI: English and Russian, auto-detected and changeable with `/language`
  (Claude's own answers are unaffected).
- Durable state: sessions, usage, settings, and language live in SQLite and survive a
  restart.

---

## How it works

```
You ──DM──▸ @your_bot
             └── /new ──▸ a chat session   (switch with /sessions · upgrade with /code)
                   ├── chat: Agent SDK + web research (WebSearch/WebFetch)
                   └── code: Agent SDK + full tools, cwd = BASE_WORKDIR/<session>
                                └── risky tool? ──▸ inline Allow / Deny
```

Long polling — no webhook, domain, or public port.

### One subscription, isolated memory

Every session — the owner's and other users' — runs on the same Pro/Max subscription
(a Telegram identity is not a separate Claude account), so they share one usage-limit
pool. There is no global or cross-session memory: the bot sets `setting_sources=[]`, so
no account- or machine-wide `CLAUDE.md` or settings load, and each session keeps only
its own conversation (its own resume id, persisted across restarts). The shared limit
pool is why per-user usage caps exist — see [Access control](#access-control).

---

## Message formatting

Claude replies in Markdown. The bot renders every reply as one native rich message (Bot
API 10.1 `sendRichMessage`, `rich_message={"markdown": …}`), so headings, lists,
checklists, quotes, side-scrolling tables, math, and code render natively without
client-side splitting; while generating, the reply streams already-formatted through
`sendRichMessageDraft`. Command replies and the inline-keyboard menus use the same path
(`_send_menu` / `_edit_menu`).

Classic `parse_mode="HTML"` (`markup.md_to_html`, a safe-subset Markdown→HTML converter)
is the fallback only: if a rich send/edit fails, the content is delivered as classic
HTML, and very long output falls back to a `.md` document — a message is never lost.

One client gap: a code block renders as plain monospace inside a rich message (no
language label or copy button) because the Telegram client does not yet style
`RichBlockPreformatted` (#174).

The rendering paths, the Markdown→HTML contract, the rich tag catalog, and the size
rules are specified in [markup.md](docs/markup.md). Telegram reference:
[Rich message formatting][tg-fmt] · [HTML style][tg-html].

[tg-fmt]: https://core.telegram.org/bots/api#rich-message-formatting-options
[tg-html]: https://core.telegram.org/bots/api#html-style

---

## Project structure

The code is grouped into the `app` package (run with `python -m app`):

| Path | Responsibility |
|---|---|
| `app/__main__.py` | Entry point — `python -m app` runs `app.bot.main()`. |
| `app/bot.py` | Wiring, middleware, long polling, graceful shutdown. |
| `app/watchdog.py` | systemd liveness watchdog — `READY=1` at startup, `WATCHDOG=1` after a successful Telegram probe, so a wedged connection triggers an auto-restart. |
| `app/config.py` | `.env` → `Settings` (warns if `ANTHROPIC_API_KEY` is set). |
| `app/i18n.py` | Localization table + `t(key, lang, …)`; `en` canonical, `ru` translation. |
| `app/core/engine.py` | `ClaudeSession` over the Agent SDK — all SDK code lives here, including the sandbox launcher. |
| `app/core/sessions.py` | `SessionManager`: per-session worker, the chaining queue, `/stop`, usage accounting. |
| `app/core/token_refresh.py` | Background refresh of the subscription OAuth credential (#191). |
| `app/core/schedules.py` | Recurring / one-shot schedule runner. |
| `app/core/agent_context.md` | Agent self-description loaded into the system prompt (runtime asset, co-located with `engine`). |
| `app/storage/db.py` | `aiosqlite` state: sessions, usage, conversation log, key-value store. |
| `app/storage/archive.py` | Cold storage (#177): on delete, bundle a session's workdir + transcript into one gzip archive. |
| `app/storage/usage.py` | Formatters for the 5h / 7d subscription windows. |
| `app/access/access.py` | Middleware: allowlist (drops non-allowed updates) + per-user language. |
| `app/access/allowlist.py` | JSON-backed access store: levels, expiry, usage caps; owner always allowed; fail-closed. |
| `app/access/permissions.py` | `PermissionGate`: the code-mode Allow/Deny approval gate. |
| `app/access/settings_schema.py` | Settings registry + resolver: each setting's type/default, storage tier, and access model. |
| `app/telegram/handlers.py` | aiogram router: commands, text/photo/document routing, callbacks, the `/` menu. |
| `app/telegram/commands.py` | Source of truth for the command set + localized menu labels; `/help` and `setMyCommands` derive from it. |
| `app/telegram/streamer.py` | Live reply: draft streaming in DM, code/table rendering, usage footer. |
| `app/telegram/markup.py` | Telegram formatting: Markdown→HTML, 4096-safe splitting, long-output-as-file. |
| `app/telegram/rich_message.py` | Binding for Bot API 10.1 `sendRichMessage` — native tables. |
| `app/telegram/svg_image.py` | Rasterizes a chat reply's inline `<svg>` diagram to PNG (#295). |
| `app/telegram/table_image.py` | Dormant PNG-table fallback (#162), kept for wide tables. |
| `deploy/` | Out-of-process helpers: `tg-bot.service` (systemd unit), `sandbox-claude.sh` (bubblewrap launcher), the egress / broker / seccomp scripts. |
| `docs/` | Design docs: `data-model.md`, `isolation.md`, `menu.md`, `markup.md`, `rich-message-spec.md`, `CONTRIBUTING.md`, `SECURITY.md`. |

Tasks are tracked in [`TODO.md`](TODO.md); contributor rules in [`AGENTS.md`](AGENTS.md)
and [`CONTRIBUTING.md`](docs/CONTRIBUTING.md).

---

## Data & directory layout

All state lives on the host; there is no external service. The runtime owner of every
file is the service user (whoever ran `claude setup-token` and the systemd unit).

```
<repo>/                          ← the checkout (service user owns it)
├── app/                         ← application package (run via `python -m app`; see Project structure)
├── deploy/                      ← systemd unit + sandbox / egress / broker helpers
├── docs/                        ← design docs (data-model, isolation, menu, markup, rich-message-spec)
├── tests/   conftest.py         ← pytest suite (+ the root sys.path shim)
├── .env                         ← config + secrets: TELEGRAM_BOT_TOKEN, OWNER_ID,
│                                  DEFAULT_MODEL, BASE_WORKDIR, DB_PATH, ALLOWLIST_PATH,
│                                  optional SANDBOX_*/concurrency caps        [gitignored]
├── allowlist.json               ← access store: per-user level/expiry/caps    [gitignored]
├── bot.db (+ -wal, -shm)        ← SQLite state (see tables below)             [gitignored]
└── bot.log                      ← run log                                     [gitignored]

/var/lib/claude-tg-bot/workdirs/  (= BASE_WORKDIR — outside /root so a per-session jail uid can reach it)
├── <sid>/                       ← one directory per session, named by the public sid (#181); 0711
│   ├── work/                    ←  the agent's cwd (owned by the session's host uid, 0700), bound into the jail
│   ├── state/                   ←  the jail HOME → ~/.claude/projects: the transcript. NOT bound into the jail.
│   └── secrets.env              ←  optional per-session user creds (#119d), 0600, injected into THIS jail only
└── _archive/<owner_id>/<sid>-<stamp>.tar.gz   ← cold storage on delete (#177); purged after retention (#178)
```

`<sid>` is the public session id shown in `/sessions`, never the internal numeric id.
Isolation is structural: each session sees only its own `work/`, and with
`SANDBOX_PER_SESSION_UID` on, `work/` is owned by a distinct non-root uid, so even a
jail escape cannot read another session's files. The subscription credential is injected
read-only in the bare jail, or — with the broker (#119b) — kept out of the jail entirely
(a `BROKER-PLACEHOLDER` dummy is injected and a host broker supplies the real token). See
[Security & isolation](#security--isolation) and [`isolation.md`](docs/isolation.md).

SQLite tables in `bot.db` (additive-migration only; full schema in
[`data-model.md`](docs/data-model.md)):

| Table | One row per | Holds |
|---|---|---|
| `threads` | session | mode, model, cwd, resumable chat/code session ids, and every per-session toggle (effort, permission mode, max-turns, favorite, enabled tools, …) |
| `usage` | turn | `input/output_tokens`, `cache_read/creation`, `cost_usd`, plus `model` + `context_tokens` for the weighted usage-units metric (#165); rolls up per user by `chat_id` |
| `messages` | message | conversation log feeding `/last`, `/recap`, `/history` |
| `kv` | key | small state: current-session pointer, usage display mode, language, pinned-message id, access overrides, user defaults |
| `rate_history` | snapshot | subscription rate-limit samples for the `/status` trend |

The subscription credential lives outside the repo, in the service user's
`~/.claude/.credentials.json` (written by `claude setup-token`, refreshed by
`token_refresh.py`, #191). It is never stored in `bot.db` or copied into a session
directory; with the broker (#119b) on, it never enters a jail.

---

## Requirements & dependencies

- A Linux server you control, Python 3.11+, and a Telegram account.
- The Claude Code CLI (`claude`), logged in to a Pro/Max subscription
  (`claude setup-token`).
- Python packages (`pip install -r requirements.txt`):

  | Package | Purpose |
  |---|---|
  | `aiogram==3.28.2` | Telegram Bot API framework (async, long polling). |
  | `claude-agent-sdk==0.2.101` | Drives the `claude` CLI on the subscription. |
  | `aiosqlite==0.22.1` | Async SQLite for per-session state and usage. |
  | `python-dotenv==1.2.2` | Loads `.env`. |
  | `Pillow==12.2.0` | Renders the PNG-table fallback (`table_image.py`); needs the DejaVu Sans Mono font. |
  | `cairosvg==2.9.0` | Rasterizes a chat reply's inline `<svg>` diagram to PNG (`svg_image.py`); needs the system library `libcairo2` (`apt install libcairo2`). |

- Optional: `bubblewrap` for the code sandbox; `pytest` + `ruff`
  (`requirements-dev.txt`) for development. `cairosvg` needs the system `libcairo2`
  library (`apt install libcairo2`); without it the SVG-diagram feature falls back to
  sending the raw `.svg` file.
- Optional (for the #119 egress allowlist, `SANDBOX_EGRESS`): `iptables` (the
  `iptables-nft` backend works) + the `xt_cgroup` kernel module + cgroup v2. No
  `nftables` and no extra Python packages. See [`isolation.md`](docs/isolation.md).

### Resource requirements & concurrency limits

Each active session holds a live `claude` subprocess (~400–600 MB RSS) — the dominant
memory cost (the bot itself is ~130 MB; `opus` with a 1M context sits at the high end).
The bot self-limits based on RAM/CPU and reaps idle sessions: the subprocess is closed,
but the transcript stays on disk and `resume` rebuilds it on the next message, so no
history is lost. Rough capacity on Debian 12/13 (defaults auto-derived at startup):

| RAM | Concurrent active turns | Live clients held | Notes |
|---|---|---|---|
| 2 GB | 2 | 2 | tight — add 2–4 GB swap; prefer `sonnet`/`haiku` |
| 4 GB | 4 | ~5 | comfortable for a small group |
| 6 GB | 6 | ~7 | |
| 8 GB | 8 | ~11 | |

Defaults ≈ `live = (RAM_MB − 900) / 550`, `turns = min(live, 2×CPU)`. Idle clients are
reaped after ~6 minutes (and under memory pressure), so you can serve many more users
than the "live clients" column — only simultaneously-active turns cost RAM. Configure
swap as an OOM backstop: with no swap, exhausting RAM is a hard kill.

Tunables (`.env`, all optional — defaults derived from the box):

| Var | Default | Meaning |
|---|---|---|
| `MAX_LIVE_CLIENTS` | from RAM | Max simultaneously-live `claude` subprocesses (idle+busy). |
| `MAX_CONCURRENT_TURNS` | from RAM/CPU | Max turns generating at once; overflow turns queue. |
| `IDLE_TTL_SEC` | `360` | Reap a session's subprocess after this many seconds idle (~6 min, the warm-cache window). |
| `SHELL_TTL_SEC` | `86400` | A persistent shell (`/shell`) outlives the subprocess reap (~3 MB vs ~500 MB), kept this long (~24h). `0` = until delete. |
| `MIN_FREE_MB` | `400` | Below this much free RAM, evict idle sessions before starting a turn. |
| `CRED_BROKER` | `0` | Keep the subscription token out of every jail — a host broker injects it (#119b). |
| `SANDBOX_EGRESS` | `0` | Hard-block jail egress to loopback only; dev hosts via the CONNECT proxy (#119c). |
| `EGRESS_ALLOW_HOSTS` | _(empty)_ | Extra CONNECT-allowlisted hosts, comma/space separated. |
| `SANDBOX_MEM_MB` / `SANDBOX_CPU_PERCENT` / `SANDBOX_PIDS_MAX` | `0` | Per-jail cgroup limits (0 = unlimited) (#119e). |
| `SANDBOX_SECCOMP` | `0` | Load an x86_64 seccomp denylist into the jail (#119e). |
| `SANDBOX_PER_SESSION_UID` | `0` | Run each jail as a distinct non-root host uid; needs `BASE_WORKDIR` outside `/root`. |
| `SANDBOX_UID_BASE` / `SANDBOX_UID_RANGE` | `700000` / `60000` | Host-uid range for per-session uids. |
| `MAX_SESSIONS_PER_USER` | `500` | Default cap on sessions per user (owner-overridable in Settings → Admin and per user; 0 = unlimited). |

---

## Setup

### 1. Telegram

1. In [@BotFather](https://t.me/BotFather) send `/newbot`, pick a name and a `…bot`
   username; copy the token → `.env` as `TELEGRAM_BOT_TOKEN`.
2. Get your numeric id from [@userinfobot](https://t.me/userinfobot) → `.env` as
   `OWNER_ID` (or send the running bot `/whoami`).
3. Open a DM with the bot and send `/start`. (Telegram Premium is not required.)

### 2. Server

Install and log in the Claude Code CLI (subscription auth):

```bash
claude setup-token     # stores Pro/Max subscription credentials (headless-friendly)
claude --version       # should print a version
```

Do not set `ANTHROPIC_API_KEY` — it switches Claude Code to paid API billing. The bot
strips it from the environment it hands to Claude and warns at startup, but keep it
unset.

Install:

```bash
git clone git@github.com:haritos90/claude-tg-bot.git
cd claude-tg-bot
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

Configure:

```bash
cp .env.example .env                       # fill TELEGRAM_BOT_TOKEN + OWNER_ID
cp allowlist.example.json allowlist.json   # add any users besides yourself
```

`.env` requires `TELEGRAM_BOT_TOKEN` and `OWNER_ID`; the rest (`DEFAULT_MODEL`,
`BASE_WORKDIR`, `DB_PATH`, `ALLOWLIST_PATH`, the sandbox flags, and the concurrency
caps) have defaults.

Run:

```bash
. .venv/bin/activate
python -m app
```

Open a DM, `/start`, create a session with `/new`, and say hello; upgrade it with
`/code` when you need a terminal or files. `/help` lists every command.

---

## Access control

The bot answers only the owner (`OWNER_ID`) and users on the allowlist; every other
update is dropped before any handler runs (fail-closed — a missing or corrupt
`allowlist.json` means owner-only, never everyone).

Each user has a level (`chat` = chat only, or `code` = chat + code), an optional expiry,
and optional rolling usage caps (a trailing-5h and a trailing-7d cap). Caps count
weighted usage units — a cost-aware metric (model weight + output + cache) that mirrors
how the shared subscription windows fill, rather than raw input+output tokens (#165).
Manage from Telegram (owner only): `/allow <id|@user>`, `/deny`, `/level`, `/expire`,
`/limit`, `/users`.

Numeric ids are authoritative; a `@username` grant is pinned to its numeric id on the
user's first message. `allowlist.json` is gitignored — see
[`allowlist.example.json`](allowlist.example.json) for the format.

Usage appears in two metrics: raw tokens (input+output) and weighted units (the cap
basis). `/userstats` shows both side by side; the `/users` list and per-user card show
units.

---

## Commands

The full set lives in the tap-to-open Telegram menu (descriptions localized; code-only
commands are hidden from chat-level users, owner commands from everyone else). Plain
text goes to the current session's Claude.

Commands are registered most-used first; `/new`, `/sessions`, `/settings` sit at the
top. Fixed-choice commands open an inline picker; commands needing free text prompt for
your next message (with `/cancel`). `/help` is generated from the same registry. The
full menu structure is in [menu.md](docs/menu.md).

| Group | Commands |
|---|---|
| Sessions | `/new` `/code` (upgrade) `/chat` (downgrade) `/sessions` `/rename` `/fork` `/clear` (alias `/reset`) |
| Run | `/status` `/retry` `/context` `/limits` (your usage) `/queue` `/clearqueue` |
| Tuning | `/model` `/effort` `/memory` `/language` · *(code)* `/permissions` `/files` `/export` `/maxturns` `/tools` `/shell` `/secret` |
| Recap & export | `/recap` (AI one-line recap) `/last` (verbatim last exchange) `/history` (transcript) |
| Meta | `/settings` `/usage` `/help` `/whoami` |
| Owner | `/users` `/userstats` (usage table) `/allow` `/deny` `/level` `/expire` `/limit` `/auto` `/codesplit` |

---

## Security & isolation

- Access is owner + allowlist, fail-closed; the bot token and `allowlist.json` are
  gitignored and never logged. Subscription only — no API key.
- Every session runs in a sandbox (#180/#231). Each session's `claude` — chat and code
  — runs in a [bubblewrap](https://github.com/containers/bubblewrap) jail: an
  unprivileged uid (not host root), filesystem confined to the session's own workdir,
  read-only root, the bot's env wiped, and the credential injected read-only. The
  sandbox is mandatory, with no per-session toggle. Risky code tools (Bash/Write/Edit)
  are still gated behind an Allow/Deny tap (or `/auto on`).
- Full isolation is opt-in, off by default. The bare jail confines the filesystem; the
  flags below turn it into containment for a semi-trusted code user. Until you enable
  them (at least the broker + egress), grant `code` only to people you trust. All
  OS/network mechanism lives in [`deploy/`](deploy/), gated behind these flags (#119).
  - Credential broker (`CRED_BROKER=1`, #119b): keeps the OAuth token out of every jail.
    The jailed `claude` gets a dummy `BROKER-PLACEHOLDER` plus `ANTHROPIC_BASE_URL`
    pointing at a host broker ([`deploy/cred-broker.py`](deploy/cred-broker.py)) that
    injects the real bearer and forwards to `api.anthropic.com`. OAuth only.
  - Egress allowlist (`SANDBOX_EGRESS=1`, #119c — code sessions): a code jail's egress
    is hard-blocked to loopback only by a cgroup-scoped iptables rule (never global).
    `claude` reaches Anthropic via the broker; the agent's tools reach an allowlisted set
    of dev hosts (Anthropic + GitHub/PyPI/npm by default, extend with
    `EGRESS_ALLOW_HOSTS`) via a CONNECT proxy
    ([`deploy/egress-proxy.py`](deploy/egress-proxy.py)). Chat sessions keep open egress
    (no Bash to exfil with; the web tools need arbitrary URLs).
  - Per-session secrets (`/secret`, #119d): a code user stores their own service creds
    for the current session, injected as env vars into that jail only. The owner's
    credentials never enter any jail.
  - DoS limits + seccomp (#119e): per-jail memory/CPU/process caps and an optional
    x86_64 syscall denylist (`SANDBOX_SECCOMP=1`).
  - Per-session host uid (`SANDBOX_PER_SESSION_UID=1`): each jail runs as a distinct
    non-root uid (via `setpriv` + a user namespace), with its workdir chowned to it. An
    escape lands as an unprivileged user and still cannot read another session's files.
    Requires `BASE_WORKDIR` outside `/root` (defaults to `/var/lib/claude-tg-bot/workdirs`).
- Hidden CLI keyword triggers are neutralized. The bundled CLI acts on prompt keywords
  like `ultrathink` (escalates effort) and `ultracode` (multi-agent orchestration),
  either of which could burn the shared subscription or bypass the effort gate. The bot
  disables workflows (`CLAUDE_CODE_DISABLE_WORKFLOWS=1`) and defuses the keywords; extend
  the list with `BLOCKED_PROMPT_KEYWORDS`. Reasoning depth is controlled only via
  `/effort`.

Deleting a session bundles its `<sid>/` folder (files + transcript) into one gzip
archive and removes the live copies (#177); archives older than the retention period are
auto-purged (#178; default 6 months, owner-configurable under Settings → Admin → Archive
retention or `ARCHIVE_RETENTION_DAYS`).

Report vulnerabilities privately — see [`SECURITY.md`](docs/SECURITY.md).

---

## Data, privacy & trust

Everything happens on your server; there is no external database.

- What's stored: per-session state, conversation transcripts (used by `/last` and
  `/history`), and token usage live in `bot.db` (tables above). Code sessions also keep
  files under `BASE_WORKDIR/<session>` and Claude's resume state under the service user's
  `~/.claude/projects`.
- The server operator can read all of it. Whoever runs the bot can open `bot.db` and the
  workdirs — every user's conversations and files. Anyone you share access with is
  trusting you, the operator; share accordingly and keep the host secured. (`bot.db`,
  `workdirs/`, and `*.log` are gitignored, so they are never committed.)
- Separate from claude.ai. These run as local Claude Code / Agent-SDK sessions, so they
  do not appear in claude.ai chat history. The requests still go through Anthropic on the
  subscription (counting against its limits, subject to Anthropic's terms).

---

## Run it 24/7 with systemd

[`deploy/tg-bot.service`](deploy/tg-bot.service) supervises the bot across crashes,
reboots, and Telegram outages.

Quick install: `sudo deploy/install-systemd.sh` adapts the unit to your checkout
path/user, stops any manual copy, and enables + starts the service (add `--with-timer`
for the daily restart). By hand — edit the paths/`User`, then:

```bash
sudo cp deploy/tg-bot.service /etc/systemd/system/claude-tg-bot.service
sudo systemctl daemon-reload
sudo systemctl stop claude-tg-bot    # stop any running copy first (avoid a 409)
sudo systemctl enable --now claude-tg-bot
journalctl -u claude-tg-bot -f
```

Resilience:

- `Restart=always` + `StartLimitIntervalSec=0`: respawns on any crash/exit and on boot,
  and never gives up (a long Telegram outage keeps retrying).
- Connection watchdog (`Type=notify` + `WatchdogSec=180`, [`watchdog.py`](watchdog.py)):
  the bot pings systemd only after a successful Telegram probe, so ~3 minutes without
  reaching Telegram triggers a force-restart.
- OAuth token refresh ([`token_refresh.py`](token_refresh.py)): the subscription access
  token has a ~8h life; a background loop renews it via the `refresh_token` grant and
  rewrites `~/.claude/.credentials.json` before it expires (subscription only, never an
  API key). Tunable via `OAUTH_REFRESH`, `OAUTH_REFRESH_INTERVAL_SEC` (1800),
  `OAUTH_REFRESH_SKEW_SEC` (3600).
- Optional daily restart: [`deploy/claude-tg-bot-restart.{service,timer}`](deploy/) —
  `sudo systemctl enable --now claude-tg-bot-restart.timer`.

Restart after a code change with `sudo systemctl restart claude-tg-bot` (never a second
manual `python -m app` — two pollers per token gives a 409). Run the service as the same
user that ran `claude setup-token`.

---

## Saving subscription limits

Watch `/usage` and `/status`: chain follow-ups within the 5-minute prompt cache, keep one
project per session, and right-size the model with `/model`. The owner's local notes live
in a gitignored `CLAUDE.md`; shared conventions in `AGENTS.md`.

---

## Known issues

Long answers can look like they retype on Telegram Desktop for macOS. Live replies stream
as a native message draft, which Telegram caps at ~4096 characters. Past that cap the
draft tracks the model's frontier, and Telegram Desktop for macOS re-renders the whole
draft on each jump, so a long answer can appear to rewrite itself while streaming. On iOS
the same stream animates smoothly. The final posted message is always complete and correct
on every client.

---

## Legal

For personal, development, and research use. You are solely responsible for how you use
it and must comply with applicable laws and with the Anthropic and Telegram terms of
service. MIT licensed — see [`LICENSE`](LICENSE).
