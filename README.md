# Telegram bot for Claude via Claude Agent SDK

A private, multi-user Telegram bot that fronts Claude and Claude Code. You run it on your own
server on a Claude Pro/Max subscription — no Anthropic API key, no per-token billing. The owner
uses it and can grant access to other Telegram users; each person talks to the bot in a DM and
keeps named, isolated sessions whose histories never cross.

A session starts as chat and can be upgraded to code and back, in the same conversation:

- chat — a Claude conversation with web tools (search and fetch); no terminal or files.
- code — a Claude Code agent with a working directory on the server; it runs shell commands and
  edits files. Risky tools wait for an Allow/Deny tap, or run freely with `/auto on`. `/code`
  upgrades a chat (needs code access); `/chat` downgrades, keeping the files.

Built on the [Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk/overview).

[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)

> Anyone you grant access to shares your one subscription and trusts you, the server operator, who
> can read every session's messages and files. See [Security, privacy & trust](#security-privacy--trust).

---

## Features

- Streaming replies: each reply renders as one native Telegram rich message and streams live as it
  is written (Bot API 10.1 drafts), DM only.
- Chat and code in one session: chat has web search and fetch; code adds the full agent toolset
  (Bash, file edits, notebooks) with a working directory on the server.
- Isolated sessions: each has its own context, working directory, and resume id; nothing leaks
  between them. Browse, switch, rename, star, fork, and delete via `/sessions`.
- Voice input (optional, off by default): a voice message is transcribed on-device and handled as
  if typed; the recognized text is shown so a mis-hearing is visible. See [voice.md](docs/voice.md).
- Diagrams: an inline SVG in a chat reply is rasterized to PNG and sent as an image (vector
  diagrams, not photos).
- Allowlist access: only the owner and explicitly allowed users can talk to the bot; each user has
  a level (chat or code), an optional expiry, and optional rolling usage caps. See
  [Access control](#access-control).
- Owner control from Telegram: `/settings` sets per-session, personal-default, and global options,
  and per-user access from the Users card — no server login needed.
- Approvals: code defaults to auto-edits; only risky actions (push/publish, destructive deletes,
  web fetches) pause for a tap. `/permissions` switches modes; `/auto on` runs everything.
- Task chaining: a follow-up sent during or after a run queues into the same session, reusing
  context and the warm cache.
- Usage display: `/usage` and `/status` show the subscription's 5h and 7d windows as "% left".
- Localized UI: English and Russian, auto-detected and changeable with `/language` (Claude's own
  answers are unaffected).
- Durable state: sessions, usage, settings, and language live in SQLite and survive a restart.

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

Every session runs on the same subscription (a Telegram identity is not a separate Claude account),
so all sessions share one usage-limit pool — which is why per-user usage caps exist. There is no
cross-session memory: the bot sets `setting_sources=[]`, so no account- or machine-wide `CLAUDE.md`
or settings load, and each session keeps only its own conversation and resume id.

Claude replies in Markdown; the bot renders each reply as one native rich message (headings, lists,
tables, math, code) and streams it live, falling back to Markdown→HTML and then to a `.md` file if
a rich send fails, so a message is never lost. The rendering contract is in
[markup.md](docs/markup.md).

---

## Setup

### Telegram

1. In [@BotFather](https://t.me/BotFather) send `/newbot`, pick a name and a `…bot` username; copy
   the token into `.env` as `TELEGRAM_BOT_TOKEN`.
2. Open a DM with the bot and send `/start`.

### Server

Requirements: a Linux server you control, Python 3.11+, the Claude Code CLI (`claude`) logged in to
a Pro/Max subscription, and `bubblewrap` (every session runs in a jail). Optional extras are listed
in [configuration.md](docs/configuration.md).

```bash
claude setup-token     # log the CLI in to the subscription (no API key)
claude --version       # should print a version

git clone https://github.com/haritos90/claude-tg-bot.git
cd claude-tg-bot
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements/base.txt

cp .env.example .env                       # fill TELEGRAM_BOT_TOKEN + OWNER_ID
cp allowlist.example.json allowlist.json   # add any users besides yourself

python -m app
```

`OWNER_ID` is your numeric Telegram id — message [@userinfobot](https://t.me/userinfobot), or send
the running bot `/whoami`. Only `TELEGRAM_BOT_TOKEN` and `OWNER_ID` are required; every other knob
has a default (see [configuration.md](docs/configuration.md)). Do not set `ANTHROPIC_API_KEY`: it
switches Claude Code to paid billing. The bot strips it from the agent's environment and warns at
startup, but keep it unset.

Open a DM, `/start`, create a session with `/new`, and say hello; upgrade it with `/code` when you
need a terminal or files. `/help` lists every command.

---

## Access control

The bot answers only the owner (`OWNER_ID`) and users on the allowlist; every other update is
dropped before any handler runs. It is fail-closed — a missing or corrupt `allowlist.json` means
owner-only, never everyone.

Each user has a level (`chat`, or `code` for chat plus code), an optional expiry, and optional
rolling usage caps (a trailing 5h and a trailing 7d cap). Caps count weighted usage units, a
cost-aware metric that mirrors how the shared subscription windows fill. Manage from Telegram
(owner only): `/allow`, `/deny`, `/level`, `/expire`, `/limit`, `/users`. Numeric ids are
authoritative; a `@username` grant pins to its id on the user's first message.

Every setting (model, effort, permissions, memory, language, …) also has an owner-set base access —
Delegated, Read-only, or Hidden — with per-user exceptions on the user card. Effective values
resolve per prompt (session → personal default → global). The full model is in
[menu.md](docs/menu.md).

---

## Commands

The full set lives in the tap-to-open Telegram menu; code-only commands are hidden from chat-level
users, owner commands from everyone else. Plain text goes to the current session's Claude.
Fixed-choice commands open an inline picker; commands needing free text prompt for your next
message (with `/cancel`). `/help` is generated from the same registry. The full menu structure is
in [menu.md](docs/menu.md).

| Group | Commands |
|---|---|
| Sessions | `/new` `/code` (upgrade) `/chat` (downgrade) `/sessions` `/rename` `/fork` `/clear` (alias `/reset`) |
| Run | `/status` `/retry` `/context` `/limits` `/queue` `/clearqueue` |
| Tuning | `/model` `/effort` `/memory` `/language` · *(code)* `/permissions` `/files` `/export` `/maxturns` `/tools` `/shell` `/secret` |
| Recap & export | `/recap` `/last` `/history` |
| Meta | `/settings` `/usage` `/help` `/whoami` |
| Owner | `/users` `/userstats` `/allow` `/deny` `/level` `/expire` `/limit` `/auto` `/codesplit` |

---

## Security, privacy & trust

Everything runs on your server; there is no external database. Whoever runs the bot can read all of
it — every user's messages and files in `bot.db` and the working directories. Anyone you grant
access to is trusting you, the operator; share accordingly and keep the host secured. The bot token,
`allowlist.json`, `bot.db`, and the working directories are gitignored and never committed.

- Subscription only — no API key, so no per-token billing.
- Every session's `claude` runs inside a [bubblewrap](https://github.com/containers/bubblewrap) jail:
  an unprivileged uid, the filesystem confined to the session's own workdir, and the bot's environment
  wiped. This is how the bot runs a session, chat and code alike. Risky code tools stay behind the
  Allow/Deny gate.
- Around the jail is a containment stack that is part of the project: a host credential broker keeps
  the subscription token out of every jail, code sessions get a loopback-only egress allowlist, each
  jail runs as a distinct non-root uid, and per-jail seccomp and CPU/memory/pid caps bound what a
  session can consume. Each layer has an `.env` off-switch for a host that can't support it, and the
  bot runs with them on. The mechanism and threat model are in [isolation.md](docs/isolation.md); the
  storage layout is in [data-model.md](docs/data-model.md).
- Hidden CLI keyword triggers (`ultrathink`, `ultracode`) that could burn the shared subscription
  are defused; reasoning depth is controlled only via `/effort`.

These run as local Agent-SDK sessions, so they do not appear in claude.ai history, but the requests
still go through Anthropic on the subscription (counting against its limits, subject to Anthropic's
terms). Deleting a session archives its files and transcript into one gzip and removes the live
copies; archives are auto-purged after the retention period (default 6 months, owner-configurable).

Report vulnerabilities privately — see [SECURITY.md](docs/SECURITY.md).

---

## Running 24/7 with systemd

[`deploy/tg-bot.service`](deploy/tg-bot.service) supervises the bot across crashes, reboots, and
Telegram outages. Install with `sudo deploy/install-systemd.sh` (it adapts the unit to your checkout,
stops any manual copy, and enables and starts the service; add `--with-timer` for a daily restart),
then follow the log with `journalctl -u claude-tg-bot -f`.

It restarts on any crash and on boot and never gives up; a connection watchdog force-restarts after
about three minutes without reaching Telegram; a background loop refreshes the subscription OAuth
token before it expires and warns before the monthly login lapses. Run the service as the same user
that ran `claude setup-token`, and never start a second `python -m app` against the same token (two
pollers give a 409). Tunables and the resilience knobs are in [configuration.md](docs/configuration.md).

---

## Architecture & documentation

The code is one package, `app`, run with `python -m app`: `app/core` (the Agent-SDK engine, session
manager, token refresh, schedules, transcription), `app/storage` (SQLite state, archives, usage),
`app/access` (allowlist, permission gate, settings), and `app/telegram` (handlers, streaming,
formatting). Out-of-process helpers live in `deploy/`. The full module map is in
[architecture.md](docs/architecture.md); contributor rules are in [AGENTS.md](AGENTS.md) and
[CONTRIBUTING.md](CONTRIBUTING.md).

| Document | Covers |
|---|---|
| [architecture.md](docs/architecture.md) | Package layout and the module map |
| [configuration.md](docs/configuration.md) | Every `.env` setting, concurrency/resource tunables, capacity planning |
| [data-model.md](docs/data-model.md) | What is persisted, the on-disk layout, the SQLite schema |
| [isolation.md](docs/isolation.md) | The sandbox and containment stack, and its threat model |
| [menu.md](docs/menu.md) | Every command, menu, and the settings/access model |
| [markup.md](docs/markup.md) | The message-formatting and rendering contract |
| [rich-message-spec.md](docs/rich-message-spec.md) | The Bot API 10.1 rich-message / draft / table spec |
| [voice.md](docs/voice.md) | On-device voice-note transcription |
| [troubleshooting.md](docs/troubleshooting.md) | Operator runbook for production incidents |
| [SECURITY.md](docs/SECURITY.md) | Vulnerability-reporting policy |

Telegram reference: [Rich message formatting][tg-fmt] · [HTML style][tg-html].

[tg-fmt]: https://core.telegram.org/bots/api#rich-message-formatting-options
[tg-html]: https://core.telegram.org/bots/api#html-style

---

## Legal

For personal, development, and research use. You are solely responsible for how you use it and must
comply with applicable laws and with the Anthropic and Telegram terms of service. MIT licensed — see
[`LICENSE`](LICENSE).
