---
id: TASK-27
title: "implement /context /stream /verbose /rename /close /queue /clearqueue /retry"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 27
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
implement /context /stream /verbose /rename /close /queue /clearqueue /retry
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Shipped from #23: `/context` via `get_context_usage`; `/stream` + `/verbose` in-memory per-thread flags; `/rename` + `/close` via `edit_forum_topic`/`close_forum_topic`; `/queue` + `/clearqueue` manage the chaining queue; `/retry` re-runs the last prompt
<!-- SECTION:NOTES:END -->

