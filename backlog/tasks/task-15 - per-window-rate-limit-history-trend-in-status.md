---
id: TASK-15
title: "per-window rate-limit history trend in `/status`"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - observability
dependencies: []
ordinal: 15
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
per-window rate-limit history trend in `/status`
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`rate_history` table (append-only, trimmed to 500) written on each rate-signature change; `/status` shows a small `_sparkline` of utilization per window (5h/7d) when ≥2 numeric points exist (utilization is often null far from a limit, so the trend appears only when meaningful).
<!-- SECTION:NOTES:END -->

