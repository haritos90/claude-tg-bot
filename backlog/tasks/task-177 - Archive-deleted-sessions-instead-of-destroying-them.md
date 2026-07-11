---
id: TASK-177
title: "Archive deleted sessions instead of destroying them"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - reliability
dependencies: []
ordinal: 177
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Deleting a session no longer loses its files OR its transcript — they're compressed into cold storage; nothing is destroyed.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Session delete (`ses:delok`) used to `shutil.rmtree` the workdir + `.sbxstate` and ORPHAN the transcript (it lives outside the workdir, in `~/.claude/projects/<encoded-cwd>/`). New `archive.py` `archive_session()` now MOVES all three (workdir + sbxstate + transcript) into one gzip bundle `BASE_WORKDIR/_archive/<owner_id>/<sid>-<stamp>.tar.gz` (+ a `.json` sidecar; text/jsonl compresses ~10× so disk drops) and removes the live copies — fail-safe (a write error keeps the live copies). A sid-suffix guard ensures the shared repo-root transcript dir can never be swept up. Old rmtree commented out (not deleted) per the audit convention; `import shutil` retired from handlers. +4 tests (`test_archive.py`), 112 green, ruff clean. Auto-purge/restore of archives deferred → #178.
<!-- SECTION:NOTES:END -->

