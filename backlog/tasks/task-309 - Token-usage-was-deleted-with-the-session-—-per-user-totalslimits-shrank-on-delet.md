---
id: TASK-309
title: "Token usage was deleted with the session — per-user totals/limits shrank on delete (cap-evasion)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - reliability
dependencies: []
ordinal: 309
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Your token-usage history — and the usage limits that depend on it — now survives deleting a session: deleting a chat no longer erases its recorded usage from your totals.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Deleting a session ran `DELETE FROM usage WHERE thread_id=?` and every per-user aggregate JOINed usage→threads on `chat_id`, so a deleted session's tokens vanished from the user's 5h/week/lifetime totals — letting a user shrink recorded spend (and dodge the #120 rolling caps) by deleting sessions, and skewing the owner's `/users` stats. (Automatic paths — idle rotation, reaper/TTL eviction, `/reset`, `/clear`, and the zero-usage cap-evictor — already preserved usage; only the manual `/delete` and the threads-join were destructive.) Decoupled usage from the session lifecycle: added a `chat_id` column to `usage` (backfilled from each row's thread on migrate; new `idx_usage_chat_ts`, created AFTER the ALTER so an existing db doesn't index a not-yet-added column), `add_usage` stores the owning chat_id via a threads sub-select, and the three per-user aggregations (`get_user_usage_window`/`get_user_breakdown`/`get_all_users_breakdown`) now sum by `usage.chat_id` directly (no threads join) so orphaned rows still attribute. `delete_dm_session` no longer deletes usage (commented out; message/schedule cascades kept). Migration dry-run on a copy of the live db (chat_id added, all rows backfilled, 0 orphaned) caught the index-ordering bug before deploy. +regression test (usage survives delete across all three aggregations). compile + import + ruff + suite 230 clean; live restart "Run polling"; live db migrated (chat_id backfilled).
<!-- SECTION:NOTES:END -->

