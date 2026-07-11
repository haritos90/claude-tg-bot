---
id: TASK-81
title: "`allowlist.add(\"-\")` stored a junk entry"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - reliability
dependencies: []
ordinal: 81
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
`allowlist.add("-")` stored a junk entry
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`add()` validates (id all-digits; username `^[A-Za-z0-9_]{4,32}$`) and returns `("invalid", raw)`; `cmd_allow` shows `allow.invalid` instead of a false "granted".
<!-- SECTION:NOTES:END -->

