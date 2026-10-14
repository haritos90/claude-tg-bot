"""Rasterize an SVG diagram to PNG for chat replies.

- uses `cairosvg`, which needs system `libcairo2`
- caller renders off-loop; on failure sends raw `.svg`
- SVG is model-steerable: external fetching must be impossible
- renders via `PNGSurface.convert` with a `data:`-only `url_fetcher`
- `unsafe=False` blocks SSRF and local-file reads
"""
from __future__ import annotations

import math
import re

from cairosvg.surface import PNGSurface
from cairosvg.url import safe_fetch  # `data:` URIs only; others become blank

# Ignore absurdly large SVG payloads; diagrams are a few KB.
MAX_SVG_CHARS = 200_000
# Target raster width in px; height follows aspect ratio.
DEFAULT_WIDTH = 1000
# Cap raster area so odd aspect ratios stay small.
# - 4M px RGBA is about 16 MB
# - enough for 1000 px wide, about 4000 px tall
MAX_RASTER_PX = 4_000_000
# Per-dimension ceiling, safely under cairo's 32767 hard limit.
# - the area cap alone allows thin, tall rasters
MAX_RASTER_DIM = 16_384

_SVG_TAG_RE = re.compile(r"<svg\b[^>]*>", re.IGNORECASE | re.DOTALL)
_VIEWBOX_RE = re.compile(
    r"viewBox\s*=\s*[\"']\s*[-\d.eE]+\s+[-\d.eE]+\s+([-\d.eE]+)\s+([-\d.eE]+)", re.IGNORECASE
)
_NUM_RE = re.compile(r"[-+]?[\d.]+(?:[eE][-+]?\d+)?")


def _attr_num(tag: str, name: str) -> float | None:
    """Leading numeric value of attribute `name`, ignoring unit suffix."""
    m = re.search(name + r"\s*=\s*[\"']([^\"']+)[\"']", tag, re.IGNORECASE)
    if not m:
        return None
    n = _NUM_RE.match(m.group(1).strip())
    try:
        return float(n.group(0)) if n else None
    except ValueError:
        return None


def _intrinsic_aspect(svg_text: str) -> tuple[float, float] | None:
    """Cheap regex read of the SVG's intrinsic size.

    - prefers viewBox, else width/height attributes
    - `None` when undeterminable; then render by width only
    """
    m = _SVG_TAG_RE.search(svg_text)
    if not m:
        return None
    tag = m.group(0)
    vb = _VIEWBOX_RE.search(tag)
    if vb:
        try:
            w, h = float(vb.group(1)), float(vb.group(2))
            if w > 0 and h > 0:
                return w, h
        except ValueError:
            pass
    w, h = _attr_num(tag, "width"), _attr_num(tag, "height")
    if w and h and w > 0 and h > 0:
        return w, h
    return None


def render_svg_png(svg_text: str, output_width: int = DEFAULT_WIDTH) -> bytes:
    """Render an SVG string to PNG bytes.

    - raises `ValueError` on missing or oversized input
    - propagates cairosvg errors so the caller can fall back
    """
    if not svg_text or "<svg" not in svg_text.lower():
        raise ValueError("not an svg")
    if len(svg_text) > MAX_SVG_CHARS:
        raise ValueError("svg too large")
    # Clamp only when the estimated raster exceeds the budget.
    # - common case keeps aspect ratio undistorted
    # - a runaway input tolerates slight aspect error
    out_w, out_h = output_width, None
    aspect = _intrinsic_aspect(svg_text)
    if aspect:
        w, h = aspect
        est_h = output_width * h / w
        if output_width * est_h > MAX_RASTER_PX:
            scale = math.sqrt(MAX_RASTER_PX / (output_width * est_h))
            # Also clamp each dimension; cairo raises above its limit.
            out_w = min(MAX_RASTER_DIM, max(1, int(output_width * scale)))
            out_h = min(MAX_RASTER_DIM, max(1, int(est_h * scale)))
    # Explicit `data:`-only fetcher and `unsafe=False`: no external fetch.
    return PNGSurface.convert(
        bytestring=svg_text.encode("utf-8"),
        output_width=out_w,
        output_height=out_h,
        unsafe=False,
        url_fetcher=safe_fetch,
    )
