---
id: TASK-204
title: "Permission prompt showed the full absolute file path"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 204
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Tool-approval prompts show a short path relative to the working directory instead of the full absolute path.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The Allow/Deny prompt previewed the raw tool input, e.g. `/var/lib/.../<sid>/work/readme.md`. `permissions._preview_input` now relativizes path-like fields to the session workdir (→ `readme.md`) via the new `_rel_to_cwd`, with `cwd` plumbed through `make_callback` (`sessions.py`). A path OUTSIDE the workdir keeps its absolute form on purpose — a tool leaving the sandbox should stand out. +4 tests. Deployed.
<!-- SECTION:NOTES:END -->

