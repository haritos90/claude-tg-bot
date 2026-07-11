---
id: TASK-132
title: "Settings as the single hub + command-menu declutter + transcript export in /sessions"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 132
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
One settings hub; fewer menu items; transcript export in the sessions menu.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`/settings` moved to menu position 4 (between `/sessions` and `/rename`); pure-config commands (model/effort/tools/memory/permissions/usage/language) dropped from the `/` menu (still typeable) — navigate from `/settings`; added a `👥 Users` hub row (owner) that opens the per-user list in-place with `➕ Add user` + `◂ Settings`; added `📄 Transcript` export to the `/sessions` options menu; chat settings header no longer shows the inert Permissions line (#121 audit #6).
<!-- SECTION:NOTES:END -->

