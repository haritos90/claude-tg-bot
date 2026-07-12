---
id: TASK-189
title: Auto-start a FRESH session after long idle (anti context-drift) — opt-in
status: Done
assignee: []
created_date: '2026-07-04 00:00'
updated_date: '2026-07-11 20:05'
labels:
  - ux
dependencies: []
ordinal: 189
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
_Priority P3 · Effort S · deferred._

NOT about respawn latency (that's #184) and NOT "context isn't saved": the idea is to start CLEAN on purpose after a long gap, to avoid context-DRIFT — dragging a morning's failed-build / debugging noise into an afternoon's unrelated request via resume. The reaper (#179) instead RESUMES the same transcript (continuous context — the project default); old sessions stay retrievable via `/sessions`. So this is the INVERSE default: "after a long gap the next ask is probably a new task → start fresh, keep the old one switchable". Marginal here — `/new` already gives a manual clean slate and the project deliberately favours preserve-and-resume; the only delta is making fresh the AUTOMATIC default after long idle (opt-in, default OFF). Cheap (a last-activity timestamp check when rebuilding an evicted record). Kept as a user-configurable DELEGATED setting (`settings_schema.py`): user sees + toggles it, own default + per-session override (like `hot_cache_timer`/`language`), default OFF; owner can leave it delegated so each user opts in. Full design in Details below.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Done - superseded by #261/#266/#329 (window tuned in #359). The anti-context-drift "fresh session after long idle" behavior is implemented: sessions._idle_reset / idle_reset_seconds() start a NEW session (the old one is preserved and stays switchable via /sessions) once now - last_active exceeds the idle-reset window; resolved per-USER (#329) and applied in _session_key_for_turn (#266). Window default is 45 min (#359); a per-user override lives in idle_reset_min (<=0 disables). Shipped as the DEFAULT behavior with a per-user off switch rather than this task's proposed opt-in / default-OFF delegated toggle - which makes this task obsolete.
<!-- SECTION:NOTES:END -->
