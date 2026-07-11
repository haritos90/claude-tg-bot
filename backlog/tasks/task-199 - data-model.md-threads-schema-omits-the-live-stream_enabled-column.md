---
id: TASK-199
title: "data-model.md threads schema omits the live stream_enabled column"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - docs
dependencies: []
ordinal: 199
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The data model reference now documents the `stream_enabled` column, matching the actual table.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The `threads` schema spec (`data-model.md:58`) listed the per-session migration toggles but dropped `stream_enabled`, a real migrated column (`db.py` ALTER + select + `set_stream_enabled`, read live in `sessions.py` to gate reply streaming). Added `stream_enabled` to the documented toggle list with a one-line note that the column is still read live but its user-facing toggle was retired in #144 (streaming is always-on). Stale line refs in the task (db.py:58/189/276, data-model.md:804) were pre-move; the doc is now 92 lines and the schema sits at line 58.
<!-- SECTION:NOTES:END -->

