---
id: TASK-356
title: "Closed `#338`/`#341` resolutions claimed a descending sort; the table is ascending"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - docs
dependencies: []
ordinal: 356
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Closed `#338`/`#341` resolutions claimed a descending sort; the table is ascending
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The Sorting note keeps every table ascending and the Closed table is ascending throughout (verified 1→353), but two leftover resolutions still claimed a descending Closed order: `#338`(5) ("327/328/329 → 329/328/327 strict descending") and `#341` ("re-sorted the Closed table strictly descending", note amended to "Closed descending"). Reconciled both to the ascending reality — dropped the now-inaccurate descending claims and noted the interim descending convention was reverted — while preserving each task's surviving factual outcome (the re-sort + the out-of-order fixes). Docs only. compile + import + ruff + suite 264 green; live restart "Run polling".
<!-- SECTION:NOTES:END -->

