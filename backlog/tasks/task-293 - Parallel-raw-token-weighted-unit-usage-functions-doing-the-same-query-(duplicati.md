---
id: TASK-293
title: "Parallel raw-token / weighted-unit usage functions doing the same query (duplication)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - core
dependencies: []
ordinal: 293
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Usage stats are computed by one parameterized function family instead of duplicate raw/units twins, and the two metrics are clearly labeled (units vs tokens) so they can't be confused; /userstats shows both.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The usage layer had twin functions per scope — raw-token vs weighted-unit reads running the same query with only the summed expression different: `get_user_usage_tokens`/`get_user_usage_units`, `get_user_usage_breakdown`/`get_user_units_breakdown`, `get_all_users_usage`/`get_all_users_units`. Consolidated into one `measure`-parameterized family in db.py: `_usage_measure_expr("raw"|"units")` selects the per-row SQL sum, and `get_user_usage_window(uid, since, measure)`, `get_user_breakdown(uid, measure)`, `get_all_users_breakdown(measure)` share the windows/scope/grouping. Dead `get_user_usage_tokens` (unused since #165) removed. All call sites in handlers.py/sessions.py + the test migrated; raw and units numbers are unchanged (same SQL, one definition). The two stats surfaces measure different things by DESIGN (units = the cap basis; raw tokens = how much text), so they are now labeled as distinct metrics: the /users text list and per-user card say "units", /whoami says "tokens", and /userstats shows BOTH side by side (User · 5h tok · 5h un · Wk tok · Wk un · Tot tok · Tot un · Req · Last) with a legend. py_compile + import + ruff + i18n parity clean; suite 227 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

