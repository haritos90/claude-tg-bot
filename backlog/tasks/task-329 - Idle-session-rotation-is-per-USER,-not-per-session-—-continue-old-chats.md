---
id: TASK-329
title: "Idle session-rotation is per-USER, not per-session — continue old chats"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 329
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Opening an old conversation continues it with full context, however long ago it was — the bot starts a fresh session only when YOU have been away past the idle window, not because the session itself is old.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
#261 idle-rotation keyed off each SESSION's `last_active`, so ANY session older than the window (default 30 min) rotated to a fresh empty one on the next message — making it impossible to continue a conversation from earlier in the day. Reworked to track the USER's overall last-active time (`kv ula:<uid>`, updated on every message AND every explicit session switch): rotation fires only when the USER has been idle past the window, regardless of how old the chosen session is. An explicit /sessions switch stamps `ula=now`, so opening an old session always CONTINUES it (never rotates it away). Root-caused from live data — after hours of migration churn every session looked "idle", so each message landed in a fresh empty session; history was never lost (verified resume works at the CLI level). +test; 247 tests green; deployed.
<!-- SECTION:NOTES:END -->

