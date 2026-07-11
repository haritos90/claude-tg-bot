---
id: TASK-357
title: "Rename the user-facing \"Big memory\" option to \"1M context\""
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 357
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The per-session 1M-context-window toggle is now labelled **1M context** (was "Big memory") across /settings, /status, /memory and the menu — clearer, and no longer confusable with the assistant's saved session memory.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Renamed every USER-FACING "Big memory" label — both the EN string and its RU translation — to "1M context" (and the RU equivalent): 7 EN + 7 RU i18n keys (`settings.row_memory`, `memory.show`/`already`/`on`/`off`, `status.big_memory`, `status.chk_bigmem` — the last dropped its now-redundant "(1M context)" parenthetical), plus `docs/menu.md` (the settings-hub rows + the delegation worked example). The internal `big_memory` flag/column/functions and the `/memory` command keyword are unchanged (its description already read "1M context window"). Left the distinct #352 *Session memory* (`remember`/`/forget`) and #275 *Global memory* surfaces untouched — the rename also disambiguates the three "memory" concepts. i18n en/ru placeholder + HTML-tag parity test green; renders verified. compile + import + ruff + suite 266 green; live restart "Run polling".
<!-- SECTION:NOTES:END -->

