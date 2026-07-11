---
id: TASK-21
title: "ambient subscription-usage display (`/usage off|footer|pinned|both`)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - observability
dependencies: []
ordinal: 21
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
ambient subscription-usage display (`/usage off|footer|pinned|both`)
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Delivered: `/usage` modes via `usage.py`; per-window % left; persisted across restart (`db.kv` `rate_snapshot` + pinned msg id).
<!-- SECTION:NOTES:END -->

