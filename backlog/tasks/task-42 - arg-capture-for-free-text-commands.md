---
id: TASK-42
title: "arg-capture for free-text commands"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 42
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
arg-capture for free-text commands
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`/new` and `/rename` with no argument PROMPT and capture the user's NEXT message as the argument (Telegram sends a picked command immediately); `/cancel` aborts.
<!-- SECTION:NOTES:END -->

