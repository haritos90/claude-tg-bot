---
id: TASK-236
title: "Follow-up-while-busy: queue at the turn boundary with a Claude-Code-style UX"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 236
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
When you send another message while the bot is still replying, it now confirms the message was queued and will run next — and caps a runaway backlog — instead of silently stacking up.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The session already queued follow-ups behind a running turn (`rec.queue`, task chaining) but gave no feedback and had no backlog bound. Design rationale: do NOT inject mid-turn — a mid-turn stdin message makes the agent CLI hang waiting for a second result, so what Claude Code shows as "added while answering" is queue-at-boundary + UX, not real injection. So `handle_text` now returns a status: `SUBMIT_STARTED` (0) when the worker was idle and it runs now, a positive count of prompts WAITING when it was queued behind a running turn, or `SUBMIT_QUEUE_FULL` (-1) when the per-session backlog cap (`MAX_QUEUED_MESSAGES`=5) is hit and the prompt is NOT enqueued. The handlers (`on_text`, `_submit`/attachments incl. #235 albums) ack via `_ack_queue`: a queued message replies `queue.queued_ack` ("📥 Queued — will run after the current reply (N waiting)"), an over-cap one replies `queue.full_reject`; an immediate start stays silent. Added `tests/test_sessions.py::test_handle_text_queue_status_and_cap`. NON-goal kept: mid-turn injection / parallel turns on one session. Deferred (optional, not needed for the ask): a staleness watermark (Telegram doesn't redeliver messages the way some platforms do, so it isn't needed here) and merging consecutive queued texts into one turn. py_compile + import + ruff clean; full suite 160 passed (1 pre-existing unrelated PIL font failure); live restart confirmed "Run polling".
<!-- SECTION:NOTES:END -->

