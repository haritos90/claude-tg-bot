---
id: TASK-256
title: "Wide (>20-col) tables are not clipped on the draft streaming path"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - ux
dependencies: []
ordinal: 256
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A very wide table now shows its "sent as an image" note consistently while the reply streams, instead of flickering as a broken table and then turning into an image.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The #243 wide-table guard ran only at finish (`_commit`); a >20-column table streamed verbatim through `SendRichMessageDraft` (the over-cap case `verify-rich-draft.py --wide` probes), then vanished from the final bubble and reappeared as a PNG. Factored the token→note expansion into `streamer._wide_table_notes` and call it from BOTH paths: `_render_draft` now runs `extract_wide_tables` on the clipped draft body and shows the localized `stream.wide_table` note while streaming, matching the final bubble (the table still goes as a PNG only at finish). No-op fast path when nothing is wide. +streamer test. py_compile + import + ruff clean; suite 197 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

