---
id: TASK-103
title: "Time-limited access — per-user expiry date"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - security
dependencies: []
ordinal: 103
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Access can expire on a date; expired users are dropped, owner never expires.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Entries carry an optional `expires_at` (UTC date); past it the user is denied inside `Allowlist.is_allowed`, so `AllowlistMiddleware` drops them (fail-closed — an unparseable expiry counts as expired; owner exempt). Granted via `/allow @user [level] until YYYY-MM-DD` or `/expire @user YYYY-MM-DD | never`; `/users` shows it.
<!-- SECTION:NOTES:END -->

