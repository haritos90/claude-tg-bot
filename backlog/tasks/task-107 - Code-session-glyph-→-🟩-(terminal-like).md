---
id: TASK-107
title: "Code session glyph → 🟩 (terminal-like)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 107
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Code sessions are marked with a big green square (terminal-like).
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`mode_glyph("code")` → 🟩 (was ▸, #96); the literal `▸` mode-glyphs in `i18n.py` (btn.code, cmd.newcode, help en+ru) + 2 handler docstrings swapped to 🟩; the generic `▸` chevrons (btn.next, lang.row, settings.row_*, deep-link button) left intact; chat stays 💬. i18n en/ru parity tests green.
<!-- SECTION:NOTES:END -->

