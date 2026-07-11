---
id: TASK-295
title: "Chat mode couldn't return an image/diagram (claude.ai can)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 295
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Ask the bot in a chat session for a diagram (e.g. a furniture schematic) and it replies with an actual image, not a wall of text — vector diagrams, charts, floor plans.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Claude has no image-generation model, but it produces clean vector SVG, and claude.ai renders such diagrams. Chat mode here is tool-free (no code execution, no files), so an SVG just arrived as raw XML in the bubble. Now the bot rasterizes it: `markup.extract_svgs` pulls each complete `<svg>…</svg>` (fenced ```svg or raw) out of a reply, leaves a localized note (`stream.svg_image`), and the streamer renders it to PNG via `svg_image.render_svg_png` (cairosvg + the system `libcairo2`) and sends it as a photo (raw `.svg` document fallback if rendering fails). The draft hides streaming/unclosed SVG XML. The chat system prompt now tells the model to answer diagram/schematic/chart/floor-plan requests with a self-contained ```svg block. Works for all chat users, no code access needed. New dep `cairosvg==2.9.0` (+ `apt install libcairo2`); +tests for extraction and rendering. py_compile + import + ruff + i18n parity clean; suite 229 passed; live restart "Run polling".
<!-- SECTION:NOTES:END -->

