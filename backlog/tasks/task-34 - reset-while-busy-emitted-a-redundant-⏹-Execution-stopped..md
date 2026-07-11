---
id: TASK-34
title: "`/reset` while busy emitted a redundant \"⏹ Execution stopped.\""
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 34
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
`/reset` while busy emitted a redundant "⏹ Execution stopped."
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Removed the worker's cancel-path `_notify` — graceful `/stop` interrupts (never cancels), so the worker is only cancelled by `reset()`/shutdown, both of which already report.
<!-- SECTION:NOTES:END -->

