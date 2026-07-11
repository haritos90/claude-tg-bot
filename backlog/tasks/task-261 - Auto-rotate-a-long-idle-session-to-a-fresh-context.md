---
id: TASK-261
title: "Auto-rotate a long-idle session to a fresh context"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 261
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A session that's been quiet for ~30 minutes starts fresh on your next message (no stale context carried over) — silently, with your project files kept. The owner can change the window (or turn it off) in Admin settings.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
After a configurable quiet window (default 30 min) the next message starts a CLEAN conversation instead of resuming stale context, avoiding context drift from re-ingesting old history. `handle_text` calls `_maybe_rotate_idle` under the session lock (idle worker only) before building: if the session has resumable ids and `now - last_active ≥ window`, it NULLs the code+chat session ids (`db.rotate_session_for_idle` — keeps the workdir, transcript, message log; only drops the resume context, unlike `reset_thread` which also wipes messages), drops the live client so the rebuild resumes nothing. The rotation is SILENT — no "new session" push message (an auto-notice on every idle gap reads as spam); the drafted `session.idle_reset` string is kept unreferenced for if/when announcing is wanted. Durable last-activity is a new wall-clock `last_active` column stamped at each turn end (survives restart, unlike the reaper's in-memory monotonic clock). Window resolution mirrors the idle-TTL: a global default — owner-settable at runtime in `/settings → Admin` (a picker: Off / 15m / 30m / 1h / 2h / 4h, persisted to kv `idle_reset_sec`, default 30 min; `IDLE_RESET_SEC` env seeds it) — with a per-user `idle_reset_min` KV override (≤0 = never). Pairs with #260 — the fresh conversation gets its own auto-title. +7 tests (last_active roundtrip + rotation keeps messages; fires-silently/skips-within-window/off-when-zero/no-context/per-user-disable; admin setter persists). py_compile + import + ruff + i18n parity clean; suite 211 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

