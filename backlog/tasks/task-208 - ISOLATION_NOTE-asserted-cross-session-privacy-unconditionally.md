---
id: TASK-208
title: "ISOLATION_NOTE asserted cross-session privacy unconditionally"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - isolation
dependencies: []
ordinal: 208
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The code agent no longer overstates isolation: it describes filesystem/network confinement as conditional and asserts only the always-true private per-session directory.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`engine.ISOLATION_NOTE` (#205), appended to every code session's system prompt, opened with an unconditional "an isolated, per-session sandbox … you cannot see or reach another session's files" — but that enforcement only holds when the sandbox layers (#104/#119/#180) are on. Reworded so only the always-true per-session SEPARATE directory (#181) is stated outright; filesystem confinement is now hedged ("may be") like the network clause. Old string kept commented.
<!-- SECTION:NOTES:END -->

