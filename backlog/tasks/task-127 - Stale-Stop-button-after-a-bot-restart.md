---
id: TASK-127
title: "Stale Stop button after a bot restart"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - reliability
dependencies: []
ordinal: 127
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Old Stop buttons clear on tap.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
A restart orphans the per-turn control message; tapping its Stop (no live turn) now deletes the dead message instead of lingering forever.
<!-- SECTION:NOTES:END -->

