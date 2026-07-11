---
id: TASK-238
title: "Streaming-draft lag on rapid turns: global draft_id + flood→grid fallback"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 238
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Calling something like `/test` several times in a row no longer lags or degrades the table — each turn streams on its own draft and flood is handled by skipping frames, not falling back to the old grid.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Two compounding causes fixed in `streamer.py`: a single global `_DRAFT_ID = 1` shared by every DM turn (a new turn animated from the previous turn's leftover ephemeral draft → cross-turn stutter) → now a UNIQUE per-`Streamer` id (`_next_draft_id`); and the rich-draft `except` dropping to the `md_to_html` `<pre>` grid on flood (`TelegramRetryAfter` on rapid turns degraded the table + slept the retry) → now backs off (`_draft_retry_after`) and SKIPS the frame instead of falling to the grid. py_compile + ruff + suite clean; live restart "Run polling".
<!-- SECTION:NOTES:END -->

