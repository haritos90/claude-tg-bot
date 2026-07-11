---
id: TASK-49
title: "inline ⏹ Stop button"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 49
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
inline ⏹ Stop button
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Worked around the draft/`reply_markup` limitation with a SEPARATE control message: the streamer posts a ⏹ Stop message only once a turn outlasts `_CONTROL_DELAY` (3s, so quick replies don't flicker) and removes it when the turn ends; `on_stop_cb` → `sessions.stop` (graceful).
<!-- SECTION:NOTES:END -->

