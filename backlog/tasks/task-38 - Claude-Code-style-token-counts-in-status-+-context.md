---
id: TASK-38
title: "Claude-Code-style token counts in /status + /context"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 38
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Claude-Code-style token counts in /status + /context
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`_fmt_tokens` abbreviates counts (12345 → "12.3k", 1.2M); `/status` shows `Tokens: Xk in · Yk out` + `Cache: …`, `/context` abbreviates used/total — easier to read than raw digits.
<!-- SECTION:NOTES:END -->

