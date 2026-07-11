---
id: TASK-23
title: "\"Pro\" command layer — safe subset"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 23
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
"Pro" command layer — safe subset
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Shipped the SDK-clean subset (per a 2026-06-14 SDK introspection): `/effort` (`effort`), `/maxturns` (`max_turns`), `/dirs` (`add_dirs`, code, sandboxed for non-owners), `/fork` (`resume` + one-shot `fork_session`, branch id persisted then flag cleared). Persisted as `threads` columns; a change rebuilds the session (same busy-guard as `/model`). Remainder (`/rewind`, `/resume`, `/mcp`, `/budget`, `/continue`) deferred — see Deferred #62.
<!-- SECTION:NOTES:END -->

