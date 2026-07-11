---
id: TASK-91
title: "streaming + DM drafts were two overlapping settings"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 91
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
streaming + DM drafts were two overlapping settings
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Merged into the single per-session Streaming toggle; removed the global `draft_streaming` flag, `set_draft_streaming`, and the `/settings` "DM drafts" row. In DM, streaming = drafts; the write-head is documented as dormant.
<!-- SECTION:NOTES:END -->

