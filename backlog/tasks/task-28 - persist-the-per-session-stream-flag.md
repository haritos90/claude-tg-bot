---
id: TASK-28
title: "persist the per-session `/stream` flag"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 28
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
persist the per-session `/stream` flag
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Added a `stream_enabled` `threads` column; `set_stream` persists it and `_get_session` restores it into the record on (re)build — survives restart.
<!-- SECTION:NOTES:END -->

