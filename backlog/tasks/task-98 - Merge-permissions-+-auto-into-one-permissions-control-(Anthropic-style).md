---
id: TASK-98
title: "Merge `/permissions` + `/auto` into one permissions control (Anthropic-style)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 98
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
`/permissions` is the single approval control (ask/auto-edits/plan/full-access); `/auto` is just a shortcut.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
One control, four policies — `ask · auto-edits · plan · full-access` — the SDK `bypassPermissions` mode renamed from `yolo` everywhere (`PERM_NAME_TO_MODE`, the `/settings` perm sub-page, `cmd_permissions`, i18n `perm.*`, `permissions.py` comments). `full-access` stays owner-only. `/auto on|off` is reframed as a thin shortcut for `/permissions full-access|ask` (its help now says so). One `/settings` row (the perm sub-page). i18n en/ru parity green.
<!-- SECTION:NOTES:END -->

