---
id: TASK-173
title: "Make the keyboard menus native rich too (full font consistency)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 173
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Button menus (settings, users, sessions) now render in the same native rich font as replies — consistent typography across the whole bot.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The inline-keyboard menus still used classic `parse_mode="HTML"` while replies/tables were native rich (#172/#164). Added `EditRichMessage(TelegramMethod)` to `rich_message.py` (Bot API 10.1 `editMessageText` + the `rich_message` param) and two `handlers` helpers — `_send_menu` (`sendRichMessage` + `reply_markup`, returns the sent Message for callers that need its id) and `_edit_menu` (`editMessageText` + `rich_message`, treating "message is not modified" as a no-op). Routed every inline-keyboard surface through them: the settings hub + choice pickers, Tools grid, Users list + per-user cards, Usage / Admin / retention sub-pages, language picker, session-options + sessions list, codesplit / working-plate toggles, and the model/language confirmations. Both helpers fall back to the classic send/edit on any failure (including a pre-rich message edited after deploy), so a menu is never lost. py_compile + import + pytest + ruff clean.
<!-- SECTION:NOTES:END -->

