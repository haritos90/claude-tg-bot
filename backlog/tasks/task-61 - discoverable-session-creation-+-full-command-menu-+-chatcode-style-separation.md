---
id: TASK-61
title: "discoverable session creation + full command menu + chat/code style separation"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 61
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
discoverable session creation + full command menu + chat/code style separation
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`/newchat` + `/newcode` create immutable-typed sessions in one tap; bare `/new` shows a 💬/⌨️ chooser (`on_new_cb`). `setMyCommands` rebuilt most-used-first with **all** 20 user commands (incl. `/rename`), plus an owner-only chat-scoped menu (`auto`/`allow`/`deny`/`users`) via `BotCommandScopeChat`. Mode glyph (💬/⌨️) + a one-line `mode_tagline` now lead every session surface — creation, switch card, `/status`, `/mode`, `/sessions`. Verified: router builds, all commands register, real DB create path makes distinct chat/code sessions.
<!-- SECTION:NOTES:END -->

