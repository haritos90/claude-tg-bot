---
id: TASK-216
title: "/level errored on a bad/missing level instead of offering a picker"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 216
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
/level pops up chat/code buttons when you don't type the level, instead of showing an error.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`/level @user` with no/invalid level now shows an inline chat|code PICKER (new owner-only `setlvl:` callback + `level.pick*` strings) instead of the `level.usage` error — matching the convention (fixed-choice → picker). The user part stays free-text; only the level became a tap. The full `/level @user chat|code` form and the no-arg capture flow still work. py_compile + ruff + pytest (151).
<!-- SECTION:NOTES:END -->

