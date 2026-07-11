---
id: TASK-47
title: "`/history` (export transcript) + `/recap` (last exchange)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 47
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
`/history` (export transcript) + `/recap` (last exchange)
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Added a `messages` table; `sessions._run_one` logs the user prompt + assistant reply each turn (cleared by `/reset` and session delete). `/recap` shows the last exchange; `/history` exports the full transcript as a `.md` document.
<!-- SECTION:NOTES:END -->

