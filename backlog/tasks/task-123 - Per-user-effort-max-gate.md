---
id: TASK-123
title: "Per-user effort-`max` gate"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - security
dependencies: []
ordinal: 123
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Only granted users can pick max effort.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`allowlist` `allow_max_effort` (owner always allowed); `/effort` picker hides `max` and both the picker + typed path reject it for un-granted users — stops a guest burning the shared subscription with max thinking.
<!-- SECTION:NOTES:END -->

