---
id: TASK-69
title: "DM callbacks acted on an unvalidated session key"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - security
dependencies: []
ordinal: 69
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
DM callbacks acted on an unvalidated session key
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`ses:sw`/`qx:`/`stop:` now require `key < 0` and `get_thread(key).chat_id == from_user.id` before acting (same guard as `ses:del`/`ses:fav`).
<!-- SECTION:NOTES:END -->

