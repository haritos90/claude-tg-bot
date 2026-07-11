---
id: TASK-44
title: "DM mode foundation (private chat, isolated)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - core
dependencies: []
ordinal: 44
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
DM mode foundation (private chat, isolated)
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Private chats route to bot-managed sessions with synthetic NEGATIVE keys that never collide with supergroup topics (≥ 0) or other users; per-user current-session pointer; gate re-keyed by the unique session key; DM-aware `/start`; `/new` creates a DM session; `/sessions` browse/search/switch + info card. Isolation verified.
<!-- SECTION:NOTES:END -->

