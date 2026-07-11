---
id: TASK-90
title: "favorite/pin sessions (⭐)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 90
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
favorite/pin sessions (⭐)
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Star a session to pin it: `threads.favorite` column + `db.set_favorite`, favorites sort first (`browse_threads ORDER BY favorite DESC`), a ☆/⭐ toggle in `/sessions` (own-session guarded) that marks the name and floats it to the top so important sessions don't need searching. db test added.
<!-- SECTION:NOTES:END -->

