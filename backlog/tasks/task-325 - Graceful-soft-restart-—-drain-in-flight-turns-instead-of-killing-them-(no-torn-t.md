---
id: TASK-325
title: "Graceful \"soft restart\" — drain in-flight turns instead of killing them (no torn transcripts)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - reliability
dependencies: []
ordinal: 325
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Restarting or updating the bot no longer cuts off an in-progress reply — it waits for active replies to finish (a few seconds) before restarting, so nothing gets truncated or lost.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
A `systemctl restart` used to SIGTERM the whole control-group, killing in-flight `claude` turns mid-generation (exit -15 — truncated output; pre-#324 also lost context). Restarts now DRAIN: (1) systemd unit `KillMode=mixed` so SIGTERM hits only the bot process, not the jailed `claude` children; (2) on shutdown the bot stops STARTING new turns (per-thread workers stop pulling new queued items) and `sessions.drain()` waits for in-flight turns to FINISH (bounded ~40s < `TimeoutStopSec`=60) before `aclose`; (3) any turn still running at the timeout is torn down but stays resumable (#324). In-flight turns tracked via `_active_turns` + an idle `asyncio.Event`. So a restart (including the upcoming migration restart) costs the user ~seconds and never tears a transcript. +test (drain blocks until idle, bounded). compile + import + ruff + suite 239 clean; live restart "Run polling"; `KillMode=mixed` applied live.
<!-- SECTION:NOTES:END -->

