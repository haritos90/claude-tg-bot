---
id: TASK-359
title: "Idle auto-rotation window 30 min -> 45 min"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 359
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A session now waits 45 minutes of inactivity (was 30) before auto-rotating to a fresh context.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Raised the #261 idle->fresh-session default `idle_reset_sec` from 1800 (30 min) to 2700 (45 min) — both the dataclass default and the `IDLE_RESET_SEC` env fallback in `app/config.py`. A quiet session now rotates to a fresh context after 45 min of no activity instead of 30; still `0`=off, env-overridable via `IDLE_RESET_SEC`, and per-user-overridable (`idle_reset_min`). compile + import + ruff + suite 266 green; live restart "Run polling".
<!-- SECTION:NOTES:END -->

