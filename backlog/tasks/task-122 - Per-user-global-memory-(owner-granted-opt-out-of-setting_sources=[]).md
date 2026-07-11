---
id: TASK-122
title: "Per-user global memory (owner-granted opt-out of `setting_sources=[]`)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - isolation
dependencies: []
ordinal: 122
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Give a user (or yourself) global memory.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`allowlist` `global_memory` (+ owner via `owner_prefs`); `sessions._resolve_global_memory` resolves it for the session owner (`created_by`) and `engine` flips `setting_sources` to `["user"]` (loads `~/.claude` + CLAUDE.md/memory). OFF by default; applies on the next rebuild; the card warns it exposes the owner's `~/.claude`.
<!-- SECTION:NOTES:END -->

