---
id: TASK-301
title: "`extract_svgs` returned mixed fenced/raw diagrams out of document order"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 301
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Replies that mix raw and fenced ```` ```svg ```` diagrams now render the images in the same order they appear in the text, matching their inline notes.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`markup.extract_svgs` (#295) ran `_SVG_FENCE_RE.sub` first then `_SVG_RAW_RE.sub`, so all fenced diagrams landed in the returned list before all raw ones — the `SVG_TOKEN` placeholders sat at the right positions but the list was grouped fenced-then-raw, not document order (contradicting the docstring), and `streamer` then sent the PNGs in the wrong order vs their inline notes for a reply that interleaved raw and fenced SVGs. Replaced the two passes with ONE combined regex (`_SVG_BLOCK_RE`, fenced-alternative first so a ```` ```svg ```` block is consumed whole before its inner `<svg>` can match the raw alternative); a single left-to-right `sub` keeps captures in true document order, list order == token order. Added a mixed raw-then-fenced ordering test. py_compile + import + ruff + suite clean; live restart "Run polling".
<!-- SECTION:NOTES:END -->

