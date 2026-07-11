---
id: TASK-165
title: "Weighted per-user usage units that mirror the official windows"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - observability
dependencies: []
ordinal: 165
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Usage caps now reflect the real cost of a turn (model, output and cache — not just input/output tokens), so heavy sessions are counted fairly. Existing day/week caps are now measured in weighted units; re-tune them if a previous token figure no longer fits.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Per-user caps counted only raw `input+output` tokens, so a big WARM context (cheap input but a huge `cache_read` re-read every turn) read as near-zero spend while the shared subscription window drained. The `usage` table gained `model` + `context_tokens` columns (additive migration); `db.add_usage` stores both. New `db.get_user_usage_units` / `get_user_units_breakdown` compute a cost-weighted token-equivalent at QUERY time: `MODEL_WEIGHT * (input + 5·output + 1.25·cache_creation + 0.1·cache_read)`, model matched by substring (opus 5 / sonnet 1 / haiku 0.27; all coefficients are tunable module constants — no migration to re-weight). Each turn's cost derives only from its own row, so it is concurrency-safe (no before/after delta on a shared global gauge). Enforcement (`_access_block`), `/limits`, the user card and the `/users` usage lines now use units; day/week caps are therefore interpreted as units (≈ Sonnet-input-token-equivalents). i18n cap-exceeded strings + a `/limits` note state the unit basis. py_compile + import + pytest + ruff clean.
<!-- SECTION:NOTES:END -->

