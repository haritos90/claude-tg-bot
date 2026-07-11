---
id: TASK-251
title: "Shell `_drive` busy-polls every 40 ms for the whole command lifetime"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - engine
dependencies: []
ordinal: 251
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A long-running shell command no longer wastes CPU polling 25 times a second while it is quiet.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`engine._drive` woke every 40 ms (`asyncio.sleep(0.04)`) for a command's whole lifetime, so a quiet long command (compile, `sleep 300`) spun the event loop ~25×/s for minutes. Added adaptive backoff: poll fast (~40 ms) while output flows and for the first ~1 s of silence, then 0.2 s, then 0.5 s; any new output resets to fast. The `settle` (>=1.5 s) and hard-deadline checks still fire within one slow poll, so await-input detection and timeouts are unaffected. py_compile + import + ruff clean; suite 167 passed (1 pre-existing PIL font failure); live restart "Run polling".
<!-- SECTION:NOTES:END -->

