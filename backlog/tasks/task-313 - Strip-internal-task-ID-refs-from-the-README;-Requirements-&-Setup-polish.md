---
id: TASK-313
title: "Strip internal task-ID refs from the README; Requirements & Setup polish"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - docs
dependencies: []
ordinal: 313
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The README reads cleaner for newcomers — no internal task numbers, an explicit "no Premium required" note, and clearer first-run setup (how to find your own id).
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Removed every `#NNN` task reference from `README.md` — the internal tracker is noise to a reader; the `#NNN` convention now lives only in code comments and TODO.md rows (rule recorded in the contributor overlay). Also added "no Telegram Premium needed" to the Requirements lead line, dropped the now-redundant Premium note from Setup step 1, and documented how to find your numeric `OWNER_ID` (via @userinfobot, or `/whoami` once running) where it is configured. compile + import + ruff + suite 230 clean.
<!-- SECTION:NOTES:END -->

