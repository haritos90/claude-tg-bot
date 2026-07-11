---
id: TASK-354
title: "`location` fenced-block regex tolerated a space the guards reject → dropped pin"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 354
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
`location` fenced-block regex tolerated a space the guards reject → dropped pin
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`markup._LOCATION_BLOCK_RE` matched an optional space after the opening fence (`` ```[ \t]*(?:location|geo) ``) that the contiguous guards in `extract_locations` and `streamer._hide_unclosed_location` reject, so the regex's behavior diverged from the guards (a `` ``` location `` block was tokenized into a pin on some paths but rejected — raw JSON, no pin — on others). Required the documented CONTIGUOUS form by dropping the leading `[ \t]*`, so the regex and both guards agree and a spaced fence is uniformly left verbatim. Also hardened `streamer._location_notes` to replace each `LOCATION_TOKEN` off the ACTUAL tokens present (`note.join(rich_text.split(TOKEN))`) instead of `range(len(locations))`, so a token/location count mismatch can never drop a trailing part. compile + import + ruff + suite 264 green (+ a focused test: a spaced fence alongside a contiguous one is left verbatim, only the contiguous block becomes a pin); live restart "Run polling".
<!-- SECTION:NOTES:END -->

