---
id: TASK-346
title: "Location pins delivered (and the raw JSON no longer leaked) on the non-rich `finish()` fallback paths"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - reliability
dependencies: []
ordinal: 346
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A map pin now arrives even for a very long reply or when the rich-message send falls back — previously the coordinates could appear as raw text with no pin.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The `location` extraction was wired only into the rich-message path; the long-reply document fallback and the post-rich-failure legacy fallback rendered the RAW reply, shipping the literal `location` JSON and sending no pin. `_commit` now builds a location-stripped body (blocks → notes) once and feeds it to `should_send_as_file` / `as_document` and `_build_sendables`, sending the pins in whichever fallback delivers the body (the rich path returns earlier, so pins are sent exactly once). +negative-path test coverage. compile + import + ruff + suite 258 green; live restart "Run polling".
<!-- SECTION:NOTES:END -->

