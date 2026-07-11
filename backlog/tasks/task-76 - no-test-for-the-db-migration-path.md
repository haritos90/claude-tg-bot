---
id: TASK-76
title: "no test for the db migration path"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - tests
dependencies: []
ordinal: 76
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
no test for the db migration path
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Added `test_forward_migration_adds_columns_with_defaults`: builds the original minimal `threads` schema, calls `init_db`, asserts the new columns default correctly.
<!-- SECTION:NOTES:END -->

