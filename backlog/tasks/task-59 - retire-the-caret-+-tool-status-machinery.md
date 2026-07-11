---
id: TASK-59
title: "retire the caret + tool-status machinery"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 59
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
retire the caret + tool-status machinery
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Caret zoo, `_spinner`, status block, `/settings` caret+speed pages removed (Telegram owns the DM frontier; the caret just flickered). Single streaming standard. **(2026-06-14 audit follow-up:** removed the leftover dead `SessionManager.set_caret_speed` + its `caret_speed` kv-load + the now-unused `CARET_SPEEDS` import in `sessions.py`; the dormant group write-head keeps a fixed `"normal"` pace. The gap the re-audit flagged is closed.)
<!-- SECTION:NOTES:END -->

