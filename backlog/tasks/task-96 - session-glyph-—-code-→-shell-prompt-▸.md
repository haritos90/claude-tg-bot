---
id: TASK-96
title: "session glyph — code → shell-prompt ▸"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 96
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Code sessions are now marked with a ▸ shell-prompt glyph instead of a keyboard.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`mode_glyph("code")` → `▸` (shell-prompt / bash-cursor-like) instead of ⌨️; the 6 hardcoded ⌨️ in `i18n.py` (btn.code, cmd.newcode, help + /new chooser) and 2 handler docstrings swapped to ▸; chat stays 💬. i18n en/ru parity tests green. The `/rename`-button ✏️ + per-row list/info icons fold into the #95 `/sessions` redesign (no standalone rename button exists yet). **(Superseded by #107 — code glyph is now 🟩.)**
<!-- SECTION:NOTES:END -->

