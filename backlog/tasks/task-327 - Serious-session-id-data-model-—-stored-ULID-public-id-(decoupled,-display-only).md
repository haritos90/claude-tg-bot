---
id: TASK-327
title: "Serious session-id data model — stored ULID public id (decoupled, display-only)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - core
dependencies: []
ordinal: 327
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Sessions now show a serious, fixed-length, opaque public id (ULID) instead of a short hash or the internal `-N` number — and existing conversations keep working (the on-disk layout was untouched).
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Added a stored PUBLIC session id — a **ULID** (26-char Crockford base32, opaque, time-sortable) — shown in the UI (session card, /status header, export filename), DECOUPLED from the filesystem so resume can't break: `session_pubid()` returns the stored ULID (cache), while `session_sid()` stays the stable 6-hex `sha1[:6]` that names the on-disk workdir / transcript / jail-uid / secrets (NEVER moved). `threads.sid` column + a DB-ONLY idempotent backfill (`migrate_sessions_to_ulid`, run at startup; no dir renames); `allocate_dm_session` mints a ULID for the public id but keeps the 6-hex workdir; 4 display call-sites → `session_pubid`, the 7 filesystem sites stay on `session_sid`. (A first attempt renamed workdirs to ULID and was rolled back — the real "no history" cause turned out to be idle-rotation #329, not the rename; the decoupled redo touches no files.) +tests; dry-run on a live-DB copy (cwd UNCHANGED, all sids ULID); deployed — backfilled 18 sessions, 0 NULL, workdir==session_sid for every real session, resume intact. 247 tests green.
<!-- SECTION:NOTES:END -->

