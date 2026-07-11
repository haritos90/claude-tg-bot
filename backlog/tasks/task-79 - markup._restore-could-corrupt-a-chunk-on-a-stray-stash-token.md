---
id: TASK-79
title: "`markup._restore` could corrupt a chunk on a stray stash token"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - core
dependencies: []
ordinal: 79
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
`markup._restore` could corrupt a chunk on a stray stash token
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Restore is now a bounded loop with an index check (`0 <= idx < len(placeholders)`), returning the literal token otherwise — also makes nested header/table/link placeholders safe.
<!-- SECTION:NOTES:END -->

