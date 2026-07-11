---
id: TASK-192
title: "Weighted usage units silently re-based the day/week usage caps"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - observability
dependencies: []
ordinal: 192
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Per-user usage caps are now clearly labelled in weighted units everywhere they're entered or shown (`/limit`, the user card), matching how usage is actually counted — no more "tokens" wording that undercounted the real cap.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
#165 switched per-user rate enforcement to weighted usage UNITS (`get_user_usage_units`; a unit ≈ a Sonnet-input-token-equivalent, ~5× Sonnet to ~25× Opus+cache vs raw tokens) and the enforcement + the exceeded notices were already unit-based, but the cap ENTRY surfaces still said "tokens" — so an owner typing `500k` thought tokens while the cap compared against units (~5–25× looser). Fix is label-only (no logic change): the caps were already stored and compared as units, only the wording lied. Relabelled the entry prompts (`usercard.prompt_day` / `usercard.prompt_week`), the `/limit` arg hint + prompt (`limit.usage` / `limit.prompt`), the set-confirmation (`limit.set`), and the `cmd_limit` docstring to say "units" (en + ru), matching `limits.units_note` and the unit-based usage display. No migration: units have no single token→unit factor (model/cache-dependent), and a fixed re-scale would be wrong — existing caps are simply interpreted as units now; the owner reviews them via the usercard. Old strings kept commented with the #192 tag. py_compile + i18n round-trip verified; live, polling.
<!-- SECTION:NOTES:END -->

