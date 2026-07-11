---
id: TASK-298
title: "Self-hosted Mermaid renderer (local Mermaid→PNG, no external service)"
status: Deferred
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - features
dependencies: []
ordinal: 298
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
_Priority P3 · Effort L · deferred._

Covered for now by the model-drawn SVG path (#296). A true Mermaid renderer needs Node + headless Chromium (~350 MB) or a local Kroki container — heavy install/ops against the lean-deps design, and no demand yet. Revive if model-drawn SVG layout proves insufficient for large/complex graphs.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
**#298 — Self-hosted Mermaid renderer** (P3 · L · features · _follow-up to #296_)

Render true Mermaid diagrams (the model emits a ```mermaid block and the renderer lays it out
AUTOMATICALLY) WITHOUT shipping content to a third-party service. Mermaid can't be rendered in pure
Python — it needs a JS engine + headless browser for DOM text-measurement / auto-layout. Two
self-hosted options:

- **(a) Node + `@mermaid-js/mermaid-cli` (`mmdc`) + headless Chromium** (~300–400 MB) rendering
  Mermaid→SVG, then reuse `svg_image.render_svg_png` (cairosvg) for SVG→PNG.
- **(b) A local Kroki container** (HTTP on loopback, no egress) rendering Mermaid→PNG directly.

Mirror the #295/#296 pipeline: add `extract_mermaid` to `markup.py` (pull ```mermaid blocks → a
token, like `extract_svgs`), a small renderer module, and a `streamer` branch that sends the PNG
with a raw-`.mmd`-document fallback so nothing is lost; gate it behind a `MERMAID` enable flag. The
win over #296's model-drawn SVG is automatic, overlap-free layout for LARGE graphs. Parked: heavy
install + ops against the lean-deps philosophy, and the SVG path (#296) covers the common case.
Local rendering keeps it inside the no-leak posture (the external-service alternative was rejected
for exactly that reason).
<!-- SECTION:NOTES:END -->

