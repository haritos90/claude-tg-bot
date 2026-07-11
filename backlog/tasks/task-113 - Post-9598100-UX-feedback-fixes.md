---
id: TASK-113
title: "Post-#95/#98/#100 UX feedback fixes"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 113
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
RU command menu now follows /language; tidier sessions menu; code-only file commands; no stale streaming setting.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
(1) `/language` (+ the `/settings` picker) now refresh the `/` command menu in the chosen language via a per-chat `BotCommandScopeChat` (`_apply_user_menu`), overriding Telegram's client-language default — and scoping the menu to the user's level (chat-level users never see code commands, closing the #102 menu gap for non-owners). (2) The `/sessions` options menu is re-posted at the bottom after Recap/Status/Export so it stays reachable without scrolling (`_repost_options`). (3) `/files` + `/export` are gated to code sessions (`common.code_only`). (4) Removed the lingering streaming row from `/settings` (header line, `_settings_text`, `_gather_vals`) and dropped `/stream` from the command menu.
<!-- SECTION:NOTES:END -->

