---
id: TASK-336
title: "Cyrillic in an `i18n.py` comment — English-only violation"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - docs
dependencies: []
ordinal: 336
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Cyrillic in an `i18n.py` comment — English-only violation
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
A code comment in `i18n.py` quoted a non-English label to describe an i18n change (a banned pattern; non-English text is allowed only in the `ru` catalog VALUES, never in comments / keys / `en` values). Restated in English ("the units label (shorter than tokens)"). Comment-only — no runtime impact. compile + import + ruff + suite 249 green.
<!-- SECTION:NOTES:END -->

