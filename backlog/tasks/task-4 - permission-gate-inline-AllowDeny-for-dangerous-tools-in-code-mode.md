---
id: TASK-4
title: "permission gate: inline Allow/Deny for dangerous tools in code mode"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - security
dependencies: []
ordinal: 4
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
permission gate: inline Allow/Deny for dangerous tools in code mode
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Delivered: `permissions.PermissionGate` inline Allow/Deny; `SAFE_TOOLS` auto-allowed; dangerous tools gated via `can_use_tool`. (Owner-only approval split out as #30.)
<!-- SECTION:NOTES:END -->

