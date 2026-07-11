---
id: TASK-175
title: "Global `/workingplate` on/off + native table kept in code replies"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 175
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Owner can switch the Working/Stop plate off to test streaming smoothness; code replies show a real code block AND a native table.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`/workingplate on|off` (owner; tappable keyboard; persisted `working_plate` kv) globally disables the "Working…"/⏹ Stop control plate, wired through `Streamer(controllable=…)` — for A/B testing whether the plate makes generation visibly jump (a mid-stream message arrival re-renders the draft on some clients; same flag already silenced it for `/test`). Also fixed: a code-containing reply now keeps its TABLE as a NATIVE bubble (was wrongly a `<pre>` grid after #172) — `_build_sendables` always extracts native tables; the code still renders as a proper classic block inline.
<!-- SECTION:NOTES:END -->

