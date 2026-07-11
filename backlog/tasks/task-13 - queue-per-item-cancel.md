---
id: TASK-13
title: "`/queue` per-item cancel"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 13
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
`/queue` per-item cancel
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Queue items carry a per-thread monotonic `qid`; `/queue` lists each pending prompt with a ✖ Cancel button (+ Clear all), `on_queue_cb` → `sessions.cancel_queued(thread_id, qid)` rebuilds the queue minus that id under `rec.lock` (order preserved). Tested.
<!-- SECTION:NOTES:END -->

