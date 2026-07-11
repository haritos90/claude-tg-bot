---
id: TASK-30
title: "tool-approval taps were not owner-restricted"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - security
dependencies: []
ordinal: 30
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
tool-approval taps were not owner-restricted
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`on_perm_callback` ignores non-owner taps ("Only the owner can approve tools."); only the owner authorizes Bash/Write/Edit in code mode.
<!-- SECTION:NOTES:END -->

