---
id: TASK-93
title: "smooth streaming in code mode + live code-block split"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 93
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Code mode now streams smoothly and breaks each finished code block into its own copyable message live, as it is generated.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Live code-block splitting: `markup.split_closed_blocks` detects a fully-closed fenced block (closing fence + newline) mid-stream; `sessions._split_live_blocks` (after each `update()` in code mode) commits the prose+block prefix as its own copyable message(s) via the new `streamer.flush_segment()` and keeps streaming the tail — a finished snippet is copyable immediately and the DM draft stays smooth (no completed block whose moving close-tag snaps the animation). `segment_break` refactored onto a shared `_begin_next_segment`. An adversarial multi-agent audit then caught + fixed a double-post (a cumulative `text_full` snapshot resurrecting an already-flushed block → `text_full` is now ignored once segmented, matching the result-branch guard) and an O(n²) re-scan on a long unclosed block (cheap fence-count gate). Tests: 7 `split_closed_blocks` units + 2 `_run_one` integration (double-post regression); 47 green; live (Run polling).
<!-- SECTION:NOTES:END -->

