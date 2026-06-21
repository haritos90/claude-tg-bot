# Contributing to claude-tg-bot

Thanks for helping out. Keep changes **small** and consistent with the file you're
editing — match the surrounding style, comment the *why* not the *what*, and don't
add abstractions beyond what the task needs. [`AGENTS.md`](../AGENTS.md) is the single
source of truth for how this project works; this file is the short contributor
version of its rules.

## Editing existing code

When you **change or remove existing logic, don't delete it outright** — comment the
old version out next to the new code with a short reference to the task/issue it
changed for (e.g. `# was: <old> — replaced for #120`), so changes stay auditable and
easy to revert. Full deletion is reserved for tasks whose explicit goal is
removal/cleanup (e.g. a dead-code sweep). See `#110`/`#118` for the in-tree pattern.

## Language: English everywhere

The repository is **English only** — it may be released publicly.

| Where | Language |
|---|---|
| Code comments & docstrings | English |
| Documentation (this repo) | English |
| Commit messages | English |
| Identifiers (names, keys) | English |
| User-facing bot strings | **Localized** — see below |

### Localization

User-facing text is **never hardcoded** in a handler. Add a row to the
`i18n.CATALOG` table and render it with `i18n.t(key, lang, …)`, resolving the
**acting user's** locale. The `en` column is the canonical source; `ru` is a
translation layer. The two must share **identical `{placeholders}` and identical
HTML tags** per row (the test suite enforces this — a mismatch breaks `.format()`
or Telegram's HTML parse, and `t()` falls back to `en`, then to the raw key, when a
translation is missing). Only the bot's **own UI** is localized — never Claude's
model output, logs, or model-facing strings.

## Commits

Use **[Conventional Commits](https://www.conventionalcommits.org/)**:
`type(scope): imperative summary`, e.g. `feat(engine): stream tool status into the
session`. Types: `feat` · `fix` · `docs` · `refactor` · `test` · `build` · `chore`.

## Tasks

Work is tracked in [`TODO.md`](../TODO.md), which flows **Backlog → Open → Closed**
(with a **Deferred** parking area). Read its "How this file works" section first.
A new idea goes to **Backlog**; when you pick it up move it to **Open**; when it's
done move it to **Closed** and fill the **Resolution** column (deleting its Details
block).

## Before you open a PR

Run the smoke checks — both are cheap and catch most breakage (you don't need to
start the bot to verify syntax):

```bash
python -m py_compile *.py
python -c "import config, db, access, allowlist, markup, streamer, permissions, engine, sessions, usage, handlers, bot"
pytest -q
```

And keep these **hard invariants** intact:

- **Never introduce `ANTHROPIC_API_KEY`** (or `ANTHROPIC_AUTH_TOKEN`) anywhere —
  env, `.env`, a test harness. Its presence forces paid API billing and bypasses
  the subscription.
- **Keep `setting_sources=[]`** on every `ClaudeAgentOptions` — `[]` is isolation;
  `None` loads all global settings (the opposite).
- **Don't widen `permissions.SAFE_TOOLS`** (or move a dangerous tool into
  `allowed_tools`) without a deliberate reason — that silently bypasses the
  Allow/Deny approval gate.

For the deeper SDK / Telegram / async invariants, read **[`AGENTS.md`](../AGENTS.md)
§5** rather than re-deriving them here.
