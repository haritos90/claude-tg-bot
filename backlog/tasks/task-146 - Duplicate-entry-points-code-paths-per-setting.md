---
id: TASK-146
title: "Duplicate entry points / code paths per setting"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 146
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Duplicate entry points / code paths per setting
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Slash commands route to ONE `sx:` picker via `_send_setting_picker`; the standalone pm:/pe:/lang: pickers are superseded (left live as stale-button handlers).
<!-- SECTION:NOTES:END -->

