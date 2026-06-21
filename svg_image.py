"""#295: rasterize an ``<svg>`` diagram to PNG so chat replies can show diagrams (schematics,
charts, floor plans) as images. Claude has no image-generation model, but it produces clean
vector SVG, which is exactly right for a labeled schematic. Rendering uses ``cairosvg`` (pure
Python + the system ``libcairo2``); ``cairosvg`` parses via ``defusedxml``, so XML-entity bombs
are mitigated, and the size guard below bounds a pathological payload.

The caller renders off the event loop (``asyncio.to_thread``) and, on any failure, falls back to
sending the raw ``.svg`` as a document so the diagram is never lost.
"""
from __future__ import annotations

import cairosvg

# Guard: ignore an absurdly large SVG payload (a diagram is a few KB; this caps a runaway).
MAX_SVG_CHARS = 200_000
# Target raster width in px; height scales with the SVG's own aspect ratio / viewBox.
DEFAULT_WIDTH = 1000


def render_svg_png(svg_text: str, output_width: int = DEFAULT_WIDTH) -> bytes:
    """Render an ``<svg>`` string to PNG bytes. Raises ``ValueError`` on missing/oversized
    input and propagates any cairosvg parse/render error so the caller can fall back."""
    if not svg_text or "<svg" not in svg_text.lower():
        raise ValueError("not an svg")
    if len(svg_text) > MAX_SVG_CHARS:
        raise ValueError("svg too large")
    return cairosvg.svg2png(bytestring=svg_text.encode("utf-8"), output_width=output_width)
