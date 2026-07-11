---
id: TASK-289
title: "Detached-shell lifecycle edge cases"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - reliability
dependencies: []
ordinal: 289
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A running shell command now survives an idle in-place rotation, and the shell re-attach is race-safe.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Three consistency fixes in the #274 detach/re-attach shell lifecycle. (1) `rotate_in_place` now preserves a live jailed shell (detach + stash in `_detached_shells`) before `aclose`, like the reaper path, so a running command + cd/env survive an in-place idle rotation instead of being killed. (2) `shell_refresh` now holds `rec.lock` across the session-snapshot read + `shell_peek` so a concurrent rebuild can't swap `rec.session` mid-await. (3) added a comment confirming the code→chat rebuild deliberately carries the live shell (preserves cd/env for a switch back; still reaped on aclose/TTL/delete — no leak). py_compile + import + ruff + suite 227 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

