---
id: TASK-12
title: "unit tests for `markup` split/escape + the `db` layer"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - tests
dependencies: []
ordinal: 12
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
unit tests for `markup` split/escape + the `db` layer
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Added `tests/` (18 tests, pure `pytest` — async tests wrap `asyncio.run`, no pytest-asyncio needed) covering escape, split round-trip, fence repair, `segment_blocks`, LaTeX conversion + prose/code protection, and the db layer (allocate/get, `/stream` persist, message log, rate history, pro-options, scoped delete). `requirements-dev.txt` + a `pytest -q` CI step + root `conftest.py`.
<!-- SECTION:NOTES:END -->

