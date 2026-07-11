---
id: TASK-174
title: "Re-enable rich for code replies (was gated on Telegram styling code blocks)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 174
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Code replies stay in the one consistent rich message; fenced code is monospace until Telegram styles it.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Moot — #176 already ships the whole reply (code included) as ONE rich-markdown message; a fenced code block renders as plain monospace in rich (no label / syntax / copy), accepted rather than waiting on Telegram. If Telegram later styles `RichBlockPreformatted`, code styles automatically with zero change.
<!-- SECTION:NOTES:END -->

