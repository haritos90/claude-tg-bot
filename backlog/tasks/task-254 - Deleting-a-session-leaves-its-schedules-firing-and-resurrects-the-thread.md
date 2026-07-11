---
id: TASK-254
title: "Deleting a session leaves its schedules firing and resurrects the thread"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 254
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Deleting a session now also removes its schedules (no zombie schedule resurrecting a deleted session), and a scheduled run waits for free memory instead of risking an out-of-memory kill.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`db.delete_dm_session` now cascades `DELETE FROM schedules WHERE thread_id = ?` alongside the usage/messages/session_uid deletes, so a deleted session's schedules go with it (reset_thread deliberately keeps them — the session still exists). Belt-and-suspenders in `sessions._fire_schedule`: an orphan guard (`db.get_thread is None` → disable + `last_status="orphaned"`) stops any legacy orphan from re-minting the thread via `ensure_thread`. Also added a no-swap memory gate: before firing (which spawns a claude jail) it evicts idle clients on pressure and, if MemAvailable is still below `min_free_mb`, DEFERS the fire (leaves `next_run` untouched → retried next ~30s sweep) instead of risking an OOM kill. +5 runner tests (dispatch/defer/orphan/revoke/cascade). py_compile + import + ruff + i18n parity clean; suite 197 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

