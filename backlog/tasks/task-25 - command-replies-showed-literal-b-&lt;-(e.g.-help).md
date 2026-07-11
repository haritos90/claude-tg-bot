---
id: TASK-25
title: "command replies showed literal `<b>` / `&lt;` (e.g. `/help`)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 25
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
command replies showed literal `<b>` / `&lt;` (e.g. `/help`)
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`handlers.reply` no longer double-escapes: command HTML is sent as-is, `md_to_html` is only for model output
<!-- SECTION:NOTES:END -->

