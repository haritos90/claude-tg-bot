---
id: TASK-110
title: "Retire the streaming on/off setting"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 110
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Removed the redundant streaming toggle (native streaming is always on).
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`/stream` handler, the `/settings` streaming row, the `_settings_apply` `tog/stream` branch, and the `/status` streaming line are all COMMENTED OUT (not deleted) — DM uses native Telegram streaming (always on), so the toggle was redundant. The plumbing (`sessions.set_stream`, the `stream_enabled` column, `rec.stream_enabled`) is kept intact so streaming/speed control can be restored by uncommenting.
<!-- SECTION:NOTES:END -->

