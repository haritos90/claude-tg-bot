---
id: TASK-6
title: "task chaining — queue follow-ups to reuse context + cache"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 6
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
task chaining — queue follow-ups to reuse context + cache
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Delivered: per-thread `asyncio.Queue` drained serially in the SAME session (`sessions._worker`), preserving context + prompt cache.
<!-- SECTION:NOTES:END -->

