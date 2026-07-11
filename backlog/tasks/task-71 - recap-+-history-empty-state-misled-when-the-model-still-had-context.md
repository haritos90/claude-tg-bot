---
id: TASK-71
title: "`/recap` + `/history` empty-state misled when the model still had context"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 71
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
`/recap` + `/history` empty-state misled when the model still had context
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The empty branch now checks for a persisted `code_session_id`/`chat_session_id` and shows `recap.empty_has_context` ("older/resumed context isn't in the transcript; new messages are saved from now on") instead of "no conversation logged." en+ru added.
<!-- SECTION:NOTES:END -->

