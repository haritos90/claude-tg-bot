---
id: TASK-347
title: "`location`-block parsing/sending hardening (nested-fence skip, venue length cap + plain-pin fallback, dropped key aliases)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - reliability
dependencies: []
ordinal: 347
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A map reply is sturdier — showing the location format as an example no longer drops a stray pin, and a place with an unusually long name or address still lands on the map.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`extract_locations` now skips a `location` block nested inside a longer (4+ backtick) demo fence, so the docs / a model demonstrating the feature no longer drop a live pin or corrupt the outer fence (new `_OUTER_FENCE_RE`). `_coerce_location` caps `title`/`address` to 256 chars so an over-long string can't make `sendVenue` 400, and `_send_location` falls back to a plain `send_location` when the venue send fails, so valid coordinates always drop at least a marker. Dropped the undocumented `name`/`addr` key aliases to match the documented `title`/`address` schema. +tests. compile + import + ruff + suite 258 green; live restart "Run polling".
<!-- SECTION:NOTES:END -->

