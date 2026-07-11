---
id: TASK-35
title: "graceful `/stop` could surface a spurious error status line"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 35
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
graceful `/stop` could surface a spurious error status line
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
engine sets `_interrupted` in `interrupt()`; `run()` returns quietly on an exception while interrupted, so the streamed partial stands as the final answer (real failures still surface). Functionally tested.
<!-- SECTION:NOTES:END -->

