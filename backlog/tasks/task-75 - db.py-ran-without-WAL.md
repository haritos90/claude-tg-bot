---
id: TASK-75
title: "db.py ran without WAL"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - reliability
dependencies: []
ordinal: 75
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
db.py ran without WAL
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`init_db` now sets `PRAGMA journal_mode=WAL` + `synchronous=NORMAL` (best-effort).
<!-- SECTION:NOTES:END -->

