---
id: TASK-332
title: "Workdirs named by the public ULID (collision-safe) — migrate off the 24-bit 6-hex sid"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - core
dependencies: []
ordinal: 332
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Each session's files now live in a folder named by the same opaque id shown in the app, with no chance of two sessions ever colliding onto one folder — and existing conversations keep working.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The on-disk session directory (workdir + transcript + secrets + `session_uid` registry key) is now named by the PUBLIC ULID (`threads.sid`, the id shown in the UI) instead of the legacy 6-hex `sha1("sess:"+thread_id)[:6]`. The 24-bit hash reached a ~50% birthday-collision probability at ~4,800 sessions, and a collision silently merged two sessions' workdir/transcript/jail-uid/secrets (a P0 isolation break); the ULID is 80-bit + DB-`UNIQUE`-indexed. New sessions are born ULID-named (`allocate_dm_session`); the 8 path-building call sites moved `session_sid`→`session_pubid` (`session_sid`/`_derive_sid` retained for migration only). One-time idempotent startup migration `migrate_workdirs_to_ulid`: renames each legacy `<6hex>/`→`<ulid>/`, RE-ENCODES the nested `state/<encoded-cwd>` transcript dir (claude keys `resume` by the cwd — must follow the rename, the #327/#140 trap), realigns `threads.cwd`, and re-keys `session_uid` (keyed by dir name) so per-session uids stay stable; per-row fail-safe + retried each startup. Also resolves the live divergence where 3 sessions sat on ULID dirs disagreeing with `session_sid()` (delete would have orphaned them, not archived). Added `PRAGMA busy_timeout=5000`. Verified: dry-run on a WAL-safe copy of the live DB + reconstructed layout (18 migrated, 3 already-ULID skipped, transcripts re-encoded, uids re-keyed, 2nd run idempotent), encoding pre-checked against the real on-disk dirs (0 mismatches), then live cutover under a pre-#332 backup + maintenance freeze → 18 migrated, 0 six-hex dirs left, every cwd on its ULID, transcripts present. +regression test; docs (data-model.md / isolation.md) updated; 248 tests green; live restart "Run polling".
<!-- SECTION:NOTES:END -->

