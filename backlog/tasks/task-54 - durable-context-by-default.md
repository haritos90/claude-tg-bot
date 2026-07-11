---
id: TASK-54
title: "durable context by default"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - engine
dependencies: []
ordinal: 54
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
durable context by default
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Chat sessions always resume `chat_session_id` across restart/`/stop` (decoupled from `big_memory`, which is now only the 1M-window toggle). Context confirmed to return after a restart.
<!-- SECTION:NOTES:END -->

