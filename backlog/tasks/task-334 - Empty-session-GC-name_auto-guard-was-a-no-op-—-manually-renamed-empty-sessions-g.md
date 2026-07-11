---
id: TASK-334
title: "Empty-session GC `name_auto` guard was a no-op — manually-renamed empty sessions got archived"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - reliability
dependencies: []
ordinal: 334
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A session you renamed but haven't used yet is no longer silently cleaned up — only genuinely empty, never-named sessions get auto-collected.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`_gc_untitled_empties` (handlers) spares manually-renamed sessions via `r.get("name_auto", True)`, but `browse_threads` SELECTed `COALESCE(name_auto,1)` yet dropped it from the returned page dict — so the guard always saw the default `True` and never fired: a renamed but zero-request, non-favorite, non-current session was silently reset + archived on opening `/sessions` or tapping New chat (only the 0-requests check still protected anything). Fix: surface `"name_auto": bool(r["name_auto"])` in the `browse_threads` page dict so the guard actually sees it. +regression test (`browse_threads` returns `name_auto` reflecting a manual rename; the GC candidate predicate now excludes a renamed empty session). compile + import + ruff + suite 249 green; live restart "Run polling".
<!-- SECTION:NOTES:END -->

