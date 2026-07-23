# Contributing to claude-tg-bot

Thanks for helping out. This file is the contribution guide: conventions, language rules, and the
pre-PR checks. Keep changes small and consistent with the file you're editing — match the
surrounding style, comment the why not the what, and don't add abstractions beyond what the task
needs. The module map is in [architecture.md](docs/architecture.md).

## AI-assisted contributions

Using AI coding tools is welcome. Two rules:

- You are responsible for what you submit. Review and understand every line, run the smoke checks
  below, and be ready to answer review questions about the change — the model having written it is
  not a defense.
- Point your tool at [`AGENTS.md`](AGENTS.md), the agent context file with the always-on rules and
  a reference index (most agent tools pick it up automatically). Everything in this guide applies
  to AI-written code exactly as to hand-written code.

## Editing existing code

When you change or remove existing logic, don't delete it outright — comment the old version out next
to the new code with a short reference to the task it changed for (e.g. `# was: <old> — replaced for
#NNN`), so changes stay auditable and easy to revert. Full deletion is reserved for tasks whose
explicit goal is removal or cleanup.

## Language: English everywhere

The repository is English only — it may be released publicly.

| Where | Language |
|---|---|
| Code comments and docstrings | English |
| Documentation | English |
| Commit messages | English |
| Identifiers (names, keys) | English |
| User-facing bot strings | Localized — see below |

### Localization

User-facing text is never hardcoded in a handler. Add a row to the `i18n.CATALOG` table and render it
with `i18n.t(key, lang, …)`, resolving the acting user's locale. The `en` column is the canonical
source; `ru` is a translation layer. The two must share identical `{placeholders}` and identical HTML
tags per row — the test suite enforces this, and `t()` falls back to `en`, then to the raw key, when a
translation is missing. Only the bot's own UI is localized — never Claude's output, logs, or
model-facing strings.

## Commits

Use [Conventional Commits](https://www.conventionalcommits.org/): `type(scope): imperative summary`,
e.g. `feat(engine): stream tool status into the session`. Types: `feat` · `fix` · `docs` ·
`refactor` · `test` · `build` · `chore`.

## Tasks

Tasks are tracked privately by the maintainer with [Backlog.md](https://github.com/MrLesk/Backlog.md)
in a local `backlog/` directory (not part of this repo). Code comments reference task numbers as
`#N`; those numbers are permanent, so never renumber or reuse one. When contributing, describe the
change in your PR — you don't need the tracker.

## Before you open a PR

Run the smoke checks — cheap, and they catch most breakage (you don't need to start the bot to
verify syntax; `pytest` and `ruff` come from `requirements/dev.txt`):

```bash
pip install -r requirements/dev.txt
python -m compileall -q app conftest.py
python -c "import app.config, app.storage.db, app.i18n, app.access.access, app.access.allowlist, app.telegram.markup, app.telegram.rich_message, app.telegram.table_image, app.telegram.streamer, app.access.permissions, app.telegram.commands, app.access.settings_schema, app.core.engine, app.core.sessions, app.storage.archive, app.storage.usage, app.telegram.handlers, app.watchdog, app.bot"
ruff check .
pytest -q
```

And keep these hard invariants intact:

- Never introduce `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` anywhere — env, `.env`, a test
  harness. Its presence forces paid API billing and bypasses the subscription.
- Keep `setting_sources=[]` on every `ClaudeAgentOptions` — `[]` is isolation; `None` loads all
  global settings (the opposite).
- Don't widen `permissions.SAFE_TOOLS` (or move a dangerous tool into `allowed_tools`) without a
  deliberate reason — that silently bypasses the Allow/Deny approval gate.

For the deeper SDK, Telegram, and async invariants, read [`docs/gotchas.md`](docs/gotchas.md)
rather than re-deriving them here.
