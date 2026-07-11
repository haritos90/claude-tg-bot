---
id: TASK-83
title: "`/language` doesn't refresh the `/` command menu"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 83
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
`/language` doesn't refresh the `/` command menu
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Documented the Telegram limitation (setMyCommands keyed by client `language_code`; no per-user command scope) at both change sites.
<!-- SECTION:NOTES:END -->

