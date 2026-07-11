---
id: TASK-300
title: "SVG rasterizer could fetch external/local resources on the host (SSRF + file read)"
status: Done
assignee: []
created_date: '2026-07-04 00:00'
labels:
  - security
dependencies: []
ordinal: 300
---
## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Closes an SSRF / host-file-read hole: a chat-drawn diagram can no longer make the bot fetch external URLs or read local files while rasterizing, and a pathological SVG can't balloon the render's memory.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
`svg_image.render_svg_png` (#295) rendered via `cairosvg.svg2png(...)` with no explicit fetcher policy; rasterization runs in `streamer._send_svg_image` via `asyncio.to_thread`, OUTSIDE the per-session jail, on SVG bytes a chat-only user can steer — so a referenced `file:///…` or `http://169.254.169.254/…` (cloud-metadata) resource would be a host-side SSRF + local-file read. (The installed cairosvg defaults `unsafe=False` → `safe_fetch`, which already blocks non-`data:` URLs — confirmed empirically — but the policy was implicit and could regress on a version bump since `svg2png` can't forward a `url_fetcher`.) Made it explicit and version-proof: render through `PNGSurface.convert` with `unsafe=False` AND an explicit `url_fetcher=safe_fetch` (inline `data:` URIs only — external schemes dropped, never fetched); the streamer's raw-`.svg` fallback covers any render error. Updated the module docstring's security note (was silent on external fetch). Sub-nit (P3, raster cap): bounded the rendered raster to `MAX_RASTER_PX` (4M px ≈ 16 MB) and each dimension to `MAX_RASTER_DIM` (16384, under cairo's hard limit), clamping only when an extreme `viewBox`/aspect would blow the budget so normal diagrams keep cairosvg's own aspect (no distortion) — stops a few-KB SVG from allocating hundreds of MB. Verified e2e: `file://`/`http://` refs blocked while render still succeeds, `data:` still works, pathological tall viewBox stays bounded with no crash. py_compile + import + ruff + suite clean; live restart "Run polling".
<!-- SECTION:NOTES:END -->

