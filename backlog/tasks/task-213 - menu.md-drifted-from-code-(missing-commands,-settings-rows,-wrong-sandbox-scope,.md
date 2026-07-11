---
id: TASK-213
title: "menu.md drifted from code (missing commands, settings rows, wrong sandbox scope, stale matrix)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - docs
dependencies: []
ordinal: 213
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
menu.md drifted from code (missing commands, settings rows, wrong sandbox scope, stale matrix)
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Refreshed menu.md against the registries: added /limits, /secret, /close, /userstats, /workingplate to the §2 tiers; added the hot_cache_timer / auto_compact / ctx_status hub rows; corrected sandbox to all-sessions (chat & code) after #215; added the user-card Name / max-sessions / idle-TTL controls + the owner self-limit card; dropped the retired `streaming` and misplaced `code_split` matrix rows and fixed the big-memory key (`memory`). Bilingual en+ru preserved.
<!-- SECTION:NOTES:END -->

