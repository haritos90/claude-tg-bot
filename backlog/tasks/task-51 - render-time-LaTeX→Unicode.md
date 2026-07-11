---
id: TASK-51
title: "render-time LaTeX→Unicode"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 51
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
render-time LaTeX→Unicode
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`markup._latex_to_unicode` runs inside `md_to_html` AFTER code is stashed (so code spans/blocks are never touched): converts `\frac`/`\sqrt`/`\times`/greek/arrows, `^{}`/`_{}` scripts, and strips `$…$`/`\(…\)` math delimiters — guarded so prose like "$5 and $10", `_italic_`, and `a_b` are preserved. Tested. _**Superseded by #297** on the primary path: the rich-markdown reply renders native math; this Unicode degradation now runs only on the classic-HTML fallback (rich send failed)._
<!-- SECTION:NOTES:END -->

