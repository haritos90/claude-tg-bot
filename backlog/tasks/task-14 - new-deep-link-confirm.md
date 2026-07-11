---
id: TASK-14
title: "`/new` deep-link confirm"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 14
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
`/new` deep-link confirm
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
**Won't Do** — DM-first: a DM session is a synthetic negative key, not a forum topic, so there is no `t.me/c/…` deep-link target. `/sessions` switch + the creation/switch cards already provide navigation; the deep link is only meaningful for the frozen supergroup mode.
<!-- SECTION:NOTES:END -->

