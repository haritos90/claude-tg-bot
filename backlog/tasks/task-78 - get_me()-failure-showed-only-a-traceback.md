---
id: TASK-78
title: "`get_me()` failure showed only a traceback"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - observability
dependencies: []
ordinal: 78
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
`get_me()` failure showed only a traceback
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`bot.main()` logs "Failed to authenticate with Telegram — check TELEGRAM_BOT_TOKEN" before re-raising.
<!-- SECTION:NOTES:END -->

