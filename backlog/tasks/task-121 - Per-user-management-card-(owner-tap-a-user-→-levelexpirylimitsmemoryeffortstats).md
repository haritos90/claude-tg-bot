---
id: TASK-121
title: "Per-user management card (owner: tap a user → level/expiry/limits/memory/effort/stats)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 121
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Manage each user from one tap-through card.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`/users` lists tappable users → `_render_user_card`/`on_user_cb`: toggle level/global-memory/max-effort, set expiry + day/week caps (arg-capture), clear limits, remove, and per-user usage stats. Owner-only; the owner's own card exposes the global-memory toggle.
<!-- SECTION:NOTES:END -->

