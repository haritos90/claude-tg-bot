# Telegram bot for Claude via Claude Agent SDK

A private, multi-user Telegram bot that fronts Claude Code. You run it on your own
server on a Claude Pro/Max subscription. The subscription owner
uses it and can grant access to other Telegram users; each user talks to the bot in a DM and
keeps named, isolated sessions whose histories never cross.

A session starts as chat and can be upgraded to code and back, in the same conversation:

- chat — a Claude conversation with web tools (search and fetch).
- code — a Claude Code agent with a working directory on the server, it runs shell commands and
  edits files. Permissions are managed with Allow/Deny tap, with auto mode available `/auto on`. `/code`
  upgrades a chat (needs code user priviliges); `/chat` downgrades, keeping the files.

Built on the [Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk/overview).

[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)

> Anyone you grant access to shares your one subscription and trusts the server operator, who
> can read every session's messages and files. See [Security, privacy & trust](#security-privacy--trust).

---

## Features

- _Streaming replies_: each reply renders via native Telegram rich messages and stream live as they
  are written (Bot API 10.1 drafts).
- _Chat and code in one session_: chat has web search and fetch; code adds the full agent toolset
  (Bash, file edits, notebooks) with a working directory on the server.
- _Isolated sessions_: each has its own context and working directory. Browse, switch, rename, favirite, fork,
  and delete via `/sessions`.
- _Voice message input (optional)_: a voice message is transcribed on-device and handled as
  if typed; the recognized text is shown so a mis-hearing is visible. See [voice.md](docs/voice.md).
- _Diagrams and maps_: an inline SVG in a chat reply is captured as PNG and a map pin becomes a
  native map, both embedded in the reply (wide tables too, as images).
- _Always-current models_: the model list, model names and effort levels come from the Claude
  Code CLI itself (`/model`, `/effort`); a family alias such as `opus` always runs that family's
  newest model, and the bot updates the CLI once a day (12:00 UTC by default), moving sessions to
  the new version without cutting a reply. The few deliberate exceptions are listed in
  [configuration.md](docs/configuration.md).
- _Allowlist access_: only the owner and explicitly allowed users can talk to the bot; each user has
  a level (chat or code), an optional expiry, and optional rolling usage caps. See
  [Access control](#access-control).
- _Configuration in Telegram_: `/settings` sets per-session, personal-default, global options,
  per-user access from the Users card.
- _Approvals_: code defaults to auto-edits; only risky actions (push/publish, destructive deletes,
  web fetches) pause for a tap. `/permissions` switches modes; `/auto on` runs everything.
- _Follow-ups while it works_: a message sent during a reply goes into that run, as in the Claude
  Code CLI — folded in at the next tool call, or answered right after as its own reply.
- _Usage display_: `/usage` and `/status` show the subscription's 5h and 7d windows as "% left".
- _Localized UI_: English and Russian, auto-detected and changeable with `/language` (Claude's own
  answers are unaffected).
- _MAX messenger (optional)_: the same bot, commands and sessions model on [MAX](https://max.ru),
  with replies delivered whole once ready and a "Thinking…" message meanwhile. MAX users are a
  separate population — their sessions, access and usage never overlap with Telegram's, and all
  administration (owner commands, access requests, tool approvals) stays in Telegram.

---

## How it works

```bash
You ──DM──▸ @your_bot
             └── /new ──▸ a chat session   (switch with /sessions · upgrade with /code)
                   ├── chat: Agent SDK + web research (WebSearch/WebFetch)
                   └── code: Agent SDK + full tools, cwd = BASE_WORKDIR/<session>
                                └── risky tool? ──▸ inline Allow / Deny
```

Every session runs on the same subscription and share one usage-limit pool. There is no
cross-session memory.

Claude replies in Markdown; the bot renders each reply as native rich messages (headings, lists,
tables, math, code) and streams it live, falling back to Markdown→HTML and a `.md` file.

---

## Setup

### Telegram

1. In [@BotFather](https://t.me/BotFather) send `/newbot`, pick a name and a `…bot` username; copy
   the token into `.env` as `TELEGRAM_BOT_TOKEN`.
2. Open a DM with the bot and send `/start`.

### MAX (optional)

1. Create a bot at [business.max.ru](https://business.max.ru/self) and copy its token into `.env`
   as `MAX_BOT_TOKEN`; restart.
2. Open the bot in MAX and send any message. Your Telegram chat with the bot receives the access
   request — tap Allow there (the MAX account is a separate user, even when it is yours).
   The platform's TLS root is bundled; nothing to install. See
   [configuration.md](docs/configuration.md#max-messenger).

### Server

Requirements: a Linux server, Python 3.11+, the Claude Code CLI (`claude`) logged in to
a Pro/Max subscription, and `bubblewrap` (every session runs in a jail). Optional extras are listed
in [configuration.md](docs/configuration.md).

```bash
claude setup-token     # log the CLI in to the subscription (no API key)
claude --version       # prints version

git clone https://github.com/haritos90/claude-tg-bot.git
cd claude-tg-bot
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements/base.txt -r requirements/dev.txt -r requirements/voice.txt

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
rolling usage caps (a trailing 5h and a trailing 7d cap). Usage and caps are counted in tokens
(input + output). Manage from Telegram
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

| Group          | Commands                                                                                                                       |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Sessions       | `/new` `/code` (upgrade) `/chat` (downgrade) `/sessions` `/rename` `/fork` `/clear` (alias `/reset`)                           |
| Run            | `/status` `/retry` `/context` `/limits`                                                                                        |
| Tuning         | `/model` `/effort` `/language` · _(code)_ `/permissions` `/files` `/export` `/maxturns` `/tools` `/shell` `/secret`            |
| Recap & export | `/recap` `/last` `/history`                                                                                                    |
| Meta           | `/settings` `/usage` `/help` `/whoami`                                                                                         |
| Owner          | `/users` `/userstats` `/allow` `/deny` `/level` `/expire` `/limit` `/auto` `/codesplit`                                        |

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
[architecture.md](docs/architecture.md); the contribution guide is [CONTRIBUTING.md](CONTRIBUTING.md),
and [AGENTS.md](AGENTS.md) is the context file for AI coding agents.

| Document                                          | Covers                                                                  |
| ------------------------------------------------- | ----------------------------------------------------------------------- |
| [architecture.md](docs/architecture.md)           | Package layout and the module map                                       |
| [gotchas.md](docs/gotchas.md)                     | Hard-won SDK / Telegram / lifecycle / sandbox invariants, per subsystem |
| [configuration.md](docs/configuration.md)         | Every `.env` setting, concurrency/resource tunables, capacity planning  |
| [data-model.md](docs/data-model.md)               | What is persisted, the on-disk layout, the SQLite schema                |
| [isolation.md](docs/isolation.md)                 | The sandbox and containment stack, and its threat model                 |
| [menu.md](docs/menu.md)                           | Every command, menu, and the settings/access model                      |
| [markup.md](docs/markup.md)                       | The message-formatting and rendering contract                           |
| [rich-message-spec.md](docs/rich-message-spec.md) | The Bot API 10.1 rich-message / draft / table spec                      |
| [voice.md](docs/voice.md)                         | On-device voice-note transcription                                      |
| [troubleshooting.md](docs/troubleshooting.md)     | Operator runbook for production incidents                               |
| [SECURITY.md](docs/SECURITY.md)                   | Vulnerability-reporting policy                                          |

Telegram reference: [Rich message formatting][tg-fmt] · [HTML style][tg-html].

[tg-fmt]: https://core.telegram.org/bots/api#rich-message-formatting-options
[tg-html]: https://core.telegram.org/bots/api#html-style

---

## Legal

For personal, development, and research use. You are solely responsible for how you use it and must
comply with applicable laws and with the Anthropic and Telegram terms of service. MIT licensed — see
[`LICENSE`](LICENSE).
