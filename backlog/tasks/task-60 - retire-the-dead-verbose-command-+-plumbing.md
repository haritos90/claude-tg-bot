---
id: TASK-60
title: "retire the dead `/verbose` command + plumbing"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 60
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
retire the dead `/verbose` command + plumbing
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Removed the `/verbose` handler, `set_verbose`, the `verbose` status-dict key, the `/settings` verbose row, and the `/verbose` menu entry — zero `verbose` references remain in any `.py`. (The previous session completed the code removal but died before closing this + restarting; verified complete + closed 2026-06-14.)
<!-- SECTION:NOTES:END -->

