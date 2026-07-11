---
id: TASK-211
title: "Session list row showed the mode word and creation date"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 211
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The session list shows just the icon and name per row (plus a "current" marker) — no mode word or creation date.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The `/sessions` list printed `{icon} {name} — {mode} · {date}` per row; the icon already conveys chat/code and the date is list noise. `sessions.row` now renders just `{icon} {name}` plus the `⬅️ current` marker; the dead `mode`/`date` kwargs were dropped from the caller (old kept commented). py_compile + pytest + ruff.
<!-- SECTION:NOTES:END -->

