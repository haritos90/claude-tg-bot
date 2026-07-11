---
id: TASK-188
title: "Natural-language scheduled tasks — recurring prompts set from chat"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 188
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Schedule a recurring prompt from chat — e.g. `/schedule every day at 9:00 | summarize my GitHub notifications` — and manage them with /schedules (pause/resume/delete).
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Unblocked now #165 (usage attribution) + #119 (sandbox) shipped. New pure `schedules.py` parses `<when> | <prompt>` (daily/weekly/interval, 12h/24h times; `parse_schedule`/`next_run_after`/`describe`) with a 15-min interval floor. `db.schedules` table + CRUD (add/list/count/due/enable/update_run/delete). A runner loop (`sessions._schedule_loop` + `start_scheduler`, started in `bot.main` beside the reaper) sweeps every 30 s, advances `next_run` FIRST (no tight re-fire), posts a `schedule.run_notice`, and submits the prompt into its session via `handle_text` (so it streams + posts like a normal turn; per-session queue serializes). `/schedule <when> | <prompt>` (arg-capture #101) with a per-user cap (5) and usage help; `/schedules` lists with inline pause/resume (recomputes next_run on resume) + delete, owner-scoped callbacks. `reply()` gained `reply_markup`. i18n (en+ru) + command-menu entries. +12 parser unit tests; DB CRUD integration-checked (due-filter/pause/update/delete). py_compile + import + i18n parity + ruff clean; **suite 191 passed**; live restart "Run polling"; `schedules` table created. On-device run of a fired schedule pending.
<!-- SECTION:NOTES:END -->

