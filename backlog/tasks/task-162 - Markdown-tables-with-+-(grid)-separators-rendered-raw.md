---
id: TASK-162
title: "Markdown tables with `+` (grid) separators rendered raw"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 162
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Tables that use `+` grid separators now render as aligned monospace grids instead of raw text.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`markup._TABLE_SEP_RE` only matched ` | `-junction separator rows, so a pipe table whose under-header line used the ASCII/grid form `---+---+---` (and dropped the outer pipes) wasn't detected → the whole table leaked as raw text. Widened the junction char class to `[ | +]` (data rows still split on ` | `); a bare dash run (`------`, no junction) still isn't mistaken for a table. +2 markup tests (the `+`-grid table + the hr negative); README formatting bullet notes both separator styles.
<!-- SECTION:NOTES:END -->

