---
id: TASK-99
title: "`/model` + `/effort` offer an interactive picker"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 99
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
`/model` and `/effort` with no argument show a tap-to-pick menu.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
No-arg `/model` and `/effort` now pop an inline button picker (current marked ✓) instead of printing the value — `/model` → opus/sonnet/haiku; `/effort` → low/medium/high/xhigh/max/default. Taps hit new `pm:`/`pe:` callbacks (`on_model_pick`/`on_effort_pick`) that set the value, rebuild the session, and edit the message to confirm.
<!-- SECTION:NOTES:END -->

