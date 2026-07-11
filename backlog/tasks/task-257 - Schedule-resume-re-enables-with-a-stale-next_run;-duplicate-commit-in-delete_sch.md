---
id: TASK-257
title: "Schedule resume re-enables with a stale `next_run`; duplicate commit in `delete_schedule`"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 257
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Resuming a paused schedule no longer risks an immediate burst of catch-up runs.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`handlers.on_schedules_cb` resume now recomputes `next_run` inside a `try` and only calls `set_schedule_enabled(sid, True)` when that SUCCEEDS (a bad spec stays paused with `common.error`), so a resume can no longer re-enable with a stale past `next_run` that fires for every missed slot on the next sweep. Removed the duplicate `await conn.commit()` in `db.delete_schedule`. py_compile + import + ruff clean; suite 197 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

