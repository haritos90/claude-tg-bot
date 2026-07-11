---
id: TASK-337
title: "New `test_db.py` cases leaked temp DBs/dirs instead of using `tmp_path`"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - tests
dependencies: []
ordinal: 337
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
New `test_db.py` cases leaked temp DBs/dirs instead of using `tmp_path`
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`test_usage_survives_session_delete`, `test_allocate_names_workdir_by_ulid`, `test_migrate_backfills_public_ulid_db_only_and_idempotent` and `test_migrate_workdirs_to_ulid_renames_reencodes_rekeys_idempotent` created scratch paths with `tempfile.mktemp(suffix=".db")` / `tempfile.mkdtemp()` and never cleaned them — the same leak #292 migrated older tests away from. All four now take the pytest `tmp_path` fixture (`str(tmp_path/"x.db")` / `tmp_path/"base"`; pytest auto-cleans). compile + import + ruff + suite 249 green.
<!-- SECTION:NOTES:END -->

