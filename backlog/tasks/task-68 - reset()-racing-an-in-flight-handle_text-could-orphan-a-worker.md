---
id: TASK-68
title: "`reset()` racing an in-flight `handle_text` could orphan a worker"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - reliability
dependencies: []
ordinal: 68
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Fixed a rare race where `/reset` during an in-flight message could spawn a duplicate, untracked worker.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`handle_text` now resolves the record and takes its lock inside a retry loop that re-checks `self._records.get(thread_id) is rec`; if `reset()` popped the record while we blocked on the lock, it retries with the fresh record (the prompt runs on a live record, never lost) instead of building a session + worker on the orphaned one — closing the two-workers-per-thread race. Verified: py_compile + import + 45 tests + live restart.
<!-- SECTION:NOTES:END -->

