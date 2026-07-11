---
id: TASK-140
title: "Per-session workdirs named by session_sid + one-time migration"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 140
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Workdir names match the public session id; no internal numbering leaked.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Workdirs are now `base_workdir/<session_sid>` (sha1 short hash) not the raw numeric thread_id, for BOTH chat + code (shared architecture; chat already ran in its cwd via #133). `db.allocate_dm_session` + `sessions._default_cwd` derive the sid; `handlers._workdir_zip`/`_ensure_state`/delete-teardown switched to sid. Idempotent `db.migrate_workdirs_to_sid()` (called from `bot.main` after init_db) renames existing `workdirs/<tid>`(+`.sbxstate`)→`<sid>` and updates the stored cwd; commit-correct on rename, realign-only, and crash-after-rename cases (review-fixed: the realign branch wasn't bumping the commit guard → lost write; verified A/B/C on a temp DB). Ran live: `-7`→`fca29e` + 6 cwd realignments, bot re-polling.
<!-- SECTION:NOTES:END -->

