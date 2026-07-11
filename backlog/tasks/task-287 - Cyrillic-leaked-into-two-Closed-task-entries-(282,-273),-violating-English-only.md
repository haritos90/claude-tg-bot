---
id: TASK-287
title: "Cyrillic leaked into two Closed-task entries (#282, #273), violating English-only"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - docs
dependencies: []
ordinal: 287
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Cyrillic leaked into two Closed-task entries (#282, #273), violating English-only
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Two Closed Resolution notes pasted the Russian translation of a placeholder name (#282) and the default session names (#273) alongside their English text. Cyrillic is permitted only in the i18n.py `ru` column, commands.py `ru` labels, and menu.md bilingual label tables — never in ledger prose. Both notes now state the names in English only; the localized strings live in i18n.py and are not quoted in the ledger.
<!-- SECTION:NOTES:END -->

