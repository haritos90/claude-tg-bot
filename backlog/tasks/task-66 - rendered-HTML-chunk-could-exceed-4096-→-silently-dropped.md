---
id: TASK-66
title: "rendered HTML chunk could exceed 4096 → silently dropped"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - reliability
dependencies: []
ordinal: 66
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
rendered HTML chunk could exceed 4096 → silently dropped
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Added `markup.render_within_limit` (+ `HARD_LIMIT=4096`): renders each raw chunk and re-splits the RAW source when the HTML overflows (never splitting rendered HTML), with a hard-cut floor; `streamer._render_chunks`/`_render_message_chunks` use it, footer gate moved to `HARD_LIMIT`. Test added.
<!-- SECTION:NOTES:END -->

