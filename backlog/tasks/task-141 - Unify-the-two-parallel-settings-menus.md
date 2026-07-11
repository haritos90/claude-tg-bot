---
id: TASK-141
title: "Unify the two parallel /settings menus"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 141
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Unify the two parallel /settings menus
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Retired the flat `st:` hub; `/settings` opens only the registry `sx:` hub, with Tools / Usage / Users ported on as sub-pages. `on_settings_cb` is now a stale-button shim; the old page builders are dead-in-place (kept for revert).
<!-- SECTION:NOTES:END -->

