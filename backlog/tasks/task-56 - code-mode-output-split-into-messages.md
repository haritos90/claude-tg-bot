---
id: TASK-56
title: "code-mode output split into messages"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 56
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
code-mode output split into messages
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`streamer.segment_break()` commits each burst of model text (between tool calls) as its own message so progress is visible; the SDK `result` is not re-shown when segmented.
<!-- SECTION:NOTES:END -->

