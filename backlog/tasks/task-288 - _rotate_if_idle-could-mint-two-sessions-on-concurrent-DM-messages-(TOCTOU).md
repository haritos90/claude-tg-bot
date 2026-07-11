---
id: TASK-288
title: "`_rotate_if_idle` could mint two sessions on concurrent DM messages (TOCTOU)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - core
dependencies: []
ordinal: 288
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Rapid back-to-back messages after an idle gap can no longer spawn two duplicate fresh sessions.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`_rotate_if_idle` read `last_active` and then, after an `await`, called `_new_dm_session` with no lock, so two near-simultaneous DM messages from the same user could each pass the idle check and each allocate a fresh session (double rotation). It now serializes the decide-then-rotate on a per-uid `asyncio.Lock` (`rotate_locks`) and re-reads the CURRENT session key + its `last_active` INSIDE the lock, so a concurrent message that already rotated or refreshed the window short-circuits. py_compile + import + ruff + suite 227 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

