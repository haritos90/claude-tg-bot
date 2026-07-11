---
id: TASK-50
title: "per-session working directory by id"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 50
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
per-session working directory by id
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Default cwd is now `BASE_WORKDIR/<session_key>` (set in `allocate_dm_session` + `_ensure_state`); the engine `os.makedirs` it before a code turn (fixed "Working directory does not exist").
<!-- SECTION:NOTES:END -->

