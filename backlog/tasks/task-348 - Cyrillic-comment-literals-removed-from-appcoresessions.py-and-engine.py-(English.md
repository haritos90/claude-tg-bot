---
id: TASK-348
title: "Cyrillic comment literals removed from `app/core/sessions.py` and `engine.py` (English-only)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - docs
dependencies: []
ordinal: 348
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Cyrillic comment literals removed from `app/core/sessions.py` and `engine.py` (English-only)
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Replaced the two Cyrillic example strings in `sessions._topic_from_text` (a docstring probe example and the `< 10 alpha` comment) with neutral English, plus an adjacent pre-existing Cyrillic word in an `engine.py` incident-note comment, satisfying the English-only rule (non-English is permitted only in the `i18n.py` / `commands.py` / `menu.md` translation surfaces). No behaviour change. compile + import + ruff + suite 258 green; live restart "Run polling".
<!-- SECTION:NOTES:END -->

