---
id: TASK-39
title: "evaluate native Telegram streaming (sendMessageDraft)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - observability
dependencies: []
ordinal: 39
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
evaluate native Telegram streaming (sendMessageDraft)
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Investigated: real + aiogram-supported (`bot.send_message_draft`, Bot API 9.3+, opened to all bots in 9.5), but tested live → **private-chat-only** (`TEXTDRAFT_PEER_INVALID` for supergroup/topics). Incompatible with the Topics-as-sessions design; kept the write-head (#3). Documented in AGENTS §5.
<!-- SECTION:NOTES:END -->

