---
id: TASK-223
title: "`/permissions` offered the defunct `ask` floor and gated `full-access` to the owner"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 223
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Code sessions default to auto-edits with no "ask" option; any code user can switch to plan or full-access (run everything unattended) — the sandbox is the safety boundary.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The code permission picker still offered `ask` (per-tool prompting) and hid `full-access` (`bypassPermissions`) from non-owners. With #119/#212 making the jail the hard boundary, `ask`/`default` was removed from the choices (`_PERM_CHOICES` + `PERM_NAME_TO_MODE`, old kept commented) so `auto-edits` is the floor, and `full-access` was un-gated for all code users (picker hide, apply-gate, and `/permissions` command gate all commented out) — the sandbox confines it to the user's own session and the user opts into the risk. `/auto off` now lands on `acceptEdits` (was `default`). Help/label copy (`perm.help.full-access`, commands.py, menu.md) updated; no jargon ("full-access", not "yolo"). py_compile + pytest (151) + ruff.
<!-- SECTION:NOTES:END -->

