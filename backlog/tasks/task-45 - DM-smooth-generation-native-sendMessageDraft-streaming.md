---
id: TASK-45
title: "DM smooth generation: native `sendMessageDraft` streaming"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 45
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
DM smooth generation: native `sendMessageDraft` streaming
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
DM streams via `send_message_draft` (`streamer._render_draft`): Telegram animates appended chars letter-by-letter. Text-only (no status block / caret) to keep a clean growing prefix; `draft_id` constant; ≤5 updates/sec (`_DRAFT_INTERVAL=0.2`, measured 3s RetryAfter penalty below ~110ms); `finish()` persists a real message; no fallback to write-head on transient errors. Verified live by the owner.
<!-- SECTION:NOTES:END -->

