# claude-tg-bot

A **private, multi-user** Telegram bot that is your personal frontend for
**Claude** and **Claude Code** — in a **DM** with the bot.

The bot keeps named **sessions** you switch between, each fully isolated
(histories never cross). A session is **either chat or code, fixed when you
create it**:

- **chat** — a plain Claude conversation.
- **code** — a full Claude Code agent with its own working directory on the
  server. It runs shell commands and edits files; with `/auto on` it works
  without asking, otherwise dangerous tools wait for an **Allow** / **Deny** tap.

Everything runs on your **Claude Pro/Max subscription** through the
[Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk/overview) — **no
Anthropic API key and no per-token billing.**

> **Smooth streaming via native message drafts.** In a DM the reply streams in
> letter-by-letter using Telegram's `sendMessageDraft` (Bot API 9.3+). This only
> works in private chats, so the older **supergroup/Topics** mode (the code is
> still here) is **frozen** — DM is the live mode. Telegram Premium is not
> required.

[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)

---

## Features

- **Sessions:** each session is one isolated Claude session (own context, working
  directory, resume id) — chat **or** code, fixed at creation. Nothing leaks
  between sessions, and no global `~/.claude` / `CLAUDE.md` is loaded
  (`setting_sources=[]`). Browse / switch / rename / delete via `/sessions`.
- **Access control by allowlist:** only the owner plus explicitly allowed users
  can talk to the bot. The user list lives in a **gitignored** `allowlist.json`,
  so your identities never reach a public repo.
- **Native letter-by-letter streaming:** the reply streams in smoothly via
  Telegram message drafts (`sendMessageDraft`). Code is rendered in **copyable**
  Telegram code blocks. In code mode each burst of output between tools is its own
  message (so progress is visible); intermediate messages are silent and links
  never expand into previews.
- **Approvals & auto mode:** in code mode, Bash/Write/Edit pause for an inline
  **Allow / Deny** tap — or run `/auto on` (owner) to execute everything without
  asking, like a local Claude Code session. `/permissions` switches between
  ask / auto-edits / plan / yolo.
- **Ambient usage:** `/usage` shows your subscription's **5h** and **7d** windows
  as "% left" — either as a thin footer under replies or a pinned, live-updated
  message.
- **Task chaining:** send a follow-up while a run is going (or right after) — it
  queues and runs in the *same* session, reusing context and the warm cache.
- **Localized interface:** the bot's UI is available in English and Russian. The
  language is auto-detected from your Telegram client on first contact and can be
  changed any time with `/language` or the ⚙️ settings menu. (Claude's own answers
  are unaffected — the model already replies in your language.)
- State is in SQLite, so sessions, usage, settings, and your language survive a
  bot restart.

---

## How it works

```
You  ──DM──▸  @your_bot
               └── /new  ──▸  one isolated session   (switch with /sessions)
                               ├── chat: Agent SDK, no tools
                               └── code: Agent SDK + tools, cwd = BASE_WORKDIR/<session>
                                           └── dangerous tool? ──▸ inline Allow/Deny
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

You only need a bot token and your numeric id — **no group, Topics, or admin
rights**. You talk to the bot in a private chat (DM).

### 1. Create the bot and get its token

1. Open a chat with **[@BotFather](https://t.me/BotFather)**.
2. Send `/newbot`. Choose a display name, then a username ending in `bot`.
3. BotFather replies with a **token** like `123456789:AAE...`. Keep it secret —
   it goes into `.env` as `TELEGRAM_BOT_TOKEN`.

### 2. Find your numeric Telegram id (`OWNER_ID`)

1. Message **[@userinfobot](https://t.me/userinfobot)** — it replies with your
   **Id** (a number). That's `OWNER_ID`.
2. (You can also send the running bot `/whoami` once it's up.)

### 3. Say hello

Open a **private chat** with your bot and send `/start`. Create sessions with
`/newchat` or `/newcode` (or `/new` to pick), and switch between them with
`/sessions`. No group, Topics, or admin setup is involved.

### Do I need Telegram Premium?

**No.** Creating bots and using inline buttons are free. Premium only adds
unrelated perks this bot doesn't use.

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
BASE_WORKDIR=./workdirs               # code-mode working dirs, one per session
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

Open a DM with your bot and send `/start`; create a session with `/newchat` or
`/newcode` and say hello. `/help` lists every command.

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
| `/new`, `/newchat`, `/newcode` | Create a new isolated session (chat or code). `/new` shows a chooser. |
| `/sessions` | Browse / search / switch / ⭐-favorite / delete your sessions. |
| `/rename <name>` | Rename the current session. |
| `/mode` | Show this session's engine (chat or code — **fixed at creation**). |
| `/model <id>` | Model for this session (`opus` / `sonnet` / `haiku` or a full id). |
| `/cwd <path>` | (code) Working directory; relative paths resolve under `BASE_WORKDIR`. |
| `/permissions ask\|auto-edits\|plan\|yolo` | Code-mode approval policy. `ask` = inline Allow/Deny (default). |
| `/auto on\|off` | (owner) Run code-mode tools without asking, like a local Claude Code session. |
| `/usage off\|footer\|pinned\|both` | (owner) Ambient 5h/7d subscription usage display. |
| `/history`, `/recap` | Export the full transcript / show the last exchange. |
| `/language [ru\|en]` | Choose the bot's interface language (or tap to pick). |
| `/settings` | Inline menu: model, permissions, streaming, memory, language… |
| `/reset` | Clear this session's context (drops context **and** warm cache). |
| `/stop` | Interrupt the run in progress in this session. |
| `/status` | Mode, model, cwd, queue, cache timer, subscription limits, token totals. |
| `/whoami` | Your numeric id + username. |
| `/allow`, `/deny`, `/users` | Owner-only: manage the allowlist. |

Plain text goes straight to the current session's Claude; the reply streams back
into your chat.

---

## Saving subscription limits

Watch `/usage` and `/status`: reuse the 5-minute prompt cache (chain follow-ups
before the timer expires), keep one project per session, and right-size the model
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
  before any handler. **Keep your bot token and `allowlist.json` private.**
- Secrets and identities live only in `.env` and `allowlist.json` (both
  gitignored). They are never committed or logged.
- **Code mode is effectively a shell on your server.** It runs as your service
  user, scoped to a per-session working directory, with dangerous tools gated
  behind an explicit Allow/Deny tap. Treat the approval prompts seriously, and
  use `/permissions yolo` only when you really mean it.

---

## Legal Notice

This software is intended for personal, development, and research use. You are
solely responsible for how you use it and must comply with applicable laws and
with the Anthropic and Telegram terms of service.
