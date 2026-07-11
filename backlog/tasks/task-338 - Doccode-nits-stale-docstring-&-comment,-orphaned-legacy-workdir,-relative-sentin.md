---
id: TASK-338
title: "Doc/code nits: stale docstring & comment, orphaned legacy workdir, relative sentinel default, Closed-table order"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - core
dependencies: []
ordinal: 338
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Doc/code nits: stale docstring & comment, orphaned legacy workdir, relative sentinel default, Closed-table order
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Grouped nits. (1) `sessions._default_cwd` docstring said the dir is named by `session_sid` — refreshed to the PUBLIC ULID via `db.session_pubid` (#332). (2) The concurrency invariant comment was refreshed to frame the rename (#179's `_turn_sem` → #326's `FairAdmission` `_turn_gate`). (3) `migrate_workdirs_to_ulid` left the orphaned legacy `<6hex>/` dir when both it and the ULID dir exist — now removes it ONLY if empty (`os.rmdir`; a non-empty legacy dir is left in place + warned, never silently deleted). (4) `_MAINTENANCE_SENTINEL` defaulted to the relative `"MAINTENANCE"` (resolved against cwd) — now defaults to an ABSOLUTE path under `REPO_ROOT` (`/opt/claude-tg-bot/MAINTENANCE` here, unchanged on this deployment but cwd-robust); still overridable via `MAINTENANCE_FILE`, verified absolute from a foreign cwd. (5) Adjusted the Closed-table row order for 327/328/329; the table is kept ascending by ID per the Sorting note (an interim descending convention here was later reverted — reconciled in #356). compile + import + ruff + suite 249 green; live restart "Run polling".
<!-- SECTION:NOTES:END -->

