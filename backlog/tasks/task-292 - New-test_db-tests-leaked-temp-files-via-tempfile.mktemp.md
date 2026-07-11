---
id: TASK-292
title: "New `test_db` tests leaked temp files via `tempfile.mktemp`"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - tests
dependencies: []
ordinal: 292
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
New `test_db` tests leaked temp files via `tempfile.mktemp`
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`test_session_name_auto_then_manual_pin` and `test_last_active_and_idle_rotation_keeps_messages` used `tempfile.mktemp(suffix=".db")`, which is deprecated and left `.db` files in `$TMPDIR`. Both now take the `tmp_path` pytest fixture and init the db at `tmp_path / "*.db"` (pytest auto-cleans), matching the sibling migration test. py_compile + suite 227 passed.
<!-- SECTION:NOTES:END -->

