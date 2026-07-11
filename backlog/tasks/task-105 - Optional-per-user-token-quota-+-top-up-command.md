---
id: TASK-105
title: "Optional per-user token quota + top-up command"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - security
dependencies: []
ordinal: 105
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Optional per-user token budget with `/limit` top-ups; over-budget users pause until topped up.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Each entry has an optional cumulative `token_grant` (None = unlimited); "used" = `SUM(input+output)` over the user's sessions (`db.get_user_usage_tokens`). Enforced pre-turn in `_access_block`: at/over grant the turn is refused with a remaining message. `/limit @user <tokens>` tops up the grant (`/limit @user off` = unlimited); `/users` shows used/grant. Owner uncapped.
<!-- SECTION:NOTES:END -->

