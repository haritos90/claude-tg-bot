---
id: TASK-26
title: "usage footer showed `5h (n/a)`"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - observability
dependencies: []
ordinal: 26
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
usage footer showed `5h (n/a)`
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`usage.window_str` shows the window status (`OK`/`⚠ high`/`⛔ limited`) when `utilization` is null; `%` shown only when the API sends it
<!-- SECTION:NOTES:END -->

