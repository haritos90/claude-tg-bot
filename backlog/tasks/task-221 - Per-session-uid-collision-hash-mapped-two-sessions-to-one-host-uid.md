---
id: TASK-221
title: "Per-session uid collision: hash mapped two sessions to one host uid"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - isolation
dependencies: []
ordinal: 221
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Two sessions can no longer be assigned the same sandbox uid — each session's host uid is reserved in a registry that probes past collisions, so per-session file isolation holds even when the uid hash collides.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`engine.py` derived each jail's host uid as `uid_base + (int(sid,16) % uid_range)` (60000 buckets) — deterministic but birthday-colliding: two sessions (even different users, since `thread_id` is global) could map to one uid, making their `0700` workdirs mutually readable/writable. Added a `session_uid(sid PK, uid UNIQUE)` registry + `db.claim_session_uid(sid, preferred, lo, hi)`: returns the recorded uid (stable across rebuilds), else the preferred hash uid if free, else linear-probes `[lo,hi)` for a free slot and records it (serialised by `_lock`; `UNIQUE(uid)` is the backstop). `ClaudeSession._ensure_client` claims the uid async — before the sync `_build_options`/`_enable_sandbox` — and caches it on `self.host_uid`; `_enable_sandbox` reads it, falling back to the bare hash if unclaimed (tests) or the registry is down. `delete_dm_session` frees the slot (`release_session_uid`). Migration is near-free: preferred == the existing hash uid, so live sessions keep their uid (no re-chown) and only a pre-existing collision self-heals on the bumped session's next turn via the launcher's stat-guarded `chown -R`. A startup "doctor" (`db.sandbox_uid_collisions`, run in `bot.main` off the pre-READY path) scans on-disk workdirs for any host uid shared by >1 session and logs + DMs the owner if found (self-heals on the affected sessions' next turn). +4 db tests. py_compile + pytest (155) + ruff; registry table + clean doctor verified on the live db, bot re-polling.
<!-- SECTION:NOTES:END -->

