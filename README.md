# claude-tg-bot

A **private, multi-user** Telegram bot that turns a Telegram supergroup into a
personal frontend for **Claude** and **Claude Code**.

Each forum **Topic** in the group is a fully isolated session — histories never
cross between topics. Two modes per topic:

- **chat** — a plain Claude conversation.
- **code** — a full Claude Code agent with its own working directory on the
  server. It can run shell commands and edit files; anything dangerous waits for
  you to tap **Allow** / **Deny**.

Everything runs on your **Claude Pro/Max subscription** through the
[Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk/overview) — **no
Anthropic API key and no per-token billing.**

> **Telegram Premium is _not_ required.** Bots, BotFather, supergroups, forum
> Topics, admin rights, and inline buttons are all free. (See "Do I need
> Premium?" below.)

[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)

---

## Features

- **Topics-as-sessions:** one forum topic = one isolated Claude session (own
  context, own working directory, own resume id). The **General** topic is its
  own session too. Nothing leaks between topics, and no global `~/.claude` /
  `CLAUDE.md` is loaded into any session (`setting_sources=[]`).
- **Access control by allowlist:** only the owner plus explicitly allowed users
  can talk to the bot. The user list lives in a **gitignored** `allowlist.json`,
  so your identities never reach a public repo.
- **Claude-Code-style streaming:** a live message with an animated spinner, text
  that fills in as it's generated, and per-tool status lines (`🔧 Bash: …`,
  `✏️ Edit …`). Code is rendered in **copyable** Telegram code blocks (tap to
  copy).
- **Approval prompts:** in code mode, Bash/Write/Edit and other risky tools pause
  for an inline **Allow / Deny** tap before they run. `/permissions` switches
  between ask / auto-edits / plan / yolo.
- **Ambient usage:** `/usage` shows your subscription's **5h** and **7d** windows
  as "% left" — either as a thin footer under replies or a pinned, live-updated
  message.
- **Task chaining:** send a follow-up while a run is going (or right after) — it
  queues and runs in the *same* session, reusing context and the warm cache.
- State is in SQLite, so topics, usage, and settings survive a bot restart.

---

## How it works

```
Telegram (your private supergroup, Topics ON)
  └── Topic  ──>  message_thread_id  ──>  one isolated session
                                            ├── chat: Agent SDK, no tools
                                            └── code: Agent SDK + tools, cwd = BASE_WORKDIR/<thread_id>
                                                        └── dangerous tool? -> inline Allow/Deny
```

The bot uses long polling (no webhook, no domain, no public port).

---

## Prerequisites

- A Linux server (VPS) you control.
- **Python 3.11+**.
- The **Claude Code CLI** installed and logged in to your Pro/Max subscription
  (this is how the bot reaches Claude on your subscription).
- A Telegram account.

---

## Part A — Telegram setup (step by step, first-timer friendly)

You'll do all of this inside the Telegram app.

### 1. Create the bot and get its token

1. Open a chat with **[@BotFather](https://t.me/BotFather)**.
2. Send `/newbot`. Choose a display name, then a username ending in `bot`.
3. BotFather replies with a **token** like `123456789:AAE...`. Keep it secret —
   it goes into `.env` as `TELEGRAM_BOT_TOKEN`.

### 2. Let the bot read messages in groups (disable Group Privacy)

By default a bot in a group only sees commands and replies — **not** ordinary
messages. This bot needs to read the plain text you type in each topic, so:

1. In BotFather: `/mybots` → your bot → **Bot Settings** → **Group Privacy** →
   **Turn off** ("Privacy mode is disabled").

### 3. Create the group and enable Topics

1. Create a **new group** and add your bot to it.
2. Group → **Edit** → turn on **Topics**. (Telegram converts the group to a
   *supergroup* automatically — free, and required for Topics.)

### 4. Make the bot an admin

1. Group → **Edit** → **Administrators** → **Add Admin** → your bot.
2. Enable **Manage Topics** (so `/new` can create topics) and **Pin Messages**
   (so the optional `/usage pinned` live counter can pin itself). Leaving the
   other admin rights on is fine for a private group.

### 5. Find your numeric Telegram id (`OWNER_ID`)

1. Message **[@userinfobot](https://t.me/userinfobot)** — it replies with your
   **Id** (a number). That's `OWNER_ID`.
2. (You can also message the running bot `/whoami` once you're the owner.)

### Do I need Telegram Premium?

**No.** Creating bots, supergroups, Topics, admin rights, and inline buttons are
all free. Premium only adds unrelated perks this bot doesn't use.

---

## Part B — Server setup

### 1. Install & log in the Claude Code CLI (subscription auth)

```bash
claude setup-token     # stores Pro/Max subscription credentials (headless-friendly)
claude --version       # should print a version
```

> **Do not set `ANTHROPIC_API_KEY`.** If present, Claude Code would switch to
> paid API billing. The bot strips it from the environment it hands to Claude,
> and warns at startup if it's set — but keep it unset to be safe.

### 2. Install the bot

```bash
git clone git@github.com:haritos90/claude-tg-bot.git
cd claude-tg-bot

python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure `.env` and the allowlist

```bash
cp .env.example .env
cp allowlist.example.json allowlist.json
```

Edit `.env`:

```ini
TELEGRAM_BOT_TOKEN=123456789:AAE...   # from BotFather (step A1)
OWNER_ID=123456789                    # your numeric id (step A5)
DEFAULT_MODEL=claude-opus-4-8         # opus | sonnet | haiku also accepted
BASE_WORKDIR=./workdirs               # code-mode working dirs, one per topic
DB_PATH=./bot.db                      # SQLite state
ALLOWLIST_PATH=./allowlist.json       # who may use the bot (gitignored)
# Do NOT add ANTHROPIC_API_KEY — this bot runs on your subscription.
```

`allowlist.json` (gitignored) lists everyone allowed besides the owner — see
**Access control** below.

### 4. Run

```bash
. .venv/bin/activate
python bot.py
```

Open a topic in your group and say hello. `/help` lists every command.

---

## Access control

The bot only answers the **owner** (`OWNER_ID`) and users on the **allowlist**.
Everyone else is dropped before any handler runs.

`allowlist.json` (gitignored, never committed):

```json
{ "ids": [123456789], "usernames": ["someuser"] }
```

- **Numeric ids are authoritative** and never change — prefer them.
- **Usernames** are a convenience and are matched case-insensitively without the
  `@`. They can be hijacked if a username is ever freed, so when a user first
  matches by username the bot **pins their numeric id** into `allowlist.json`
  automatically.
- The owner is always allowed, even if the file is missing or empty (the bot
  **fails closed** — a corrupt/empty file means "owner only", never "everyone").

Manage the list from Telegram (owner only): `/allow <id|@user>`,
`/deny <id|@user>`, `/users`. Get your own id with `/whoami`.

---

## Commands

| Command | What it does |
|---|---|
| `/help`, `/start` | Show the command reference. |
| `/new <name>` | Create a new topic = fresh isolated session. |
| `/mode chat\|code` | Switch this topic's engine. Default: `chat`. |
| `/model <id>` | Model for this topic (`opus` / `sonnet` / `haiku` or a full id). |
| `/cwd <path>` | (code) Working directory; relative paths resolve under `BASE_WORKDIR`. |
| `/permissions ask\|auto-edits\|plan\|yolo` | Code-mode approval policy. `ask` = inline Allow/Deny (default). |
| `/usage off\|footer\|pinned\|both` | Ambient 5h/7d subscription usage display. |
| `/reset` | Clear this topic's session (drops context **and** warm cache). |
| `/stop` | Interrupt the run in progress in this topic. |
| `/status` | Mode, model, cwd, queue, cache timer, subscription limits, token totals. |
| `/whoami` | Your numeric id + username. |
| `/allow`, `/deny`, `/users` | Owner-only: manage the allowlist. |

Plain text in a topic goes straight to that topic's Claude session; the reply
streams back into the same topic.

---

## Saving subscription limits

Watch `/usage` and `/status`: reuse the 5-minute prompt cache (chain follow-ups
before the timer expires), keep one project per topic, and right-size the model
with `/model`. The owner keeps personal limit-saving habits in a local,
gitignored `CLAUDE.md`; shared project conventions are in `AGENTS.md`.

---

## Run it 24/7 with systemd

A unit file is in [`deploy/tg-bot.service`](deploy/tg-bot.service). Edit the
paths and `User`, then:

```bash
sudo cp deploy/tg-bot.service /etc/systemd/system/claude-tg-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now claude-tg-bot
journalctl -u claude-tg-bot -f
```

> The service must run as the **same user** that ran `claude setup-token`, so it
> can read the subscription credentials from that user's home directory.

---

## Security

- The only access control is the owner + allowlist; every other update is dropped
  before any handler. **Keep the group private.**
- Secrets and identities live only in `.env` and `allowlist.json` (both
  gitignored). They are never committed or logged.
- **Code mode is effectively a shell on your server.** It runs as your service
  user, scoped to a per-topic working directory, with dangerous tools gated
  behind an explicit Allow/Deny tap. Treat the approval prompts seriously, and
  use `/permissions yolo` only when you really mean it.

---

## Legal Notice

This software is intended for personal, development, and research use. You are
solely responsible for how you use it and must comply with applicable laws and
with the Anthropic and Telegram terms of service.
