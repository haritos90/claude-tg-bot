# Contributing to claude-tg-bot

Thanks for helping out. This file is the contribution guide: conventions, language rules, and the
pre-PR checks. Keep changes small and consistent with the file you're editing — match the
surrounding style, comment the why not the what, and don't add abstractions beyond what the task
needs. The module map is in [architecture.md](docs/architecture.md).

## AI-assisted contributions

Using AI coding tools is welcome. There are two rules:

- You are responsible for what you submit. Review and understand every line, run the smoke checks
  below, and be ready to answer review questions about the change.
- Point your tool at [`AGENTS.md`](AGENTS.md), the agent context file with the always-on rules and
  a reference index (most agent tools pick it up automatically).

## Language: English everywhere

The repository is English only.

| Where                        | Language              |
| ---------------------------- | --------------------- |
| Code comments and docstrings | English               |
| Documentation                | English               |
| Commit messages              | English               |
| Identifiers (names, keys)    | English               |
| User-facing bot strings      | Localized — see below |

### Localization

Add a row to the `i18n.CATALOG` table and render it with `i18n.t(key, lang, …)`, resolving the acting
user's locale. The `en` column is the canonical source; `ru` is a translation layer. The two must
share identical `{placeholders}` and identical HTML tags per row — the test suite enforces this,
and `t()` falls back to `en`, then to the raw key, when a
translation is missing. Only the bot's own UI is localized.

## Commits

Use [Conventional Commits](https://www.conventionalcommits.org/): `type(scope): imperative summary`,
e.g. `feat(engine): stream tool status into the session`. Types: `feat` · `fix` · `docs` ·
`refactor` · `test` · `build` · `chore`.

## Tasks

Tasks are tracked privately by the maintainer, outside this repository. Code
comments reference task numbers as `#N`; don't renumber or reuse one.
When contributing, describe the change in your PR.

## Before you open a PR

Run the smoke checks:

```bash
pip install -r requirements/dev.txt
python -m compileall -q app conftest.py
python -c "import app.config, app.storage.db, app.i18n, app.access.access, app.access.allowlist, app.telegram.markup, app.telegram.rich_message, app.telegram.table_image, app.telegram.streamer, app.access.permissions, app.telegram.commands, app.access.settings_schema, app.core.engine, app.core.sessions, app.storage.archive, app.storage.usage, app.telegram.handlers, app.watchdog, app.bot"
ruff check .
pytest -q
```
