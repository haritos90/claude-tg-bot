---
id: TASK-350
title: "First-token-timeout watchdog tidy-ups (un-`aclose`d async-gen, per-`__anext__` comment, dead `error_detail`)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - engine
dependencies: []
ordinal: 350
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
First-token-timeout watchdog tidy-ups (un-`aclose`d async-gen, per-`__anext__` comment, dead `error_detail`)
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
On the `asyncio.TimeoutError` path the abandoned `receive_response()` async-generator is now `aclose()`d (errors suppressed) before `_drop_client()`, so it is not left to the GC async-gen finalizer; the misleading "Only the wait for the FIRST event is bounded" comment now states each pre-`_progressed` `__anext__` is bounded; and the dead `error_detail` was dropped (the localized `err.service_unavailable` carries no `{detail}` and the warning above already logs the stall). compile + import + ruff + suite 258 green; live restart "Run polling".
<!-- SECTION:NOTES:END -->

