---
id: TASK-296
title: "Render graph/flow diagrams (flowchart, sequence, ER, …) in chat replies"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 296
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Chat replies now produce real flowcharts, sequence / ER / class diagrams, org charts, mind maps and other graph diagrams as a clean labelled image — not just simple schematics, and not a wall of text.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Evaluated native Mermaid and rejected it for this host: Mermaid can't be rendered in pure Python (it needs a JS engine + headless browser for layout), and the host has no Node/Chromium — so it would mean either a ~350 MB local Node+Chromium/Kroki install (against the lean-deps design, parked as #298) or an external render service (ships diagram content to a third party, against the no-leak design). Instead reused the #295 SVG→PNG path (model draws clean vector SVG, `svg_image.render_svg_png` rasterizes it): strengthened `CHAT_SYSTEM_PROMPT` (`engine.py`) to enumerate the graph diagram types (flowchart, sequence / state / ER / class, org chart, mind map, tree, network, Gantt) and to give the model explicit layout guidance — one flow direction, consistent box sizes with padding, no overlap/clipping, `<marker>` arrowheads, labelled nodes AND edges — so the model both draws and lays out the diagram itself. Old #295 prompt text kept commented with a #296 ref. py_compile + import + ruff clean; live restart "Run polling".
<!-- SECTION:NOTES:END -->

