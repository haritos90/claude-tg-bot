---
id: TASK-264
title: "Align per-user usage caps with Anthropic's real 5h / 7d windows"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 264
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Per-user limits now reset on the same ~5-hour cadence as the real Anthropic subscription (instead of a 24-hour "daily" window), so the owner can share the budget across users more fairly; all the "daily" labels now read "5h".
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The per-user rolling caps (`/users` card; stored in `allowlist.json` as `day`/`week` weighted-unit limits, enforced from `db.usage` timestamps) used a 24h "daily" short window — but Anthropic's real subscription short window resets every ~5 HOURS, so a 24h cap was too coarse for the owner to split the shared budget fairly between users. Changed the short window to 5h: new `db.SHORT_WINDOW_SEC = 5*3600` / `db.WEEK_WINDOW_SEC = 7*86400`, applied in the three breakdown queries (`get_user_usage_breakdown`, `get_user_units_breakdown`, `get_all_users_usage`) and the enforcement gate (`_access_block` now queries `since=now-SHORT_WINDOW_SEC`). The long window stays 7d. Internal dict keys remain `day`/`week` (no `allowlist.json` migration — `day` now means trailing-5h), and all user-facing labels were relabeled "daily/Today/24h" → "5h" across `/limits`, the `/users` card + buttons, `/whoami`, userstats, the streaming footer, the cap-entry prompt, and the limit-reached block message (en + ru). Caps stay in cost-weighted units (#165) — which already account for context cost via the cache-read weight, so they track how the shared window actually fills. No behavior change to the weekly window. py_compile + import + ruff + i18n parity clean; suite 212 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

