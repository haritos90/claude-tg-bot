# Telegram bot for Claude via Claude Agent SDK

A **private, multi-user** Telegram bot that is your personal frontend to **Claude**
and **Claude Code** — use it yourself and share access with other Telegram users,
each talking to the bot in a **DM**. You keep named **sessions** and switch between
them; each is fully isolated (histories never cross) and is **either chat or code,
fixed at creation**:

- **chat** — a plain Claude conversation.
- **code** — a full Claude Code agent with its own working directory on the
  server; it runs shell commands and edits files (dangerous tools wait for an
  **Allow** / **Deny** tap, or run freely with `/auto on`).

Everything runs on your **Claude Pro/Max subscription** via the
[Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk/overview) — **no
Anthropic API key, no per-token billing.**

[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)

---

## Features

- **Streaming:** uses native Telegram streaming tailored for generative AI tools
  (Telegram only supports it for DMs now).
- **Isolated sessions** — each is its own Claude session (context, working dir,
  resume id), chat **or** code, fixed at creation; nothing leaks between them
  (see **One subscription, isolated memory** below). Browse / switch / rename /
  ⭐ / delete via `/sessions`.
- **Allowlist access** — only the owner and explicitly allowed users can talk to
  the bot; each allowed user has a **level** (chat or code), an optional
  **expiry**, and an optional **token cap**. The list lives in a gitignored
  `allowlist.json`.
- **Approvals & auto mode** — in code mode Bash/Write/Edit pause for an inline
  **Allow / Deny** tap; `/auto on` (owner) runs everything without asking.
  `/permissions` switches ask / auto-edits / plan / full-access.
- **Ambient usage** — `/usage` and `/status` show your subscription's **5h** and
  **7d** windows as "% left", as a footer or a pinned live message.
- **Task chaining** — send a follow-up during or right after a run; it queues into
  the *same* session, reusing context and the warm cache.
- **Localized UI** — English and Russian, auto-detected from your Telegram client
  and changeable with `/language` (Claude's own answers are unaffected).
- **Durable state** — sessions, usage, settings, and language live in SQLite and
  survive a restart.

---

## How it works

```
You ──DM──▸ @your_bot
             └── /newchat | /newcode ──▸ one isolated session   (switch with /sessions)
                   ├── chat: Agent SDK, no tools
                   └── code: Agent SDK + tools, cwd = BASE_WORKDIR/<session>
                                └── dangerous tool? ──▸ inline Allow / Deny
```

Long polling — no webhook, domain, or public port.

### One subscription, isolated memory

Every session — yours and other users' — runs on the **same** Pro/Max subscription
(a Telegram identity is **not** a separate Claude account), so they all draw from
**one shared usage-limit pool**. But there is **no global or cross-session
memory**: the bot sets `setting_sources=[]`, so no account- or machine-wide
`CLAUDE.md` / settings ever load, and each session keeps only its **own**
conversation (its own resume id, persisted across restarts). That isolation is
exactly what lets one subscription safely serve many independent sessions and
users. (The shared limit pool is also why per-user **token caps** exist — see
**Access control**.)

---

## Project structure

| File | Responsibility |
|---|---|
| `bot.py` | Entry point: wiring, middleware, long polling, graceful shutdown. |
| `config.py` | `.env` → `Settings` (warns if `ANTHROPIC_API_KEY` is set). |
| `handlers.py` | aiogram router: commands, text/photo/document routing, callbacks, the `/` menu. |
| `engine.py` | `ClaudeSession` over the Agent SDK — **all** SDK code lives here (incl. the sandbox launcher). |
| `sessions.py` | `SessionManager`: per-session worker, the chaining queue, `/stop`, usage accounting. |
| `streamer.py` | Live reply: native `sendMessageDraft` streaming in DM, code-block rendering, usage footer. |
| `permissions.py` | `PermissionGate`: the code-mode Allow/Deny approval gate. |
| `access.py` | Middleware: allowlist (drops non-allowed updates) + per-user language resolution. |
| `allowlist.py` | JSON-backed access store: levels, expiry, token caps; owner always allowed; fail-closed. |
| `db.py` | `aiosqlite` state: sessions, usage, conversation log, key-value store. |
| `i18n.py` | Localization table + `t(key, lang, …)`; `en` canonical, `ru` translation. |
| `markup.py` | Telegram formatting: Markdown→HTML, 4096-safe splitting, long-output-as-file. |
| `usage.py` | Formatters for the 5h / 7d subscription windows. |
| `deploy/` | `tg-bot.service` (systemd unit) and `sandbox-claude.sh` (bubblewrap launcher). |

Tasks are tracked in [`TODO.md`](TODO.md); contributor rules in
[`AGENTS.md`](AGENTS.md) and [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## Requirements & dependencies

- A **Linux server (VPS)** you control, **Python 3.11+**, and a **Telegram account**.
- The **Claude Code CLI** (`claude`), logged in to your Pro/Max subscription
  (`claude setup-token`).
- Python packages — installed by `pip install -r requirements.txt`:

  | Package | Purpose |
  |---|---|
  | `aiogram==3.28.2` | Telegram Bot API framework (async, long polling). |
  | `claude-agent-sdk==0.2.101` | Drives the `claude` CLI on your subscription. |
  | `aiosqlite==0.22.1` | Async SQLite for per-session state and usage. |
  | `python-dotenv==1.2.2` | Loads `.env`. |

- Optional: the **`bubblewrap`** package (e.g. `apt install bubblewrap`) for the
  code sandbox; **`pytest`** + **`ruff`** (`requirements-dev.txt`) for development.

---

## 1. Telegram setup

1. In **[@BotFather](https://t.me/BotFather)** send `/newbot`, pick a name and a
   `…bot` username; copy the **token** → `.env` as `TELEGRAM_BOT_TOKEN`.
2. Get your numeric id from **[@userinfobot](https://t.me/userinfobot)** → `.env`
   as `OWNER_ID` (or send the running bot `/whoami`).
3. Open a **DM** with your bot and send `/start`.

(Telegram Premium is not required.)

## 2. Server setup

**Install & log in the Claude Code CLI (subscription auth):**

```bash
claude setup-token     # stores Pro/Max subscription credentials (headless-friendly)
claude --version       # should print a version
```

> **Do not set `ANTHROPIC_API_KEY`** — it would switch Claude Code to paid API
> billing. The bot strips it from the environment it hands to Claude and warns at
> startup, but keep it unset.

**Install the bot:**

```bash
git clone git@github.com:haritos90/claude-tg-bot.git
cd claude-tg-bot
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

**Configure:**

```bash
cp .env.example .env                       # fill TELEGRAM_BOT_TOKEN + OWNER_ID
cp allowlist.example.json allowlist.json   # add any users besides yourself
```

`.env` has two required keys (`TELEGRAM_BOT_TOKEN`, `OWNER_ID`); the rest
(`DEFAULT_MODEL`, `BASE_WORKDIR`, `DB_PATH`, `ALLOWLIST_PATH`, and the optional
sandbox flags `SANDBOX_CODE` / `SANDBOX_UID` — see **Security & isolation**) have
sensible defaults.

**Run:**

```bash
. .venv/bin/activate
python bot.py
```

Open a DM, `/start`, create a session with `/newchat` or `/newcode`, and say
hello. `/help` lists every command.

---

## Access control

The bot answers only the **owner** (`OWNER_ID`) and users on the **allowlist**;
every other update is dropped before any handler runs (fail-closed — a
missing/corrupt `allowlist.json` means owner-only, never everyone).

Each allowed user has a **level** (`chat` = chat mode only, or `code` = chat +
code), an optional **expiry** date, and an optional **token cap** (a cumulative
budget across their sessions). Manage it from Telegram (owner only): `/allow
<id|@user>`, `/deny`, `/level`, `/expire`, `/limit`, `/users`.

Numeric ids are authoritative; a `@username` grant is **pinned to its numeric id**
on the user's first message (usernames can be hijacked if freed). `allowlist.json`
is gitignored — see [`allowlist.example.json`](allowlist.example.json) for the
format.

---

## Commands

The full set lives in the tap-to-open Telegram menu (descriptions localized;
code-only commands are hidden from chat-level users, owner commands from everyone
else). Plain text goes straight to the current session's Claude.

| Group | Commands |
|---|---|
| **Sessions** | `/newchat` `/newcode` `/sessions` `/rename` |
| **Run** | `/status` `/stop` `/retry` `/reset` |
| **Tuning** | `/model` `/effort` `/fork` `/memory` · *(code)* `/permissions` `/files` `/export` `/maxturns` |
| **Info** | `/recap` `/history` `/usage` `/context` `/queue` `/clearqueue` |
| **Meta** | `/settings` `/language` `/help` `/whoami` |
| **Owner** | `/auto` `/allow` `/deny` `/users` `/level` `/expire` `/limit` `/sandbox` |

---

## Security & isolation

- **Access** is owner + allowlist, fail-closed; the bot token and `allowlist.json`
  are gitignored and never logged. **Subscription only** — no API key, no
  per-token billing.
- **Code mode is effectively a shell on your server.** It runs as the bot's user,
  with dangerous tools (Bash/Write/Edit) gated behind an explicit Allow/Deny tap
  (or `/auto on`).
- **Isolation is still in progress — grant `code` level only to people you fully
  trust.** Without the optional sandbox, a code-level user is as powerful as the
  bot's user: they can read any file that user can (including secrets) and use the
  network.
- **Optional sandbox** (`SANDBOX_CODE=1`, **off by default, in development**)
  wraps each code session's `claude` in a
  [bubblewrap](https://github.com/containers/bubblewrap) jail — unprivileged uid,
  filesystem confined to the session workdir, env wiped (requires the
  `bubblewrap` package). It limits the *filesystem* blast radius, **but is not yet
  a complete jail:** the subscription token is currently injected into the jail
  and the network is open, so a determined user could still read or exfiltrate it.
  The full design — a **credential broker** so the token never enters the jail, a
  **network egress allowlist**, per-session secrets, and DoS limits — is tracked
  as **#119 in [`TODO.md`](TODO.md)** and not yet built. The owner can toggle
  isolation per session with `/sandbox on|off`.

Report vulnerabilities privately — see [`SECURITY.md`](SECURITY.md).

---

## Data, privacy & trust

Everything happens on **your server** — there is no external database.

- **What's stored, and where.** Per-session state, **conversation transcripts**
  (used by `/recap` and `/history`), and token usage live in the SQLite DB
  (`bot.db`). Code sessions also keep their files under `BASE_WORKDIR/<session>`,
  and Claude's own resume state under the bot user's `~/.claude/projects`. All of
  it sits on the host's disk.
- **The server operator can read all of it.** Whoever runs the bot (root / the
  service user) can open `bot.db` and the workdirs — i.e. **every user's
  conversations and files**. So anyone you share access with is trusting **you, the
  operator**, with their session content; share accordingly and keep the host
  secured. (`bot.db`, `workdirs/`, and `*.log` are gitignored, so they're never
  committed — but they do live on the server.)
- **Separate from claude.ai.** These run as local Claude Code / Agent-SDK sessions,
  so they **do not appear in your claude.ai web/app chat history** — that list only
  shows conversations made in the claude.ai apps. The requests still go through
  Anthropic on your subscription (they count against your limits and are subject to
  Anthropic's terms), they're just not surfaced as claude.ai chats.

---

## Run it 24/7 with systemd

[`deploy/tg-bot.service`](deploy/tg-bot.service) — edit the paths and `User`, then:

```bash
sudo cp deploy/tg-bot.service /etc/systemd/system/claude-tg-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now claude-tg-bot
journalctl -u claude-tg-bot -f
```

> Run the service as the **same user** that ran `claude setup-token`, so it can
> read the subscription credentials from that user's home directory.

---

## Saving subscription limits

Watch `/usage` and `/status`: chain follow-ups within the 5-minute prompt cache,
keep one project per session, and right-size the model with `/model`. The owner's
personal limit-saving notes live in a local, gitignored `CLAUDE.md`; shared
conventions in `AGENTS.md`.

---

## Legal

For personal, development, and research use. You are solely responsible for how
you use it and must comply with applicable laws and with the Anthropic and
Telegram terms of service. MIT licensed — see [`LICENSE`](LICENSE).
