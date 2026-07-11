---
id: TASK-232
title: "test_sandbox_uid_collisions_scan regresses under the #231 uid==0 guard"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - core
dependencies: []
ordinal: 232
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
None — test-only fix; no runtime change. The sandbox uid-collision doctor's test now passes on a root host.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The #231 root-exclusion (`if uid == 0: continue` in `_uid_collisions`) made the scan return `{}` for root-owned work dirs, but `test_sandbox_uid_collisions_scan` still asserted `{os.getuid(): [...]}` — failing on a root host (this VPS runs as uid 0), where the test's own dirs are root-owned. Updated `tests/test_db.py`: the scan assertion now branches on `os.getuid()` (root host → expect `{}` since root is excluded; non-root → expect the collision), and `test_uid_collisions_pure` gained explicit root-exclusion cases (`{"a": 0, "b": 0}` → `{}`; a root pair plus a real non-root collision returns only the non-root one). Behavior was already correct; only the test lagged. Old assertion kept commented with the #232 ref. py_compile + ruff clean; `pytest tests/test_db.py` 14 passed; full suite 154 passed (one pre-existing unrelated PIL font-load failure in test_markup).
<!-- SECTION:NOTES:END -->

