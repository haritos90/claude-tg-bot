---
id: TASK-117
title: "Sandbox #104 — perm 6/7 noexec toggle on the workdir"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - isolation
dependencies: []
ordinal: 117
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Sandbox #104 — perm 6/7 noexec toggle on the workdir
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
**Won't do — folded into #119 rationale.** noexec is capability-reduction (counter to the goal of containing, not de-powering, sessions) and weak regardless (interpreters run scripts even from a noexec dir; bwrap 0.8 has no per-bind noexec). Recorded in #119 (component 4) so it isn't re-proposed.
<!-- SECTION:NOTES:END -->

