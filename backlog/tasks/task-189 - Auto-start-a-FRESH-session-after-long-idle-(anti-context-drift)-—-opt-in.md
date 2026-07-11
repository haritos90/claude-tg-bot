---
id: TASK-189
title: "Auto-start a FRESH session after long idle (anti context-drift) — opt-in"
status: Deferred
assignee: []
created_date: '2026-07-04 00:00'
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
**#189 — auto-fresh session after long idle (anti context-drift)** (P3 · S · ux · _follow-up to the reaper #179_)

**What.** After a session has been idle longer than a threshold, the NEXT message
starts a CLEAN session instead of resuming the stale transcript — to avoid
context-DRIFT (a long-ago turn's failed-build / debugging noise being re-ingested into
an unrelated new task). The previous session is NOT destroyed: it stays switchable via
`/sessions` exactly as today, so nothing is lost — only the *active* context resets.

**How it differs from neighbours.** NOT the respawn-latency placeholder (#184); NOT
memory eviction (#179's reaper unloads from RAM but RESUMES the same transcript —
continuous context, the project default). This is the INVERSE default: fresh-on-return instead
of resume-on-return. `/new` already gives the manual clean slate; #189 only makes
"fresh" the AUTOMATIC behaviour after a long gap.

**Setting (delegated).** Expose as a **DELEGATED** option in
`settings_schema.py` (`Access.DELEGATED`, per the model in [[settings-scope-role-matrix]]):
the user SEES it and toggles it, with a per-user default + per-session override — same
shape as `hot_cache_timer` (#166) and `language`. Default OFF, so the global
preserve-and-resume default is unchanged. The owner keeps the usual lever: leave it
DELEGATED so each user opts in, or flip to HIDDEN/forced if a global policy is ever
wanted. Surface it in the `/settings` (`sx:`) hub like the other toggles. The idle
THRESHOLD (e.g. hours) should also be tunable — either a second value or a sensible
fixed default to start; if per-user, it's a second delegated setting.

**Mechanism.** A last-activity timestamp already exists per session (the reaper uses
it). When rebuilding a cold/evicted record in `sessions`, if the effective
`fresh_on_idle` is ON **and** `now − last_activity > threshold`, allocate a NEW session
(or skip `resume`) instead of resuming. Resolve the toggle through `_effective_settings`
like the other delegated flags. Cheap; the only care is parking the old session so it
stays switchable, and telling the user "started a fresh session (previous kept in
/sessions)" so the reset isn't surprising.
<!-- SECTION:NOTES:END -->

