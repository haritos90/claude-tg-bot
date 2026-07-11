---
id: TASK-364
title: 'Sessions list: order by last activity, not creation time'
status: Done
assignee: []
created_date: '2026-07-11 16:40'
updated_date: '2026-07-11 16:43'
labels: []
dependencies: []
ordinal: 2362
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The /sessions list is ordered by creation time, so continuing to write in an existing session does not float it to the top. It should be ordered by most-recent activity (last message), with a fresh empty session still sorting sensibly by its creation time.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
FIXED. browse_threads now orders by 'favorite DESC, max(COALESCE(last_active,0), COALESCE(created_at,0)) DESC' (app/storage/db.py). last_active was already stamped at each turn end; the sort just ignored it. Fresh/never-completed sessions fall back to created_at. Regression test: test_browse_threads_orders_by_last_activity_not_creation (tests/test_db.py) — an older but recently-active session floats above a newer never-active one. Full suite 273 green, ruff clean, service restarted (Run polling).
<!-- SECTION:NOTES:END -->
