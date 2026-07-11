---
id: TASK-315
title: "Fewer `/` menu commands for chat users (everyday trio only); per-user menus on first contact"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 315
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Chat users now see a short, uncluttered command menu (just New session / Sessions / Settings); everything else is a tap away in /settings, and code users still get their full menu automatically.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Chat-level users' Telegram `/` menu is trimmed to the everyday trio — /new, /sessions, /settings (new `_chat_menu_names()` = the first 3 of the chat set, so /clear and the rest drop off; everything stays reachable via /settings and the inline menus). To keep CODE users' fuller menu without requiring a /language tap, `_ensure_state` now applies each user's privilege-filtered, localized menu via `BotCommandScopeChat` once per process on first contact (`_menu_applied` guard) — chat → trio, code → full set, owner → full + admin. compile + import + ruff + suite 230 clean; live restart "Run polling".
<!-- SECTION:NOTES:END -->

