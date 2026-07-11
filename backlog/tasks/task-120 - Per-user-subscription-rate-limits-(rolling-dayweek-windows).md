---
id: TASK-120
title: "Per-user subscription rate limits (rolling day/week windows)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - security
dependencies: []
ordinal: 120
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Per-user daily/weekly token caps.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`allowlist` entry `rate={day,week}` (None=no cap) + `set_rate`/`rate_of`; `db.get_user_usage_tokens(since=)` + `get_user_usage_breakdown`; enforced pre-turn in `_access_block` over the trailing 24h/7d (no reset job). Set via the per-user card or `/limit @user <n> [day|week]|off`. Replaces the #105 lifetime cap; owner exempt.
<!-- SECTION:NOTES:END -->

