---
id: TASK-161
title: "Access model #151 follow-up (151c/151d)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 161
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Access model #151 follow-up (151c/151d)
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
151c shipped: `sessions._effective_settings` resolves model/effort/permission_mode/max_turns/big_memory through the access model at session-build, so soft-revoke binds at CONSUMPTION (not just the hub). 151d: `max` effort + `full-access` are enforced on the effective values (ungranted→downgraded). Re-modelling the already-working chat/code `level` + per-tool `tool_cap` gates as Access-matrix entries was deemed low-value (no behaviour change) and left as-is. Unit-tested.
<!-- SECTION:NOTES:END -->

