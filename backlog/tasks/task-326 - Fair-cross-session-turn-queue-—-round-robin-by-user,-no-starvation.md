---
id: TASK-326
title: "Fair cross-session turn queue — round-robin by user, no starvation"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - reliability
dependencies: []
ordinal: 326
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
When several people (or one person with many chats) are active at once, the bot shares its turn slots fairly — no one waits behind another user's whole burst.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Replaced the global plain `asyncio.Semaphore(max_concurrent_turns)` (wakes blocked acquirers FIFO by arrival, so one user's burst of sessions could occupy every slot and make another user wait behind the whole burst) with a custom `FairAdmission` gate: at most N turns run at once, and when full, waiting turns are admitted ROUND-ROBIN by user (chat_id) — so user B is served in rotation, not behind all of user A's queued turns. Per-session FIFO worker unchanged; the gate is cancellation-safe (a cancelled waiter is dropped; a slot handed to a since-cancelled waiter is passed on, never leaked) and a drop-in for the Semaphore's `locked()` / acquire / release (paired with the #325 drain's active-turn tracking). +tests (round-robin order A2 → B1 → A3, not FIFO A2 → A3 → B1; cancel-while-waiting frees the slot, no leak). compile + import + ruff + suite 241 clean; live restart "Run polling" (graceful drain — clean shutdown, no killed turn, no exit -15).
<!-- SECTION:NOTES:END -->

