---
id: TASK-55
title: "code-mode auto-approve actually works"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - security
dependencies: []
ordinal: 55
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
code-mode auto-approve actually works
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The gate (`permissions.make_callback`) now enforces `permission_mode`: `bypassPermissions` (`/auto on`, owner-only) auto-allows everything, `acceptEdits` auto-allows file edits. Before, `can_use_tool` prompted regardless of the SDK mode.
<!-- SECTION:NOTES:END -->

