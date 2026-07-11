---
id: TASK-248
title: "PTY master fd leaked when `PersistentShell` spawn fails"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - engine
dependencies: []
ordinal: 248
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A failed shell start no longer leaks a file descriptor.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`engine._start_shell` opened a PTY (`os.openpty()`) and the `finally` closed only `slave`; if `create_subprocess_exec` raised, `master` leaked — one fd per failed attempt until exhaustion. Added an `except BaseException` that closes `master` before re-raising (the `finally` still closes `slave`). py_compile + import + ruff clean; suite 167 passed (1 pre-existing PIL font failure); live restart "Run polling".
<!-- SECTION:NOTES:END -->

