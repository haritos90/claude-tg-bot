---
id: TASK-166
title: "Live ticking hot-cache countdown"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 166
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The warm-cache reminder now counts down live and clears itself when the cache cools or you reply.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The warm-cache note now ticks DOWN once a minute (`_hot_cache_tick`: ~5 → 0, then ❄️ cold), and is cancelled + removed on the next turn (the window reset). Opt-in (the `hot_cache_timer` toggle is delegated, default off), so the per-minute edits only run for users who enabled it.
<!-- SECTION:NOTES:END -->

