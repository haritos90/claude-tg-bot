---
id: TASK-214
title: "Retired flat-hub dead code lingered (~283 lines)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - core
dependencies: []
ordinal: 214
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Retired flat-hub dead code lingered (~283 lines)
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Deleted the `pm:`/`pe:` callback handlers (`on_model_pick`/`on_effort_pick`, emitted by no keyboard — superseded by the unified `sx:` picker) and the RETIRED-#141 builders `_gather_vals`, `_settings_apply`, `_settings_text`, `_onoff_label`, `_settings_keyboard` (nothing live called them). Kept the `st:` stale-button shim and `_mark` (both live) and updated their docstring + the /stream restore comment to note the removal. py_compile + #139 registry assertion + ruff + pytest (151).
<!-- SECTION:NOTES:END -->

