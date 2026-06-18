# Telegram bot for Claude via Claude Agent SDK

A **private, multi-user** Telegram bot that is your personal frontend to **Claude**
and **Claude Code** — use it yourself and share access with other Telegram users,
each talking to the bot in a **DM**. You keep named **sessions** and switch between
them; each is fully isolated (histories never cross). A session is **born a chat and
can be upgraded to code (and back)** — same conversation, more power:

- **chat** — a Claude conversation with **web** tools (search + fetch); no terminal
  or files.
- **code** — a full Claude Code agent with its own working directory on the server;
  it runs shell commands and edits files (dangerous tools wait for an **Allow** /
  **Deny** tap, or run freely with `/auto on`). Upgrade a chat with **`/code`**
  (needs code access); **`/chat`** downgrades back, keeping the files.

Everything runs on your **Claude Pro/Max subscription** via the
[Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk/overview) — **no
Anthropic API key, no per-token billing.**

[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)

---

## Features

- **Streaming:** uses native Telegram streaming
  ([`sendMessageDraft`](https://core.telegram.org/bots/api#sendmessagedraft))
  tailored for generative AI tools (Telegram only supports it in DMs now).
- **Web-capable chat** — chat sessions can **search the web** and **read pages**
  (`WebSearch` / `WebFetch`), like the Claude apps; code sessions add the full
  agent toolset (Bash, file edits, notebooks).
- **Isolated sessions** — each is its own Claude session (context, working dir,
  resume id), **born chat, upgradeable to code** (`/code` ⇄ `/chat`, same
  conversation); nothing leaks between them
  (see **One subscription, isolated memory** below). Browse / switch / rename /
  ⭐ / delete via `/sessions`.
- **Allowlist access** — only the owner and explicitly allowed users can talk to
  the bot; each allowed user has a **level** (chat or code), an optional
  **expiry**, and optional rolling **token limits** (day/week). The list lives in a
  gitignored `allowlist.json`.
- **Full owner control from Telegram** — `/settings` is one **scope-tabbed hub**
  (📍 This session · 👤 My defaults · 🌍 Global) for everything, no server access
  needed. Open **👥 Users** and tap a person to set their **access** (chat vs
  **code**), **expiry**, rolling **token limits** (day/week), **global memory**,
  **max-effort**, **which tools** they may use, and **per-option access exceptions**
  — plus their **usage stats** — all from one card. Each session's tools are also
  configurable per-session (`/tools` or `/settings → Tools`): WebSearch/WebFetch for
  chat, the full agent toolset for code.
- **Owner-configurable access model** — every setting (model, effort, permissions,
  memory, sandbox, language, …) has an owner-set **base access**: *Delegated* (the
  user sees and changes it), *Read-only* (sees it, can't change), or *Hidden* (never
  sees it; rides the global default). Set the base on the **🌍 Global** tab and make
  **per-user exceptions** on the user card. Effective values are **derived per
  prompt** (session → personal default → global), so a change applies on the next
  message with nothing to migrate.
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
             └── /new ──▸ a chat session   (switch with /sessions · upgrade with /code)
                   ├── chat: Agent SDK + web research (WebSearch/WebFetch)
                   └── code: Agent SDK + full tools, cwd = BASE_WORKDIR/<session>
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

## Message formatting

Claude replies in Markdown. The bot renders **every reply as one native rich
message** (Bot API 10.1 `sendRichMessage`, `rich_message={"markdown": …}`), so
headings, nested lists, checklists, block quotes, side-scrolling tables, math and
code render natively with **no client-side splitting**; while generating, the reply
streams already-formatted through `sendRichMessageDraft`. The same native-rich path
backs command replies and the inline-keyboard menus — the settings hub, user cards
and session menus open and edit in place via `sendRichMessage` / `editMessageText`
(`_send_menu` / `_edit_menu`, #173) — so every surface shares one font.

Classic `parse_mode="HTML"` (`markup.md_to_html`, a safe-subset Markdown→HTML
converter that escapes everything else) is the **fallback only**: if a rich
send/edit fails, the same content is delivered as classic HTML, and very long output
falls back to a `.md` document — a message is never lost.

One current client gap: a code block renders as **plain monospace** inside a rich
message (no language label, no copy button) because the Telegram client does not yet
style `RichBlockPreformatted` (#174); when it does, code renders as a full code block
with no change here.

The two rendering paths, the Markdown→HTML conversion contract, the full rich tag
catalog (headings, lists, details, math, media, tables…) and the size rules are
specified in **[markup.md](markup.md)**.

Telegram reference: [Rich message formatting options][tg-fmt] · [HTML style][tg-html].

[tg-fmt]: https://core.telegram.org/bots/api#rich-message-formatting-options
[tg-html]: https://core.telegram.org/bots/api#html-style

---

## Project structure

| File | Responsibility |
|---|---|
| `bot.py` | Entry point: wiring, middleware, long polling, graceful shutdown. |
| `watchdog.py` | systemd liveness watchdog — `READY=1` at startup, `WATCHDOG=1` only after a successful Telegram probe, so a wedged/dropped connection triggers an auto-restart. |
| `config.py` | `.env` → `Settings` (warns if `ANTHROPIC_API_KEY` is set). |
| `handlers.py` | aiogram router: commands, text/photo/document routing, callbacks, the `/` menu. |
| `commands.py` | Single source of truth for the command set + localized menu labels; `/help` and `setMyCommands` derive from it (a startup assert catches drift). |
| `settings_schema.py` | Settings registry + resolver: each setting's type/default, its session→user→global storage tier, and the owner access model behind the `/settings` hub. |
| `engine.py` | `ClaudeSession` over the Agent SDK — **all** SDK code lives here (incl. the sandbox launcher). |
| `sessions.py` | `SessionManager`: per-session worker, the chaining queue, `/stop`, usage accounting. |
| `archive.py` | Cold storage (#177): on delete, bundle a session's workdir + transcript into one gzip archive instead of destroying it. |
| `streamer.py` | Live reply: native `sendMessageDraft` streaming in DM, code-block rendering, usage footer. |
| `permissions.py` | `PermissionGate`: the code-mode Allow/Deny approval gate. |
| `access.py` | Middleware: allowlist (drops non-allowed updates) + per-user language resolution. |
| `allowlist.py` | JSON-backed access store: levels, expiry, token caps; owner always allowed; fail-closed. |
| `db.py` | `aiosqlite` state: sessions, usage, conversation log, key-value store (schema under **Data, privacy & trust**). |
| `i18n.py` | Localization table + `t(key, lang, …)`; `en` canonical, `ru` translation. |
| `markup.py` | Telegram formatting: Markdown→HTML (bold/italic/strike/spoiler/quotes/code), 4096-safe splitting, long-output-as-file. See **Message formatting**. |
| `rich_message.py` | Hand-rolled binding for Bot API 10.1 `sendRichMessage` — native bordered/striped tables (`markup.py` builds the rich HTML). |
| `table_image.py` | Dormant PNG-table fallback (#162), kept commented out now that tables use `sendRichMessage`. |
| `usage.py` | Formatters for the 5h / 7d subscription windows. |
| `deploy/` | `tg-bot.service` (systemd unit) and `sandbox-claude.sh` (bubblewrap launcher). |

Tasks are tracked in [`TODO.md`](TODO.md); contributor rules in
[`AGENTS.md`](AGENTS.md) and [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## Data & directory layout

All state lives on the host running the bot — there is no external service. The
runtime owner of every file is the **service user** (whoever ran `claude
setup-token` and the systemd unit); that user can read everything below.

```
<repo>/                          ← the checkout (service user owns it)
├── *.py                         ← application code (see Project structure)
├── .env                         ← config + secrets: TELEGRAM_BOT_TOKEN, OWNER_ID,
│                                  DEFAULT_MODEL, BASE_WORKDIR, DB_PATH, ALLOWLIST_PATH,
│                                  optional SANDBOX_*/concurrency caps        [gitignored]
├── allowlist.json               ← access store: per-user level/expiry/caps    [gitignored]
├── bot.db (+ -wal, -shm)        ← SQLite state (see tables below)             [gitignored]
└── bot.log                      ← run log                                     [gitignored]

/var/lib/claude-tg-bot/workdirs/  (= BASE_WORKDIR — outside /root so a per-session jail uid can reach it)
├── <sid>/                       ← one directory per session, named by the PUBLIC sid (#181); 0711
│   ├── work/                    ←  the agent's cwd (owned by the session's host uid, 0700);
│   │                               bound into the jail, writable
│   ├── state/                   ←  the jail HOME → ~/.claude/projects: the session TRANSCRIPT.
│   │                               Sibling of work/, deliberately NOT bound into the jail.
│   └── secrets.env              ←  optional per-session user creds (#119d), root-owned 0600,
│                                   injected as env vars into THIS jail only (never bound in)
└── _archive/<owner_id>/<sid>-<stamp>.tar.gz   ← cold storage on delete (#177); purged after retention (#178)
```

`<sid>` is the public session id shown in `/sessions`, never the internal numeric id.
Per-session isolation is structural: each session sees only its own `work/` (the mount
namespace), and — with `SANDBOX_PER_SESSION_UID` on — `work/` is owned by a distinct
non-root host uid, so even a jail escape can't read another session's files. The
subscription credential is injected read-only in the bare jail — or, with the broker
(#119b) on, kept OUT of the jail entirely (a `BROKER-PLACEHOLDER` dummy is injected and a
host broker supplies the real token). See **Security & isolation** and
[`isolation.md`](isolation.md) for the full scheme.

**SQLite tables in `bot.db`** (additive-migration only; full schema +
storage layout in [`data-model.md`](data-model.md)):

| Table | One row per | Holds |
|---|---|---|
| `threads` | session | mode, model, cwd, resumable chat/code session ids, and every per-session toggle (effort, permission mode, max-turns, sandbox, favorite, enabled tools, …) |
| `usage` | turn | `input/output_tokens`, `cache_read/creation`, `cost_usd`, plus `model` + `context_tokens` for the weighted usage-units metric (#165); rolls up per user by `chat_id` |
| `messages` | message | conversation log feeding `/last`, `/recap`, `/history` |
| `kv` | key | small state: current-session pointer, usage display mode, per-user language, pinned-message id, access overrides, user defaults |
| `rate_history` | snapshot | subscription rate-limit samples for the `/status` trend |

The subscription credential itself lives **outside** the repo, in the service user's
`~/.claude/.credentials.json` (written by `claude setup-token`, refreshed before expiry
by `token_refresh.py` #191). It is **never** stored in `bot.db` and never copied into a
session directory; with the credential broker (#119b) on it is never placed in a jail at
all — the jail gets a `BROKER-PLACEHOLDER` dummy and the host broker injects the real
token on the outbound request. Full data-flow: [`isolation.md`](isolation.md).

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
  | `Pillow==12.2.0` | Renders the dormant PNG-table fallback (`table_image.py`); needs the system DejaVu Sans Mono font. |

- Optional: the **`bubblewrap`** package (e.g. `apt install bubblewrap`) for the
  code sandbox; **`pytest`** + **`ruff`** (`requirements-dev.txt`) for development.
- Optional (only for the #119 egress allowlist, `SANDBOX_EGRESS`): **`iptables`** (the
  `iptables-nft` backend is fine) + the **`xt_cgroup`** kernel module + **cgroup v2**
  (standard under systemd). No `nftables` and **no extra Python packages** are needed.
  The full isolation scheme is documented in [`isolation.md`](isolation.md).

### Resource requirements & concurrency limits

Each **active session holds a live `claude` subprocess (~400–600 MB RSS)** — the
dominant memory cost (the bot itself is ~130 MB; `opus` + a 1M context sit at the
high end). The bot **self-limits** based on the box's RAM/CPU and **reaps idle
sessions** — their subprocess is closed, but the transcript stays on disk and
`resume` rebuilds it on the next message, so **no history is lost**. Rough capacity
on Debian 12/13 (defaults auto-derived at startup):

| RAM | Concurrent **active** turns | Live clients held | Notes |
|---|---|---|---|
| 2 GB | 2 | 2 | tight — **add 2–4 GB swap**; prefer `sonnet`/`haiku` |
| 4 GB | 4 | ~5 | comfortable for a small group |
| 6 GB | 6 | ~7 | |
| 8 GB | 8 | ~11 | |

Defaults ≈ `live = (RAM_MB − 900) / 550`, `turns = min(live, 2×CPU)`. Because **idle
sessions are evicted after 15 min** (and under memory pressure), you can serve many
more *users* than the "live clients" column — only simultaneously-**active** turns
cost RAM. Always configure **swap** as an OOM backstop: with no swap, exhausting RAM
is a hard kill, not a slowdown.

Tunables (`.env`, all optional — sane defaults derived from the box):

| Var | Default | Meaning |
|---|---|---|
| `MAX_LIVE_CLIENTS` | from RAM | Max simultaneously-live `claude` subprocesses (idle+busy). |
| `MAX_CONCURRENT_TURNS` | from RAM/CPU | Max turns generating at once; overflow turns queue with a "server busy" notice. |
| `IDLE_TTL_SEC` | `900` | Reap a session's subprocess after this many seconds idle. |
| `MIN_FREE_MB` | `400` | Below this much free RAM, evict idle sessions before starting a turn. |
| `CRED_BROKER` | `0` | Keep the subscription token OUT of every jail — a host broker injects it (#119b). |
| `SANDBOX_EGRESS` | `0` | Hard-block jail egress to loopback only; dev hosts via the CONNECT proxy (#119c). |
| `EGRESS_ALLOW_HOSTS` | _(empty)_ | Extra CONNECT-allowlisted hosts (beyond github/pypi/npm/anthropic), comma/space separated. |
| `SANDBOX_MEM_MB` / `SANDBOX_CPU_PERCENT` / `SANDBOX_PIDS_MAX` | `0` | Per-jail cgroup limits (0 = unlimited; CPU% of one core) (#119e). |
| `SANDBOX_SECCOMP` | `0` | Load an x86_64 seccomp denylist into the jail (refuses exotic syscalls) (#119e). |
| `SANDBOX_PER_SESSION_UID` | `0` | Run each jail as a distinct non-root host uid (escape hardening; needs `BASE_WORKDIR` outside `/root`). |
| `SANDBOX_UID_BASE` / `SANDBOX_UID_RANGE` | `700000` / `60000` | Host-uid range for per-session uids (`base + sid % range`). |
| `MAX_SESSIONS_PER_USER` | `10` | Global default cap on sessions per user (owner-overridable in Settings → Admin and per user). |

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
(`DEFAULT_MODEL`, `BASE_WORKDIR`, `DB_PATH`, `ALLOWLIST_PATH`, the optional sandbox
flags `SANDBOX_CODE` / `SANDBOX_UID` — see **Security & isolation** — and the
concurrency caps `MAX_LIVE_CLIENTS` / `MAX_CONCURRENT_TURNS` / `IDLE_TTL_SEC` /
`MIN_FREE_MB` — see **Resource requirements & concurrency limits**) have sensible
defaults.

**Run:**

```bash
. .venv/bin/activate
python bot.py
```

Open a DM, `/start`, create a session with `/new`, and say hello — when you need a
terminal or files, upgrade it with `/code`. `/help` lists every command.

---

## Access control

The bot answers only the **owner** (`OWNER_ID`) and users on the **allowlist**;
every other update is dropped before any handler runs (fail-closed — a
missing/corrupt `allowlist.json` means owner-only, never everyone).

Each allowed user has a **level** (`chat` = chat mode only, or `code` = chat +
code), an optional **expiry** date, and optional **rolling usage limits** (a
trailing-24h and a trailing-7d cap). The caps count **weighted usage units** — a
cost-aware metric (model weight + output + cache) that mirrors how the shared
subscription windows actually fill, rather than raw input+output tokens (#165).
Manage it from Telegram (owner only): `/allow <id|@user>`, `/deny`, `/level`,
`/expire`, `/limit`, `/users`.

Numeric ids are authoritative; a `@username` grant is **pinned to its numeric id**
on the user's first message (usernames can be hijacked if freed). `allowlist.json`
is gitignored — see [`allowlist.example.json`](allowlist.example.json) for the
format.

---

## Commands

The full set lives in the tap-to-open Telegram menu (descriptions localized;
code-only commands are hidden from chat-level users, owner commands from everyone
else). Plain text goes straight to the current session's Claude.

Commands are registered **most-used first** (Telegram surfaces the top few on
mobile); `/new`, `/sessions`, `/settings` sit at the very top. Fixed-choice commands
open an inline **picker**; commands needing free text prompt for your next message
(with `/cancel`). The `/help` text is generated from this same registry, so it never
drifts. The full command + settings **menu structure** is documented in
**[menu.md](menu.md)**.

| Group | Commands |
|---|---|
| **Sessions** | `/new` `/code` (upgrade) `/chat` (downgrade) `/sessions` `/rename` `/fork` `/clear` (alias `/reset`) |
| **Run** | `/status` `/retry` `/context` `/limits` (your usage) `/queue` `/clearqueue` |
| **Tuning** | `/model` `/effort` `/memory` `/language` · *(code)* `/permissions` `/files` `/export` `/maxturns` `/tools` |
| **Recap & export** | `/recap` (AI one-line recap) `/last` (verbatim last exchange) `/history` (transcript) |
| **Meta** | `/settings` `/usage` `/help` `/whoami` |
| **Owner** | `/users` `/userstats` (usage table) `/allow` `/deny` `/level` `/expire` `/limit` `/auto` `/codesplit` `/sandbox` |

---

## Security & isolation

- **Access** is owner + allowlist, fail-closed; the bot token and `allowlist.json`
  are gitignored and never logged. **Subscription only** — no API key, no
  per-token billing.
- **Every session runs in a sandbox by default (#180).** Each session's `claude`
  — chat AND code — runs in a [bubblewrap](https://github.com/containers/bubblewrap)
  jail: an **unprivileged uid** (not host root), filesystem **confined to the
  session's own workdir**, the root filesystem read-only, the bot's env wiped, and
  the subscription credential injected read-only (requires the `bubblewrap`
  package). Neither the agent nor the user can read or write outside that session's
  directory. Dangerous code tools (Bash/Write/Edit) are still gated behind an
  explicit Allow/Deny tap (or `/auto on`). The owner can toggle the jail per session
  with `/sandbox on|off`.
- **Full isolation is available (#119) — opt-in, off by default.** The bare jail
  confines the **filesystem**; the four flags below turn it into real containment for a
  semi-trusted `code` user. Until you enable them (at least the broker + egress), grant
  `code` only to people you trust. All OS/network mechanism lives in
  [`deploy/`](deploy/) (shell + standalone), gated behind these flags; tracked as **#119
  in [`TODO.md`](TODO.md)**.
  - **Credential broker (`CRED_BROKER=1`, #119b).** Keeps the subscription OAuth token
    **out of every jail**: the jailed `claude` gets only a dummy `BROKER-PLACEHOLDER`
    plus `ANTHROPIC_BASE_URL` pointing at a host-side broker
    ([`deploy/cred-broker.py`](deploy/cred-broker.py)) that injects the real bearer
    (read fresh from disk, kept current by the #191 refresher) and forwards to
    `api.anthropic.com`. The agent can't read, print, or exfiltrate the token — there's
    nothing real inside to take. OAuth only (never an API key).
  - **Egress allowlist (`SANDBOX_EGRESS=1`, #119c — code sessions).** A code jail's
    network egress is hard-blocked to loopback only by a **cgroup-scoped** iptables rule
    (never global — it can't lock out SSH or the bot). `claude` reaches Anthropic via the
    broker; the agent's tools reach an allowlisted set of dev hosts (Anthropic +
    GitHub/PyPI/npm by default, extend with `EGRESS_ALLOW_HOSTS`) via a CONNECT proxy
    ([`deploy/egress-proxy.py`](deploy/egress-proxy.py)); everything else is dropped, so
    there's no way to POST data to an arbitrary host. (Chat sessions keep open egress —
    no Bash to exfil with, and the web tools need arbitrary URLs.)
  - **Per-session secrets (`/secret`, #119d).** A `code` user stores **their own** service
    credentials (e.g. a GitHub token) for the current session; they're injected as env
    vars into that session's jail only. Your own credentials never enter any jail.
  - **DoS limits + seccomp (#119e).** Per-jail memory/CPU/process caps (`SANDBOX_MEM_MB`
    / `SANDBOX_CPU_PERCENT` / `SANDBOX_PIDS_MAX`) and an optional x86_64 syscall denylist
    (`SANDBOX_SECCOMP=1`) shrink the blast radius of a runaway or hostile session.
  - **Per-session host uid (`SANDBOX_PER_SESSION_UID=1`).** Each jail runs as a distinct
    non-root host uid (via `setpriv` + an unprivileged user namespace), with its workdir
    chowned to that uid. A jail escape therefore lands as an unprivileged user — not host
    root — and still cannot read another session's files. Requires `BASE_WORKDIR` outside
    `/root` (defaults to `/var/lib/claude-tg-bot/workdirs`).

### Where session files live

Everything for a session lives under **one parent dir** (#181) — nothing is stored
outside it:

```
workdirs/<sid>/
  ├── work/    ← the agent's cwd: the files it creates (bound into the jail, writable)
  └── state/   ← the jail HOME → ~/.claude/projects: the session TRANSCRIPT. A sibling
                 of work/, deliberately NOT bound into the jail, so the agent can't
                 reach it (or any other session) through its own tools.
workdirs/_archive/<owner_id>/<sid>-<stamp>.tar.gz   ← cold storage on delete (#177); auto-purged after retention (#178)
```

`<sid>` is the public session id shown in `/sessions` (never the internal id).
Deleting a session bundles its whole `<sid>/` folder into one gzip archive and
removes the live copies (#177) — files and transcript together, nothing lost.
Archives older than the **retention period** are then auto-purged (#178; default
**6 months**, owner-configurable under **`/settings → 👑 Admin → 🗄 Archive
retention`** or the `ARCHIVE_RETENTION_DAYS` env var; choose **Never** to keep
them forever).
- **Hidden CLI keyword triggers are neutralized.** The bundled Claude CLI acts on
  prompt keywords like `ultrathink` (escalates reasoning effort) and `ultracode`
  (spins up multi-agent **Workflow** orchestration) — either could let any user
  silently burn the owner's one shared subscription or bypass the per-user effort
  gate. The bot disables Workflows outright (`CLAUDE_CODE_DISABLE_WORKFLOWS=1`) and
  defuses the keywords in every prompt. The blocked list defaults to `ultrathink,
  ultracode`; add more (no code change) via the **`BLOCKED_PROMPT_KEYWORDS`** env
  var (comma/space-separated). Reasoning depth is controlled only through `/effort`.

Report vulnerabilities privately — see [`SECURITY.md`](SECURITY.md).

---

## Data, privacy & trust

Everything happens on **your server** — there is no external database.

- **What's stored, and where.** Per-session state, **conversation transcripts**
  (used by `/last` and `/history`), and token usage live in the SQLite DB
  (`bot.db`), across five tables:
  - **`threads`** — one row per session (mode, model, cwd, the resumable chat/code
    session ids, and every per-session toggle: effort, permission mode, max-turns,
    sandbox, favorite, enabled tools, …).
  - **`usage`** — one row per turn (input/output tokens, cache read/creation, cost,
    plus the turn's `model` + `context_tokens` for the weighted usage-units metric,
    #165); per-user totals roll up by `chat_id`.
  - **`messages`** — the conversation log feeding `/last`, `/recap`, `/history`.
  - **`kv`** — small key-value state (current-session pointer, usage display mode,
    per-user language, pinned-message id, access overrides, user defaults).
  - **`rate_history`** — subscription rate-limit snapshots for the `/status` trend.

  Code sessions also keep their files under `BASE_WORKDIR/<session>`, and Claude's
  own resume state under the bot user's `~/.claude/projects`. All of it sits on the
  host's disk. The full schema (and the additive-migration rule) is in
  [`AGENTS.md`](AGENTS.md) → **Architecture → Data model**.
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

[`deploy/tg-bot.service`](deploy/tg-bot.service) supervises the bot so it survives
crashes, reboots, and Telegram outages.

**Quick install:** `sudo deploy/install-systemd.sh` — it adapts the unit to your
checkout path/user, stops any manual copy, then enables + starts the service (add
`--with-timer` to also enable the daily restart). Or do it by hand — edit the
paths/`User`, then:

```bash
sudo cp deploy/tg-bot.service /etc/systemd/system/claude-tg-bot.service
sudo systemctl daemon-reload
pkill -f 'python bot\.py$'            # stop any manual copy first (avoid a 409)
sudo systemctl enable --now claude-tg-bot
journalctl -u claude-tg-bot -f
```

Resilience built in:

- **`Restart=always` + `StartLimitIntervalSec=0`** — respawns on any crash/exit and
  on boot, and never gives up (a long Telegram outage just keeps retrying until the
  network path is back).
- **Connection watchdog** (`Type=notify` + `WatchdogSec=180`, driven by
  [`watchdog.py`](watchdog.py)) — the bot pings systemd only after a *successful*
  Telegram probe, so if it can't reach Telegram for ~3 minutes (connection dropped or
  polling wedged) systemd force-restarts it. This auto-recovers an outage instead of
  leaving the process dead.
- **Proactive OAuth token refresh** — the subscription access token has a hard ~8 h
  life and nothing else rotates it (the idle reaper recycles the `claude` subprocess
  but a fresh one re-reads the same on-disk token), so after a long idle gap a turn
  would 401 until a manual re-login. A background loop ([`token_refresh.py`](token_refresh.py),
  started next to the usage poller) renews the token via the OAuth `refresh_token`
  grant and rewrites `~/.claude/.credentials.json` before it expires — subscription
  auth only, never an API key, fail-soft. Tunable / disablable via `OAUTH_REFRESH`
  (kill-switch), `OAUTH_REFRESH_INTERVAL_SEC` (default 1800), `OAUTH_REFRESH_SKEW_SEC`
  (default 3600).
- **Optional daily restart** —
  [`deploy/claude-tg-bot-restart.{service,timer}`](deploy/) add a clean daily restart
  as insurance against slow leaks. Enable with
  `sudo systemctl enable --now claude-tg-bot-restart.timer`.

Restart after a code change with `sudo systemctl restart claude-tg-bot` (never a
second manual `python bot.py` — two pollers per token → 409). Run the service as the
**same user** that ran `claude setup-token`, so it can read the subscription
credentials from that user's home.

---

## Saving subscription limits

Watch `/usage` and `/status`: chain follow-ups within the 5-minute prompt cache,
keep one project per session, and right-size the model with `/model`. The owner's
personal limit-saving notes live in a local, gitignored `CLAUDE.md`; shared
conventions in `AGENTS.md`.

---

## Known issues

- **Long answers can look like they "retype" on Telegram Desktop for macOS.** Live
  replies stream as a native message *draft*, which Telegram caps at ~4096
  characters. Past that cap the draft tracks the model's frontier, and **Telegram
  Desktop for macOS** re-renders the whole draft on each jump — so a long answer can
  appear to rewrite itself several times *while streaming*. On **iOS** the same
  stream animates smoothly in one pass. This is a client-side draft-rendering
  limitation, not a bot bug: the **final posted message is always complete and
  correct** on every client.

---

## Legal

For personal, development, and research use. You are solely responsible for how
you use it and must comply with applicable laws and with the Anthropic and
Telegram terms of service. MIT licensed — see [`LICENSE`](LICENSE).
