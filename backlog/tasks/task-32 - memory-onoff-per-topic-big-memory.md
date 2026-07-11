---
id: TASK-32
title: "`/memory on|off` per-topic big memory"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 32
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
`/memory on|off` per-topic big memory
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
New `big_memory` flag + `chat_session_id` column (live `bot.db` migrated). On → chat gets the 1M context beta and resumes its persisted session, so the topic survives restart + `/stop`; off → standard ephemeral chat. Chat session id is ALWAYS persisted (so toggling on keeps the context built so far) but only RESUMED when on; `/reset` clears it. `/status` shows the state. Verified end-to-end.
<!-- SECTION:NOTES:END -->

