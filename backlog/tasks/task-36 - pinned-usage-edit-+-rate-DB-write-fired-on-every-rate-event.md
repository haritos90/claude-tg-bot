---
id: TASK-36
title: "pinned-usage edit + rate DB write fired on every rate event"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - observability
dependencies: []
ordinal: 36
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
pinned-usage edit + rate DB write fired on every rate event
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`_run_one` persists + edits only when `_rate_signature()` changes, skipping repeated identical rate events.
<!-- SECTION:NOTES:END -->

