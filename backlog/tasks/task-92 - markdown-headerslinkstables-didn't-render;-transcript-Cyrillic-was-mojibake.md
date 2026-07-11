---
id: TASK-92
title: "markdown headers/links/tables didn't render; transcript Cyrillic was mojibake"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 92
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
markdown headers/links/tables didn't render; transcript Cyrillic was mojibake
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`md_to_html` now renders ATX headers → bold, `[t](url)` → `<a>`, and GitHub tables → an aligned `<pre>` grid; `as_document` prepends a UTF-8 BOM for `.md`/`.txt`. Tests added.
<!-- SECTION:NOTES:END -->

