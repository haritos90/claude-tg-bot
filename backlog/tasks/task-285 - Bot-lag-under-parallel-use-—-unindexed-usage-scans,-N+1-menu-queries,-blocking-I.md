---
id: TASK-285
title: "Bot lag under parallel use — unindexed usage scans, N+1 menu queries, blocking I/O on the event loop"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - perf
dependencies: []
ordinal: 285
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The bot stays responsive when several people use it at once: the user/session menus no longer get slower as usage history and the number of sessions/users grow, and a long reply or a finishing turn no longer briefly freezes everyone else.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
A 3-agent performance review (memory/leaks ruled out — the box was healthy; a long-lived `claude` proc was the DEV session under tmux, not a bot leak) found three classes of slowdown, all fixed: (1) DB — the append-only `usage` table had NO index, so every usage aggregate full-scanned it; added `idx_usage_thread_ts` + `idx_threads_chat` (the per-user join/filter column) — the per-thread aggregate now uses an index range scan instead of a full scan. (2) N+1 menu queries — `/sessions` ran one usage aggregate PER row and `/users` ran one weighted-units aggregate PER user; replaced with single batch GROUP BY queries (`db.get_usage_totals_bulk`, `db.get_all_users_units`). (3) Event-loop blocking — `_read_ai_title` (full transcript JSONL scan, per turn-end), the wide-table PIL PNG render (`streamer`), and the outbox multi-MB `read_bytes` now run via `asyncio.to_thread` so a finishing/long turn no longer stalls every other user's stream. (Confirmed clean by the review: model turns, the PTY read loop, and the 300s approval wait already run OUTSIDE rec.lock/the db lock, so one user's turn never blocks another opening a menu.) Deferred (noted, not done): batching the ~9–14 per-call `get_user_default` kv reads in `_effective_settings`/`_build_ss_ctx`, and a reader DB connection so menu reads don't queue behind turn-time writes through the single SQLite lock. py_compile + import + ruff + i18n parity clean; suite 227 passed; live restart "Run polling" — `idx_usage_thread_ts`/`idx_threads_chat` verified created + used by EXPLAIN.
<!-- SECTION:NOTES:END -->

