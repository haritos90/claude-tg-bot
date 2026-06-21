"""#295: rasterize an ``<svg>`` diagram to PNG so chat replies can show diagrams (schematics,
charts, floor plans) as images. Claude has no image-generation model, but it produces clean
vector SVG, which is exactly right for a labeled schematic. Rendering uses ``cairosvg`` (pure
Python + the system ``libcairo2``); ``cairosvg`` parses via ``defusedxml``, so XML-entity bombs
are mitigated, and the size guard below bounds a pathological payload.

The caller renders off the event loop (``asyncio.to_thread``) and, on any failure, falls back to
sending the raw ``.svg`` as a document so the diagram is never lost.

#300 (security): the SVG bytes are attacker-steerable (a chat-only user can make the model emit
any SVG). cairosvg's *unsafe* path would ``urlopen`` any ``file://`` / ``http(s)://`` resource the
SVG references — on the HOST, outside the per-session jail — an SSRF (cloud-metadata) + local-file
read. We render through ``PNGSurface.convert`` with an EXPLICIT ``url_fetcher`` (``safe_fetch`` =
``data:`` URIs only) and ``unsafe=False``, so external fetching is impossible regardless of any
future change to cairosvg's default fetcher. (``svg2png`` itself can't forward ``url_fetcher``.)
"""
from __future__ import annotations

import math
import re

from cairosvg.surface import PNGSurface
from cairosvg.url import safe_fetch  # data:-only fetcher; non-data URLs -> empty 1x1 svg

# Guard: ignore an absurdly large SVG payload (a diagram is a few KB; this caps a runaway).
MAX_SVG_CHARS = 200_000
# Target raster width in px; height scales with the SVG's own aspect ratio / viewBox.
DEFAULT_WIDTH = 1000
# #300 (P3): bound the raster so a pathological aspect ratio (e.g. viewBox 1x40000) can't
# allocate hundreds of MB even when it stays under cairo's per-dimension limit. 4M px RGBA
# ~= 16 MB, ample for a 1000-px-wide diagram up to ~4000 px tall.
MAX_RASTER_PX = 4_000_000
# Per-dimension ceiling, safely under cairo's ~32767 hard limit (it raises above that). The
# area cap alone can still yield a thin-but-tall raster whose single dimension blows that limit.
MAX_RASTER_DIM = 16_384

_SVG_TAG_RE = re.compile(r"<svg\b[^>]*>", re.IGNORECASE | re.DOTALL)
_VIEWBOX_RE = re.compile(
    r"viewBox\s*=\s*[\"']\s*[-\d.eE]+\s+[-\d.eE]+\s+([-\d.eE]+)\s+([-\d.eE]+)", re.IGNORECASE
)
_NUM_RE = re.compile(r"[-+]?[\d.]+(?:[eE][-+]?\d+)?")


def _attr_num(tag: str, name: str) -> float | None:
    """Leading numeric value of attribute ``name`` (ignoring a unit suffix like ``px``)."""
    m = re.search(name + r"\s*=\s*[\"']([^\"']+)[\"']", tag, re.IGNORECASE)
    if not m:
        return None
    n = _NUM_RE.match(m.group(1).strip())
    try:
        return float(n.group(0)) if n else None
    except ValueError:
        return None


def _intrinsic_aspect(svg_text: str) -> tuple[float, float] | None:
    """Cheap (regex) read of the SVG's intrinsic (width, height) for the area cap — viewBox
    preferred, else the width/height attributes. ``None`` when undeterminable (then we render
    with width only and lean on cairo's per-dimension limit)."""
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
    """Render an ``<svg>`` string to PNG bytes. Raises ``ValueError`` on missing/oversized
    input and propagates any cairosvg parse/render error so the caller can fall back."""
    if not svg_text or "<svg" not in svg_text.lower():
        raise ValueError("not an svg")
    if len(svg_text) > MAX_SVG_CHARS:
        raise ValueError("svg too large")
    # #300 (P3): clamp only when the estimated raster would blow the budget, so the common case
    # keeps output_height=None and cairosvg derives the correct aspect (no distortion). When the
    # cap kicks in the input is a runaway anyway, so a tiny aspect inaccuracy is irrelevant.
    out_w, out_h = output_width, None
    aspect = _intrinsic_aspect(svg_text)
    if aspect:
        w, h = aspect
        est_h = output_width * h / w
        if output_width * est_h > MAX_RASTER_PX:
            scale = math.sqrt(MAX_RASTER_PX / (output_width * est_h))
            # Clamp each dimension too: a thin/tall fit-to-area result can still exceed cairo's
            # per-dimension limit (which would raise instead of rendering). Clamping only shrinks.
            out_w = min(MAX_RASTER_DIM, max(1, int(output_width * scale)))
            out_h = min(MAX_RASTER_DIM, max(1, int(est_h * scale)))
    # #300 (security): explicit data:-only fetcher + unsafe=False -> no external fetch ever.
    return PNGSurface.convert(
        bytestring=svg_text.encode("utf-8"),
        output_width=out_w,
        output_height=out_h,
        unsafe=False,
        url_fetcher=safe_fetch,
    )
