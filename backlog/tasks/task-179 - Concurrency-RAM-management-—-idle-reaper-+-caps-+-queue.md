---
id: TASK-179
title: "Concurrency / RAM management — idle reaper + caps + queue"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - reliability
dependencies: []
ordinal: 179
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The bot self-limits to the server's RAM: idle sessions release their memory (history kept), simultaneous turns are capped, and overflow turns queue instead of crashing the box.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Each live session pinned a persistent `claude` subprocess (~400–600 MB) until restart — no cap, no eviction, so N idle users could OOM a small box (and the box had **no swap** = hard kill). Added in `sessions.py`: an **idle reaper** (`_reaper_loop`/`_reap_once`/`_evict_session`, started in `bot.main` next to the usage poller, cancelled in `aclose`) that `aclose()`s sessions idle > `IDLE_TTL_SEC` (default 900) — history persists on disk so `resume` rebuilds on the next message, nothing lost; a **live-client cap** (`MAX_LIVE_CLIENTS`, LRU eviction of idle clients); a **turn semaphore** (`MAX_CONCURRENT_TURNS`) bounding simultaneous generations, overflow turns queue with a `busy.queued` notice; **memory-pressure relief** (`MIN_FREE_MB`, evicts idle before a turn, reading `/proc/meminfo`). All four caps auto-derive from the box's RAM/CPU in `config.load_settings` (getattr-tolerant so test stubs construct). +4 tests (`test_sessions.py`), 116 green, ruff clean, deployed (Run polling confirmed, single poller). Ops alongside: 2 GB swap + journald 200M cap + 3proxy/btmp purge + `cron.daily` (freed ~2.2 GB); README gained a RAM/limits table + tunables.
<!-- SECTION:NOTES:END -->

