"""Render a parsed markdown table to a PNG image.

- Telegram has no table; wide monospace grids wrap badly
- uses DejaVu Sans Mono for full Cyrillic coverage
- narrow tables keep the text grid
- needs `fonts-dejavu-core`; else falls back to PIL default font
"""
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
_FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"

_BG = (255, 255, 255)
_HEADER_BG = (234, 238, 243)
_GRID = (203, 209, 216)
_TEXT = (24, 26, 28)


def _load_font(path: str, size: int):
    """Load DejaVu Sans Mono, else PIL's default font.

    - rendering never hard-fails without the font
    - default font is proportional, so columns misalign slightly
    """
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        try:
            return ImageFont.load_default(size)
        except TypeError:  # old Pillow: `load_default()` takes no size
            return ImageFont.load_default()


def render_table_png(rows: list[list[str]], font_size: int = 28) -> bytes:
    """Draw rows as a bordered table PNG; return bytes.

    - first row is the header: bold and shaded
    - cells are plain text, already emphasis-stripped
    """
    font = _load_font(_FONT, font_size)
    bold = _load_font(_FONT_BOLD, font_size)
    ncol = max(len(r) for r in rows)
    rows = [list(r) + [""] * (ncol - len(r)) for r in rows]

    char_w = font.getlength("M")                 # monospace: every glyph this wide
    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    pad_x, pad_y = round(char_w * 0.7), round(line_h * 0.35)

    col_chars = [max(len(r[c]) for r in rows) for c in range(ncol)]
    col_w = [round(n * char_w) + 2 * pad_x for n in col_chars]
    row_h = line_h + 2 * pad_y
    width = sum(col_w) + 1
    height = row_h * len(rows) + 1

    img = Image.new("RGB", (width, height), _BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width, row_h], fill=_HEADER_BG)

    y = 0
    for ri, r in enumerate(rows):
        x = 0
        glyph = bold if ri == 0 else font
        for c in range(ncol):
            draw.text((x + pad_x, y + pad_y), r[c], fill=_TEXT, font=glyph)
            x += col_w[c]
        y += row_h

    x = 0
    for c in range(ncol + 1):
        draw.line([(x, 0), (x, height)], fill=_GRID, width=1)
        if c < ncol:
            x += col_w[c]
    y = 0
    for ri in range(len(rows) + 1):
        draw.line([(0, y), (width, y)], fill=_GRID, width=1)
        if ri < len(rows):
            y += row_h

    buf = BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
