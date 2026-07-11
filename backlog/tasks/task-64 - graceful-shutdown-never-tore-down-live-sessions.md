---
id: TASK-64
title: "graceful shutdown never tore down live sessions"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - reliability
dependencies: []
ordinal: 64
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
graceful shutdown never tore down live sessions
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`bot.py` `main()` `finally` now `await sessions.aclose()` BEFORE `close_db()`, so live `claude` subprocesses disconnect, workers cancel, and best-effort writes aren't aimed at a closed DB. Verified (import + tests).
<!-- SECTION:NOTES:END -->

