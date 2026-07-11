---
id: TASK-101
title: "Arg-capture for ALL arg-commands + document the rule in CLAUDE.md"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 101
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Commands that need a value now ask for it (with /cancel) instead of erroring.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Free-text arg-commands now PROMPT + capture the next message when invoked with no arg (with a `/cancel` escape) instead of erroring: `/allow` + `/deny` join `/new`, `/rename` (incl. the #95 per-session `rename:<key>`), and `/sessions` Search. Built on the existing module `pending` dict + `_run_pending`; `_do_allow`/`_do_deny` extracted so the direct-arg and captured paths share logic (both owner-gated). Fixed-CHOICE commands (`/model`, `/effort`, `/permissions`, `/usage`, `/memory`, `/language`) keep pickers / `/settings` sub-pages — the better UX than typing. The convention (+ the picker exception) is documented in CLAUDE.md.
<!-- SECTION:NOTES:END -->

