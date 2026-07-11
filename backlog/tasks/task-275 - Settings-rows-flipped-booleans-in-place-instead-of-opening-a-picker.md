---
id: TASK-275
title: "Settings rows flipped booleans in place instead of opening a picker"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 275
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Tapping a setting (in /settings OR on a user's card) now always shows the available values with a Back button before changing anything — no more accidental one-tap flips.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
In `/settings`, a boolean row toggled its value the instant it was tapped (`sx:tog`) — so a user who didn't recall the options (or how many there were) could silently flip On→Off with one tap. Now EVERY editable setting opens a value picker with a Back button, even a 2-option On/Off boolean: the hub row routes booleans through `sx:nav` (the picker) like any other setting, `_setting_choice_labels` returns On/Off choices for `type is bool` (labels matching the value renderer so the ✓ lands right), and the two owner Admin toggles (code-split, working-plate) became On/Off pickers too (`sx:admin:bool/boolset`). The per-user `/users` CARD got the same treatment: its memory / max-effort booleans and the level (chat/code) row no longer flip in place — they open On/Off (or chat/code) pickers with Back (`usr:bopt/boptset`, `usr:lopt/loptset`). A direct typed command (`/shell`, `/auto`) still toggles — that's explicit intent, not a menu tap. Guideline documented in menu.md (§1.1 + §1.5). py_compile + import + ruff + i18n parity clean; suite 220 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

