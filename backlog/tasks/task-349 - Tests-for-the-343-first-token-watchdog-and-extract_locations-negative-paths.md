---
id: TASK-349
title: "Tests for the #343 first-token watchdog and `extract_locations` negative paths"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - tests
dependencies: []
ordinal: 349
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Tests for the #343 first-token watchdog and `extract_locations` negative paths
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Added a `test_engine` case driving a stalled stream (no first event within a monkeypatched 0.05 s window) → asserts exactly one `err.service_unavailable` event, the client dropped, and the resume `session_id` preserved. Extended `test_extract_locations` with the missing negative paths (missing a coordinate, `lon` out of range, title-without-address, dropped `name`/`addr` aliases, the venue length cap, and a block nested in a demo fence). Aligned the `test_sessions` `_capture` to the 3-tuple `(thread_id, name, manual)` so the `thread_id` assertion is no longer dropped. compile + import + ruff + suite 258 green; live restart "Run polling".
<!-- SECTION:NOTES:END -->

