---
id: TASK-106
title: "Waiting/Stop control animated braille dots"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 106
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The "working…" control no longer animates dots — just a static label + Stop.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Removed the spinner animation from `streamer._delayed_control`: it now posts a STATIC "⏳ Working…" + ⏹ Stop message; the rotating-glyph loop and `_SPIN_FRAMES`/`_SPIN_INTERVAL` are deleted (owner: at Telegram's ~1 edit/sec cap the dots read as flicker, not motion). Teardown (`_remove_control`/`cancel`) unchanged.
<!-- SECTION:NOTES:END -->

