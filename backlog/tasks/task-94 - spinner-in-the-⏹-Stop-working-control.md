---
id: TASK-94
title: "spinner in the ⏹ Stop / \"working\" control"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 94
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The ⏹ Stop / "working…" control now shows a live spinner while a turn runs.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`streamer._delayed_control` animates a braille spinner (`_SPIN_FRAMES`, ~1.2 s cadence, just above Telegram's ~1 edit/sec cap) next to the "working…" label, keeping the ⏹ Stop button on every edit; the loop re-checks the streaming flags under the lock and is torn down by `_remove_control()`/`cancel()` (no orphaned task). Audit follow-up: the control message id is registered + re-checked under the lock right after the send, so a turn ending mid-send can't orphan it. Live.
<!-- SECTION:NOTES:END -->

