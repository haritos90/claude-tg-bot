# AGENTS.md

Context for AI coding agents working on this repo. The human contribution process is
in [CONTRIBUTING.md](CONTRIBUTING.md).

This is a private Telegram bot: a personal frontend to Claude and Claude Code. Each user
talks to it in a private chat and keeps isolated sessions. A session is born a chat and
can be promoted to code and back; the conversation carries across the switch.

Access is owner plus allowlist. Runs on the owner's Claude Pro/Max subscription via the
Agent SDK — no Anthropic API key, no per-token billing.

Supergroup/Topics mode is frozen: the forum-Topics-as-sessions code is still present but dormant
until Telegram fixes drafts streaming in groups.

---

## 1. Working on the project

Code comments reference maintainer task ids as `#N`. Don't reuse these numbers.
Describe your changes in the PR.

Docs are part of the change:

- Update the doc a change implies, in the same batch. A schema change updates
  [data-model.md](docs/data-model.md); a menu/command change updates [menu.md](docs/menu.md); a
  config/operational change updates [configuration.md](docs/configuration.md) and `README.md`; a
  production incident updates [troubleshooting.md](docs/troubleshooting.md). Code without its doc
  update is incomplete.
- Keep docs structure.
- Spec voice, English only: declarative, present tense, no first person, no provenance or chat
  quotes. State the decision as a neutral fact.

---

## 2. Build, run, test

```bash
# one-time
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements/base.txt -r requirements/dev.txt -r requirements/voice.txt
cp .env.example .env                 # fill TELEGRAM_BOT_TOKEN + OWNER_ID
cp allowlist.example.json allowlist.json

# the Claude Code CLI must be installed and logged in to the subscription:
claude --version                     # Prints version
claude setup-token                   # headless subscription login (no API key)

# smoke test — must exit 0
python -m compileall -q app conftest.py
python -c "import app.config, app.storage.db, app.i18n, app.access.access, app.access.allowlist, app.telegram.markup, app.telegram.rich_message, app.telegram.table_image, app.telegram.streamer, app.access.permissions, app.telegram.commands, app.access.settings_schema, app.core.engine, app.core.sessions, app.storage.archive, app.storage.usage, app.telegram.handlers, app.watchdog, app.bot"

# run
python -m app
```

Development and test extras are in `requirements/dev.txt` (`pytest`, `ruff`); run `pytest -q` and
`ruff check .` before opening a PR.

---

## 3. Golden rules

1. English is the canonical language. Code, comments, docstrings, docs, identifiers, and commit
   messages are English only. User-facing strings are localized via `i18n.py`. Non-English
   text is allowed in the three translation surfaces — `i18n.py` `ru` values, `commands.py` `ru`
   labels, `menu.md` bilingual label tables.
2. Secrets and identities stay out of code and git. Secrets live in `.env`, the user list in
   `allowlist.json`; both are gitignored.
3. Subscription, not API. Don't set or read `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN`; the engine
   strips them from the spawned `claude` environment. Code reaching for an API key is a bug.
4. Isolation. Every `ClaudeAgentOptions` sets `setting_sources=[]` (see
   [gotchas.md](docs/gotchas.md)). Each session gets its own `ClaudeSession`, `resume` id, `cwd`
   and message queue.
5. Owner plus allowlist access. `access.AllowlistMiddleware` drops every update not from the owner or
   an allowlisted user, and fails closed. Allowlist management is owner-only.
6. Conventional Commits: `<type>(<scope>): <imperative summary>`.
7. Keep changes small and idiomatic — match the surrounding file, comment the why not the what.
8. Preserve replaced code as a commented-out block. When changing or removing
   existing logic, comment the old version next to the new code so changes stay auditable.

---

## 4. Reference — pull detail on demand

[gotchas.md](docs/gotchas.md) collects the hard-won SDK, Telegram, lifecycle, and sandbox
invariants that have caused real bugs — read the matching section before editing `engine.py`,
`streamer.py`, `handlers.py`, `sessions.py`, `i18n.py`, `db.py`, or anything under `deploy/`.

| Reference                                         | Read it when                                                                   |
| ------------------------------------------------- | ------------------------------------------------------------------------------ |
| [gotchas.md](docs/gotchas.md)                     | Editing any of the modules above.                                              |
| [architecture.md](docs/architecture.md)           | Locating where a change belongs.                                               |
| [configuration.md](docs/configuration.md)         | Adding or changing an `.env` setting.                                          |
| [data-model.md](docs/data-model.md)               | Touching `db.py`, the SQLite schema, or the on-disk session layout.            |
| [isolation.md](docs/isolation.md)                 | Touching the sandbox stack (jail, broker, egress, seccomp, uids) or `deploy/`. |
| [menu.md](docs/menu.md)                           | Adding or changing a command, button, menu, or settings row.                   |
| [markup.md](docs/markup.md)                       | Message rendering: Markdown→HTML, splitting, tables, attachments.              |
| [rich-message-spec.md](docs/rich-message-spec.md) | The Bot API 10.1 rich-message and draft-streaming.                             |
| [troubleshooting.md](docs/troubleshooting.md)     | Diagnosing runtime behavior; update it after fixing an incident.               |
| [README.md](README.md)                            | Setup and the user-facing walkthrough.                                         |
