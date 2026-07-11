---
id: TASK-63
title: "localize the bot UI (Russian) + per-user language selection"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 63
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
localize the bot UI (Russian) + per-user language selection
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
New `i18n.py` extensible l10n table (rows = keys, cols = languages; `en` canonical, `ru` translation; `t()` falls back en→key, gracefully ignores bad format args; `onoff`/`yesno`/`mode_word` helpers; `lang` is positional-only so a `{lang}`-style placeholder can't collide). Every user-facing string across `handlers.py`/`permissions.py`/`usage.py`/`sessions.py`/`streamer.py`/`engine.py` routes through `t()` with the acting user's locale; engine error events carry a stable `error_key` localized at the consumer. Per-user locale auto-detected from the Telegram `language_code` by a new `access.LanguageMiddleware`, cached in `i18n`, persisted in `db` (`kv` `lang:<uid>`), overridable via `/language` (+ a 🌐 `/settings` row). `setMyCommands` registered per locale (incl. owner scope). Scope is UI only — Claude's output is untouched; comments/docstrings/docs stay English. Adversarial multi-agent audit run; all findings fixed. `tests/test_i18n.py` (13 tests) enforces en/ru placeholder + HTML-tag parity and render-without-crash; ruff + 31 tests green; verified live (RU command menu registered with Telegram).
<!-- SECTION:NOTES:END -->

