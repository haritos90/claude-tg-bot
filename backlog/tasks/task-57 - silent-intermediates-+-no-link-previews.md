---
id: TASK-57
title: "silent intermediates + no link previews"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 57
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
silent intermediates + no link previews
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Streaming/segment messages are silent (`disable_notification`); only the final answer pings; permission prompts still notify. All sends/edits pass `_NO_PREVIEW` (links never expand).
<!-- SECTION:NOTES:END -->

