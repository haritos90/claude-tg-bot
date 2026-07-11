---
id: TASK-31
title: "code-mode blast radius for non-owners"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - security
dependencies: []
ordinal: 31
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
code-mode blast radius for non-owners
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`/cwd` sandboxed under `BASE_WORKDIR` for non-owners (absolute paths + `../` escapes rejected via `relative_to`); `/permissions yolo` is owner-only. Owner unrestricted.
<!-- SECTION:NOTES:END -->

