---
id: TASK-53
title: "session mode bound at creation (chat XOR code)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - engine
dependencies: []
ordinal: 53
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
session mode bound at creation (chat XOR code)
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
A session's type is FIXED at `/new chat|code`; `/mode` is read-only (no mutation — it used to corrupt a chat session into code); mode toggle removed from `/settings`. `allocate_dm_session` takes `mode`.
<!-- SECTION:NOTES:END -->

