---
id: TASK-58
title: "delete DM sessions"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 58
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
delete DM sessions
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
🗑 in `/sessions` → confirm → `sessions.reset` (close subprocess) + `db.delete_dm_session` + remove the workdir + fix the current pointer. Scoped to the user's own negative keys.
<!-- SECTION:NOTES:END -->

