---
id: TASK-258
title: "Schedule polish: double prompt bubble, `cb.message` guard, `last_status` semantics, DST drift"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 258
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Minor schedule UX polish — single setup prompt and clearer internal status semantics; no behavior change for normal use.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Four #188 nits: the no-arg `/schedule` prompt is now ONE bubble (usage + prompt joined) instead of two; `on_schedules_cb` guards `if cb.message is not None` before `edit_text` (None for an old/inaccessible message); documented that `last_status` reflects DISPATCH not turn outcome (`"ok"` = submitted, not "succeeded"); and added a DST caveat to `schedules.next_run_after` (daily/weekly track local wall-clock incl. DST via naive `replace`+`timestamp`; only a target time inside a transition hour can skew ≤1h, tolerated by the 30s sweep). py_compile + import + ruff clean; suite 197 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

