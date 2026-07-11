---
id: TASK-133
title: "Chat-default sessions + upgrade/downgrade to code (mutable type, carry conversation)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - core
dependencies: []
ordinal: 133
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Sessions start as chat and upgrade to code (and back), keeping the conversation.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Reverses #53: every session is born 💬 chat (one `/new`); `/code` upgrades to a code session (working dir + full tools + approval gate, gated by code-access level), `/chat` downgrades back KEEPING the workdir files. `db.switch_mode` carries the conversation by copying the resumable session id old-mode→new-mode column; BOTH modes now run in the per-session workdir (`engine`), so cross-mode resume finds the transcript (verified live — a chat-planted fact was recalled after upgrade). Session-menu **Convert** button (shown per code-access), `/mode` shows how to switch, the new-chat message hints `/code` only to code-capable users, the chat system prompt tells the model to suggest `/code` for code requests, and `big_memory` now applies to both modes. AGENTS/README + button-label UX convention updated; existing chat sessions reset context once (owner-accepted).
<!-- SECTION:NOTES:END -->

