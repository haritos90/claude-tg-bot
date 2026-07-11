---
id: TASK-341
title: "Closed-table sort rule contradicts practice (preamble says ascending, table is descending) + out-of-order rows"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - docs
dependencies: []
ordinal: 341
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Closed-table sort rule contradicts practice (preamble says ascending, table is descending) + out-of-order rows
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The "How this file works" Sorting note and the tables had drifted out of sync, and many Closed/Deferred runs were out of order. Re-sorted every table by ID and fixed the out-of-order rows; the Deferred table and its three Details blocks (189/298/310) were unordered too and were sorted to match. (This task briefly set Closed to descending; that convention was later reverted, so every table is now ascending — reconciled in #356.) Pure reorder — no row content changed (verified the non-blank-line multiset was preserved). Docs only. compile + import + ruff + suite 249 green; live restart "Run polling".
<!-- SECTION:NOTES:END -->

