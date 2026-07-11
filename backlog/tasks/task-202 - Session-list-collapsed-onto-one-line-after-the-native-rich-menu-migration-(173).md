---
id: TASK-202
title: "Session list collapsed onto one line after the native-rich menu migration (#173)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 202
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Menus (session list, cards, settings) render on multiple lines again instead of collapsing into one.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Rich-message HTML folds raw newlines (HTML whitespace collapsing), so the #173 `_send_menu` / `_edit_menu` helpers rendered every multi-line menu — the `/sessions` list, session cards, settings pages — on a SINGLE line and lost indentation. Both helpers now convert `\n` → `<br>` for the rich `html` field; the classic-HTML fallback keeps the raw `\n` (which `parse_mode="HTML"` renders as a newline and which rejects `<br>`). Central fix, so it covers every `_send_menu` / `_edit_menu` surface, not just the session list. py_compile + import + pytest (148) + ruff, deployed.
<!-- SECTION:NOTES:END -->

