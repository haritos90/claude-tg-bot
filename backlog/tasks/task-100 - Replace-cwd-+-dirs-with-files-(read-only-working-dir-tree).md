---
id: TASK-100
title: "Replace `/cwd` + `/dirs` with `/files` (read-only working-dir tree)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 100
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
`/files` shows the working-dir tree; `/cwd`+`/dirs` retired (working dir is fixed per session).
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Dropped `/cwd` + `/dirs` (a session's working dir is fixed at `BASE_WORKDIR/<key>`) and added `/files` — a read-only, depth/entry-capped tree (`_build_tree`) of the session's working dir, sent inline or as a `files.txt` document when large. Removed both from the command menu + help text; the `set_cwd`/`set_add_dirs` db plumbing is left intact (unused).
<!-- SECTION:NOTES:END -->

