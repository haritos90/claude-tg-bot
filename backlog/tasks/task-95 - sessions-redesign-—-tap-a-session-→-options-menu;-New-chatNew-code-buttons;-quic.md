---
id: TASK-95
title: "`/sessions` redesign — tap a session → options menu; New chat/New code buttons; quick actions on switch"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 95
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The `/sessions` list is scannable — tap a session for a full actions menu; create chat/code sessions right from the browser.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Each list row is now a single full-width NAME button → tapping it opens a per-session options menu (✅ Switch · 📋 Recap · ✏️ Rename · ℹ️ Status · ⭐/☆ favorite · 🗑 Delete · ◂ Back). The browser footer gained **💬 New chat** / **🟩 New code** (next to Search/Close). The switch card now carries quick actions (📋 Recap · 📄 Export). Recap/Rename/Status/Export are now key-addressable (`_recap_messages`, `_history_doc`, `_session_options`, key-aware `_do_rename` + a `rename:<key>` pending action); every per-session action is ownership-gated via `_owned_session` (chat_id OR created_by). i18n en/ru parity + 47 tests + ruff green.
<!-- SECTION:NOTES:END -->

