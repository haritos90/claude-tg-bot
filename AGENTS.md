# AGENTS.md

Context for AI coding agents working on this repo: the rules that apply to every change, how to
verify a change, and an index of the reference docs. Short by design — pull per-subsystem detail
from the references in §4, reading the one that covers the area being touched. The human
contribution process (PRs, conventions, AI-usage policy) is in [CONTRIBUTING.md](CONTRIBUTING.md).

This is a private, DM-first Telegram bot: a personal frontend to Claude and Claude Code. Each user
talks to it in a private chat and keeps named, fully-isolated sessions. A session is born a chat and
can be promoted to code and back; the conversation carries across the switch.

- chat — a Claude conversation with the read-only web tools (WebSearch / WebFetch); no terminal,
  files, or code execution.
- code — a full Claude Code agent with a per-session working directory, able to run Bash and edit
  files on the server. Reached by upgrading a chat (`/code`), gated by the user's code-access level;
  `/chat` downgrades back and keeps the workdir files.

Access is owner plus allowlist. Everything runs on the owner's Claude Pro/Max subscription via the
Agent SDK — no Anthropic API key, no per-token billing.

Supergroup/Topics mode is frozen: the forum-Topics-as-sessions code is still present but dormant
until Telegram fixes drafts in groups, so DM is the only live mode. Don't add user-facing Topics
references; keep the dormant group code.

---

## 1. Working on the project

Code comments reference maintainer task ids as `#N`. The numbers are permanent and load-bearing —
never renumber, reuse, or strip one. The tracker itself is private; describe the change in the PR.

Docs are part of the change, not an afterthought:

- Update the doc a change implies, in the same batch. A schema change updates
  [data-model.md](docs/data-model.md); a menu/command change updates [menu.md](docs/menu.md); a
  config/operational change updates [configuration.md](docs/configuration.md) and `README.md`; a
  production incident updates [troubleshooting.md](docs/troubleshooting.md). Code without its doc
  update is incomplete.
- Never break a doc's structure. Each doc has a documented shape — obey it, and re-read its own
  format preamble before editing rather than guessing.
- Spec voice, English only: declarative, present tense, no first person, no provenance or chat
  quotes. State the decision as a neutral fact.

---

## 2. Build, run, test

```bash
# one-time
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements/base.txt
cp .env.example .env                 # fill TELEGRAM_BOT_TOKEN + OWNER_ID
cp allowlist.example.json allowlist.json

# the Claude Code CLI must be installed and logged in to the subscription:
claude --version                     # must print a version
claude setup-token                   # headless subscription login (no API key)

# smoke test — must exit 0 (no real .env needed, nothing starts polling)
python -m compileall -q app conftest.py
python -c "import app.config, app.storage.db, app.i18n, app.access.access, app.access.allowlist, app.telegram.markup, app.telegram.rich_message, app.telegram.table_image, app.telegram.streamer, app.access.permissions, app.telegram.commands, app.access.settings_schema, app.core.engine, app.core.sessions, app.storage.archive, app.storage.usage, app.telegram.handlers, app.watchdog, app.bot"

# run
python -m app
```

Development and test extras are in `requirements/dev.txt` (`pytest`, `ruff`); run `pytest -q` and
`ruff check .` before opening a PR. `app.bot` must never start polling or call `load_settings()` at
import time — `main()` runs only via `python -m app` — so the smoke import stays cheap.

---

## 3. Golden rules

1. English is the canonical language. Code, comments, docstrings, docs, identifiers, and commit
   messages are English only (this repo may be released publicly). User-facing strings are localized
   via `i18n.py`: never hardcode one in a handler — add a row to `i18n.CATALOG` and render it with
   `i18n.t(key, lang, …)`. Only the bot's own UI is localized; Claude's output is not. Non-English
   text is allowed only in the three translation surfaces — `i18n.py` `ru` values, `commands.py` `ru`
   labels, `menu.md` bilingual label tables — and nowhere else, including when describing an i18n
   change (reference the `CATALOG` key, give only the English).
2. Secrets and identities stay out of code and git. Secrets live in `.env`, the user list in
   `allowlist.json`; both are gitignored. Never hardcode a token, an `OWNER_ID`, or a user id, and
   never log the token.
3. Subscription, not API. Never set or read `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN`; the engine
   strips them from the spawned `claude` environment. Code reaching for an API key is a bug.
4. Isolation is sacred. Every `ClaudeAgentOptions` sets `setting_sources=[]` (see
   [gotchas.md](docs/gotchas.md)). Each session gets its own `ClaudeSession`, its own `resume` id,
   its own `cwd`, and its own message queue; no mutable session state is shared across `thread_id`s.
5. Owner plus allowlist access. `access.AllowlistMiddleware` drops every update not from the owner or
   an allowlisted user, and fails closed. Allowlist management is owner-only.
6. Dangerous tools go through the Allow / Deny gate. In code mode, anything outside
   `permissions.SAFE_TOOLS` (Bash, Write, Edit, …) is subject to the inline Allow / Deny gate; what
   actually prompts depends on the session's permission mode ([gotchas.md](docs/gotchas.md)). Don't
   widen `SAFE_TOOLS` or move a dangerous tool into `allowed_tools` without a deliberate reason.
7. Conventional Commits: `<type>(<scope>): <imperative summary>`.
8. Keep changes small and idiomatic — match the surrounding file, comment the why not the what, and
   don't add abstractions beyond what the task needs.
9. Preserve replaced code as a commented-out block with a task reference. When changing or removing
   existing logic, comment the old version next to the new code (e.g. `# was: <old> — replaced for
   #NNN`) so changes stay auditable and revertible. Exception: a task whose explicit goal is
   removal/cleanup may delete.

---

## 4. Reference — pull detail on demand

[gotchas.md](docs/gotchas.md) collects the hard-won SDK, Telegram, lifecycle, and sandbox
invariants that have caused real bugs — read the matching section before editing `engine.py`,
`streamer.py`, `handlers.py`, `sessions.py`, `i18n.py`, `db.py`, or anything under `deploy/`.

| Reference | Read it when |
|---|---|
| [gotchas.md](docs/gotchas.md) | Editing any of the modules above — per-subsystem traps and invariants. |
| [architecture.md](docs/architecture.md) | Locating where a change belongs: package layout and module map. |
| [configuration.md](docs/configuration.md) | Adding or changing an `.env` setting; tunables and capacity planning. |
| [data-model.md](docs/data-model.md) | Touching `db.py`, the SQLite schema, or the on-disk session layout. |
| [isolation.md](docs/isolation.md) | Touching the sandbox stack (jail, broker, egress, seccomp, uids) or `deploy/`. |
| [menu.md](docs/menu.md) | Adding or changing a command, button, menu, or settings row. |
| [markup.md](docs/markup.md) | Message rendering: Markdown→HTML, splitting, tables, attachments. |
| [rich-message-spec.md](docs/rich-message-spec.md) | The Bot API 10.1 rich-message and draft-streaming contract. |
| [troubleshooting.md](docs/troubleshooting.md) | Diagnosing runtime behavior; update it after fixing an incident. |
| [README.md](README.md) | Setup and the user-facing walkthrough. |
| [CONTRIBUTING.md](CONTRIBUTING.md) | The contribution guide: PR process, conventions, AI-usage policy. |

`CLAUDE.md` is a local, gitignored personal overlay; this file is the shared, committed agent
context.
