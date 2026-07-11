---
id: TASK-108
title: "/recap rendered raw Markdown"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 108
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
/recap now shows Claude's reply formatted, not as raw Markdown.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`cmd_recap` now renders Claude's stored reply via `markup.md_to_html` (was `escape_html`, which leaked literal `##`/`**`/code fences — the reported bug); the user's echoed prompt stays escaped; a long/code-heavy reply is sent as size-safe rendered chunks (never splitting rendered HTML across a tag). `/history` stays a raw `.md` export.
<!-- SECTION:NOTES:END -->

