---
id: TASK-97
title: "Unique git-commit-style session ids (short hash, not a position or plain number)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - core
dependencies: []
ordinal: 97
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Sessions now have a fixed short id (e.g. `0d4be1`) instead of a number that shifted.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`db.session_sid(thread_id)` = `sha1("sess:"+id).hexdigest()[:6]` — a stable, migration-free PUBLIC id derived from the immutable thread_id, so every existing session gets one immediately. Shown as `<code>{sid}</code>` in `/sessions` rows, the switch card (`session.card_meta`), and `/status` (`status.header`), REPLACING the `enumerate` list position that shifted as sessions were added/removed. Also bumped the row button's name clip 20→40 so long names (e.g. a long multi-word title) aren't cut. Typed sid-reference folds into #95/#100.
<!-- SECTION:NOTES:END -->

