---
id: TASK-29
title: "changing /mode·/model·/cwd·/permissions mid-run broke the in-flight turn"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - reliability
dependencies: []
ordinal: 29
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
changing /mode·/model·/cwd·/permissions mid-run broke the in-flight turn
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`_get_session` never aclose()s/rebuilds while a worker is busy — it returns the live session and defers the rebuild to the next idle message; `on_mode_or_model_or_cwd_change` defers + returns a flag so the handler appends "(applies after the current run finishes)". Functionally tested.
<!-- SECTION:NOTES:END -->

