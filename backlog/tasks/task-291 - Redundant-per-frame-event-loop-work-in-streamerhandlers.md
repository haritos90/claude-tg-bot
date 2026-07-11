---
id: TASK-291
title: "Redundant per-frame event-loop work in streamer/handlers"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - engine
dependencies: []
ordinal: 291
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Slightly less event-loop work while streaming tables and on each shell keypad tap.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Two efficiency nits. (1) `Streamer` re-ran `extract_wide_tables` + `_wide_table_notes` on every draft frame whose body contained ` | `; it now memoizes the substitution on the frame body (`_wide_cache`) so an unchanged body (keepalive / throttled re-send) skips the table re-parse. (2) `on_shell_key` awaited `_callback_key(cb)` twice (two `get_dm_current` reads per tap); it now resolves the key once and reuses it. py_compile + import + ruff + suite 227 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

