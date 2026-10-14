"""Telegram formatting helpers.

- Safe message limit is 3900, under Telegram's 4096
- Public: escape_html, md_to_html, split_message, should_send_as_file, as_document
"""

from __future__ import annotations

import json
import re

from aiogram.types import BufferedInputFile

SAFE_LIMIT = 3900
# Telegram's hard per-message limit.
# - escaping can expand chunks past it
# - render_within_limit re-splits to stay under
HARD_LIMIT = 4096
# Rich messages allow up to 32768 UTF-8 characters.
# - far above the classic 4096
RICH_LIMIT = 32768
# A native rich table renders at most 20 columns.
# - wider tables go to the PNG path
RICH_TABLE_MAX_COLS = 20
# Above this length, prefer sending a document.
FILE_THRESHOLD = SAFE_LIMIT * 3


# ---- Escaping ----
def escape_html(s: str) -> str:
    """Escape the three characters Telegram HTML treats specially.

    - Escape & first to avoid double-escaping
    """
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ---- Markdown to Telegram HTML ----
# - Escape everything first, then re-apply a safe subset
# - only deliberately inserted tags can appear in output
# - Tags: b, i, u, s, code, pre, a, spoiler, blockquote

_FENCE_RE = re.compile(
    r"```[ \t]*([A-Za-z0-9_+\-.#]*)[ \t]*\r?\n(.*?)```",
    re.DOTALL,
)
# Same as the fence regex, for tilde fences.
_FENCE_TILDE_RE = re.compile(
    r"~~~[ \t]*([A-Za-z0-9_+\-.#]*)[ \t]*\r?\n(.*?)~~~",
    re.DOTALL,
)
_FENCE_NOLANG_RE = re.compile(r"```(.*?)```", re.DOTALL)
# One full fenced code block, language optional.
# - needs a newline after opener; inline spans don't match
_CODE_FENCE_BLOCK_RE = re.compile(
    r"```[ \t]*[A-Za-z0-9_+\-.#]*[ \t]*\r?\n.*?```"
    r"|~~~[ \t]*[A-Za-z0-9_+\-.#]*[ \t]*\r?\n.*?~~~",
    re.DOTALL,
)
# A fence open or close line, backtick or tilde.
# - lets demote_headings skip comments inside code
_FENCE_TOGGLE_RE = re.compile(r"^[ \t]*(?:```|~~~)")
_INLINE_CODE_RE = re.compile(r"`([^`\n]+?)`")
_BOLD_STAR_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_BOLD_USCORE_RE = re.compile(r"__(.+?)__", re.DOTALL)
_ITALIC_STAR_RE = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", re.DOTALL)
_ITALIC_USCORE_RE = re.compile(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])", re.DOTALL)
# Link and ATX header patterns; placeholder token for stash.
_LINK_RE = re.compile(r"\[([^\]\n]+)\]\(\s*([^)\s]+)\s*\)")
_ATX_HEADER_RE = re.compile(r"(?m)^[ \t]{0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_PH_RE = re.compile(r"\x00PH(\d+)\x00")
# Table separator row, in pipe or grid form.
# - junction character is pipe or plus
# - some models drop outer pipes, using plus junctions
_TABLE_SEP_RE = re.compile(
    r"^[ \t]*[|+]?[ \t]*:?-{2,}:?[ \t]*(?:[|+][ \t]*:?-{2,}:?[ \t]*)+[|+]?[ \t]*$"
)

# Max grid width in characters that fits a phone.
# - wider tables render as vertical cards instead
_TABLE_GRID_MAX_WIDTH = 46
# Emphasis markers dropped from table cells, keeping inner text.
# - pre grids are monospace, so raw markers would show
_CELL_EMPH_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__|~~(.+?)~~|`([^`]+)`")

# Strikethrough pattern, GitHub style.
# - guarded so ~~~ code fences never match
_STRIKE_RE = re.compile(r"(?<!~)~~(?!~)([^\n]+?)(?<!~)~~(?!~)")
# Spoiler pattern requiring non-space inner edges.
# - keeps logical-or like a || b literal
_SPOILER_RE = re.compile(r"(?<!\|)\|\|(?!\|)(?=\S)([^\n]+?)(?<=\S)\|\|(?!\|)")
# A blockquote line after escaping, optional single space.
_QUOTE_LINE_RE = re.compile(r"^&gt;[ \t]?(.*)$")
# Quote runs longer than this become expandable blockquotes.
# - shorter runs stay always-open
# - None never collapses
EXPANDABLE_BLOCKQUOTE_MIN_LINES: int | None = 10


def _table_disp_len(s: str) -> int:
    """Visible width of an HTML-escaped cell."""
    return len(s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">"))


def _strip_cell_emphasis(s: str) -> str:
    """Drop markdown emphasis markers from a table cell.

    - keeps inner text; raw markers would leak
    """
    prev = None
    out = s
    while prev != out:
        prev = out
        out = _CELL_EMPH_RE.sub(lambda m: next(g for g in m.groups() if g is not None), out)
    return out


def _split_table_row(line: str) -> list[str]:
    """Split a pipe row into trimmed, emphasis-stripped cells."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [_strip_cell_emphasis(c.strip()) for c in s.split("|")]


def _render_table_pre(rows: list[list[str]]) -> str:
    """Render escaped rows as a column-aligned pre grid.

    - Telegram HTML has no table tag
    """
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    widths = [max(_table_disp_len(r[c]) for r in rows) for c in range(ncol)]

    def _fmt(r: list[str]) -> str:
        return " | ".join(
            r[c] + " " * (widths[c] - _table_disp_len(r[c])) for c in range(ncol)
        )

    body = [_fmt(rows[0]), "-+-".join("-" * w for w in widths)]
    body += [_fmt(r) for r in rows[1:]]
    return "<pre>" + "\n".join(body) + "</pre>"


def _render_table_cards(rows: list[list[str]]) -> str:
    """Render a wide table as vertical per-row cards.

    - first column is a bold title
    - other columns become label: value lines
    """
    ncol = max(len(r) for r in rows)
    headers = rows[0] + [""] * (ncol - len(rows[0]))
    blocks: list[str] = []
    for r in rows[1:]:
        r = r + [""] * (ncol - len(r))
        title = r[0].strip() or "—"
        lines = [f"▸ <b>{title}</b>"]
        for c in range(1, ncol):
            val = r[c].strip()
            if not val:
                continue
            label = headers[c].strip()
            lines.append(f"  <b>{label}:</b> {val}" if label else f"  {val}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _render_table_auto(rows: list[list[str]]) -> str:
    """Pick grid or cards layout by table width."""
    ncol = max(len(r) for r in rows)
    padded = [r + [""] * (ncol - len(r)) for r in rows]
    widths = [max(_table_disp_len(r[c]) for r in padded) for c in range(ncol)]
    grid_w = sum(widths) + 3 * (ncol - 1)
    if grid_w <= _TABLE_GRID_MAX_WIDTH or len(rows) < 2:
        return _render_table_pre(rows)
    return _render_table_cards(rows)


# A photo cannot live inside an HTML text message.

class TableImage:
    """A wide table to send as a PNG photo.

    - holds parsed, unescaped, emphasis-stripped rows
    """

    __slots__ = ("rows",)

    def __init__(self, rows: list[list[str]]):
        self.rows = rows


def _table_is_wide(rows: list[list[str]]) -> bool:
    """True when the grid is wider than a phone."""
    if len(rows) < 2:
        return False
    ncol = max(len(r) for r in rows)
    padded = [r + [""] * (ncol - len(r)) for r in rows]
    widths = [max(_table_disp_len(r[c]) for r in padded) for c in range(ncol)]
    return sum(widths) + 3 * (ncol - 1) > _TABLE_GRID_MAX_WIDTH


def split_image_tables(text: str):
    """Split model text into text runs and wide tables.

    - narrow tables stay inside the text runs
    - returns [text] when there are no wide tables
    """
    if "|" not in text:
        return [text]
    lines = text.split("\n")
    items: list = []
    buf: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        nxt = lines[i + 1] if i + 1 < n else ""
        if "|" in lines[i] and _TABLE_SEP_RE.match(nxt):
            rows = [_split_table_row(lines[i])]
            j = i + 2
            while j < n and "|" in lines[j] and lines[j].strip():
                rows.append(_split_table_row(lines[j]))
                j += 1
            if _table_is_wide(rows):
                if buf:
                    items.append("\n".join(buf))
                    buf = []
                items.append(TableImage(rows))
            else:
                buf.extend(lines[i:j])          # narrow: keep raw lines
            i = j
        else:
            buf.append(lines[i])
            i += 1
    if buf:
        items.append("\n".join(buf))
    return items or [text]


def _tables_to_pre(text: str, stash) -> str:
    """Replace markdown tables with stashed aligned pre grids."""
    if "|" not in text:
        return text
    lines = text.split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        nxt = lines[i + 1] if i + 1 < n else ""
        if "|" in lines[i] and _TABLE_SEP_RE.match(nxt):
            rows = [_split_table_row(lines[i])]
            j = i + 2
            while j < n and "|" in lines[j] and lines[j].strip():
                rows.append(_split_table_row(lines[j]))
                j += 1
            out.append(stash(_render_table_pre(rows)))
            i = j
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


# Streaming tables: draft and final share one renderer.

# Partial table separator still being typed.
# - clipped from streaming drafts
_PARTIAL_SEP_RE = re.compile(r"^[ \t]*[|+]?[ \t:|+-]*-[ \t:|+-]*$")


def clip_partial_table(text: str) -> str:
    """Clip a half-typed trailing table line from a draft.

    - every draft frame stays a valid prefix of the final
    - only the trailing partial line is touched
    - no-op without a table or with trailing newline
    """
    if "|" not in text or text.endswith("\n"):
        return text
    lines = text.split("\n")
    last = lines[-1]
    is_partial_row = "|" in last
    is_partial_sep = bool(_PARTIAL_SEP_RE.match(last))
    if not (is_partial_row or is_partial_sep):
        return text
    above = lines[:-1]
    # Walk up the contiguous table-like block.
    k = len(above)
    while k > 0 and ("|" in above[k - 1] or _TABLE_SEP_RE.match(above[k - 1])):
        k -= 1
    block = above[k:]
    established = any(_TABLE_SEP_RE.match(line) for line in block)   # header and separator seen
    header_then_partial_sep = is_partial_sep and bool(block) and "|" in block[-1]
    if established or header_then_partial_sep:
        return "\n".join(above)
    return text


def hold_open_table(text: str) -> tuple[str, int | None]:
    """Hold back a still-open trailing table from draft frames.

    - iOS client does not reconcile cells added on view reuse
    - a table growing row by row would show empty rows
    - returns (text before table, data rows) or (text, None)
    - a blank line closes a table; fenced code ignored
    """
    if "|" not in text:
        return text, None
    lines = text.split("\n")
    partial_last = not text.endswith("\n")
    if not partial_last:
        lines = lines[:-1]  # empty string after final newline
    # Trailing non-blank lines; a blank line closes tables.
    start = len(lines)
    while start > 0 and lines[start - 1].strip():
        start -= 1
    block = lines[start:]
    if not block:
        return text, None
    # A table inside an open code fence is code.
    in_fence = False
    for line in lines[:start]:
        if _FENCE_TOGGLE_RE.match(line):
            in_fence = not in_fence
    if in_fence:
        return text, None
    sep = next((i for i, line in enumerate(block) if _TABLE_SEP_RE.match(line)), None)
    if sep is not None and sep >= 1:
        head = sep - 1                      # header sits right above separator
    else:
        head = next((i for i, line in enumerate(block) if line.lstrip().startswith("|")), None)
        if head is None:
            return text, None               # no table shape in trailing block
    if any(_FENCE_TOGGLE_RE.match(line) for line in block[:head]):
        return text, None                   # fence opened before this block
    rows = 0
    if sep is not None and sep >= 1:
        rows = len(block) - sep - 1 - (1 if partial_last else 0)
    kept = lines[:start] + block[:head]
    return "\n".join(kept), max(0, rows)


def demote_headings(text: str) -> str:
    """Demote ATX headings to bold for rich markdown.

    - avoids a distinct heading font beside body text
    - adds nbsp spacer paragraphs above and below headings
    - skips fenced code; line-local so drafts match final
    - below spacer deferred until content follows
    """
    if "#" not in text:
        return text
    out: list[str] = []
    in_fence = False
    # A just-demoted heading awaits its below spacer.
    # - added once real content follows
    pending_after = False

    def _add_spacer() -> None:
        # nbsp paragraph is the visual gap.
        # - a blank line alone is trimmed
        # - deduped: adjacent headings share one gap
        if next((x for x in reversed(out) if x != ""), None) == "\u00A0":
            return
        # Collapse pre-existing blank runs above a heading first.
        # - yields a single gap above
        while out and out[-1] == "":
            out.pop()
        if out:
            out.append("")
        out.append("\u00A0")
        out.append("")

    for line in text.split("\n"):
        # Defer the heading's below spacer until content follows.
        # - swallows the model's own blank lines
        # - no floating spacer at the draft frontier
        if pending_after:
            if line == "":
                continue
            _add_spacer()
            pending_after = False
        if _FENCE_TOGGLE_RE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        m = _ATX_HEADER_RE.match(line) if not in_fence else None
        if m is None:
            out.append(line)
            continue
        # nbsp spacer above (not first content) and below heading.
        if out:
            _add_spacer()
        out.append("**" + m.group(2).replace("**", "").replace("__", "") + "**")
        pending_after = True            # below spacer added when content arrives
    return "\n".join(out)


# ---- Native Telegram tables ----
# - Rich messages render table, tr, th, td natively
# - the client lays out and side-scrolls columns
# - PNG and pre-grid paths remain only as fallback

# Inline cell emphasis kept for native cells.
# - bold and inline code, paired markers only
_CELL_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_CELL_CODE_RE = re.compile(r"`([^`]+)`")


class RichTable:
    """A markdown table to send as a native Telegram table.

    - holds raw rows, header first, plus column alignments
    """

    __slots__ = ("rows", "aligns")

    def __init__(self, rows: list[list[str]], aligns: list | None = None):
        self.rows = rows
        self.aligns = aligns or []


def _split_table_row_raw(line: str) -> list[str]:
    """Split a pipe row into trimmed cells keeping emphasis."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _parse_table_aligns(sep_line: str) -> list:
    """Parse a separator row into per-column alignments.

    - values: left, center, right, or None
    """
    out: list = []
    for c in _split_table_row_raw(sep_line):
        c = c.strip()
        left, right = c.startswith(":"), c.endswith(":")
        out.append("center" if left and right else "right" if right else "left" if left else None)
    return out


def _cell_rich_html(cell: str) -> str:
    """Escape a cell, then restore bold and inline code tags."""
    s = escape_html(cell.strip())
    s = _CELL_CODE_RE.sub(lambda m: f"<code>{m.group(1)}</code>", s)
    s = _CELL_BOLD_RE.sub(lambda m: f"<b>{m.group(1) or m.group(2)}</b>", s)
    return s


def table_to_rich_html(
    rows: list[list[str]],
    aligns: list | None = None,
    *,
    bordered: bool = True,
    striped: bool = True,
    caption: str | None = None,
) -> str:
    """Render parsed rows as a native Telegram table.

    - first row becomes th header cells
    - bordered and zebra-striped, with per-column alignment
    """
    rows = [r for r in rows if r is not None]
    if not rows:
        return ""
    ncol = max((len(r) for r in rows), default=0)
    attrs = []
    if bordered:
        attrs.append("bordered")
    if striped:
        attrs.append("striped")
    parts = ["<table" + ((" " + " ".join(attrs)) if attrs else "") + ">"]
    if caption:
        parts.append(f"<caption>{_cell_rich_html(caption)}</caption>")
    for ri, r in enumerate(rows):
        cells = list(r) + [""] * (ncol - len(r))
        tag = "th" if ri == 0 else "td"
        row = ["<tr>"]
        for c in range(ncol):
            a = aligns[c] if aligns and c < len(aligns) else None
            align_attr = f' align="{a}"' if a else ""
            row.append(f"<{tag}{align_attr}>{_cell_rich_html(cells[c])}</{tag}>")
        row.append("</tr>")
        parts.append("".join(row))
    parts.append("</table>")
    return "".join(parts)


def split_rich_tables(text: str):
    """Split model text into text runs and native tables.

    - every table is extracted, narrow or wide
    - returns [text] when there is no table
    """
    if "|" not in text:
        return [text]
    lines = text.split("\n")
    items: list = []
    buf: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        nxt = lines[i + 1] if i + 1 < n else ""
        if "|" in lines[i] and _TABLE_SEP_RE.match(nxt):
            rows = [_split_table_row_raw(lines[i])]
            aligns = _parse_table_aligns(nxt)
            j = i + 2
            while j < n and "|" in lines[j] and lines[j].strip():
                rows.append(_split_table_row_raw(lines[j]))
                j += 1
            if len(rows) >= 1:
                if buf:
                    items.append("\n".join(buf))
                    buf = []
                items.append(RichTable(rows, aligns))
            i = j
        else:
            buf.append(lines[i])
            i += 1
    if buf:
        items.append("\n".join(buf))
    return items or [text]


def table_col_count(rows: list[list[str]]) -> int:
    """Column count: the widest row's cell count."""
    return max((len(r) for r in rows), default=0)


# Glyphs for task-list card statuses.
_TODO_GLYPH = {"completed": "✅", "in_progress": "🔄", "pending": "⬜"}
_TODO_CELL_MAX = 90  # cap task lines for compactness


def summarize_todos(todos: list) -> tuple[int, int, int, str]:
    """Turn TodoWrite todos into total, done, open, and body.

    - body is one glyph-prefixed line per task
    - blank or invalid entries are skipped
    """
    lines: list[str] = []
    done = 0
    for t in todos or []:
        if not isinstance(t, dict):
            continue
        status = str(t.get("status") or "pending")
        content = str(t.get("content") or t.get("activeForm") or "").strip()
        if not content:
            continue
        content = content.replace("\n", " ")
        if len(content) > _TODO_CELL_MAX:
            content = content[: _TODO_CELL_MAX - 1] + "…"
        if status == "completed":
            done += 1
        lines.append(f"{_TODO_GLYPH.get(status, '⬜')} {content}")
    total = len(lines)
    # Join with a markdown hard break, not bare newline.
    # - a single newline is a soft break (space)
    # - soft breaks would collapse glyph lines onto one
    return total, done, total - done, "  \n".join(lines)


# Sentinel marking where a wide table was removed.
# - NUL never appears in model text
# - caller swaps it for a localized note
WIDE_TABLE_TOKEN = "\x00WIDE_TABLE\x00"


def extract_wide_tables(text: str, max_cols: int = RICH_TABLE_MAX_COLS):
    """Extract tables wider than max_cols columns.

    - native rich tables cap at 20 columns
    - each wide table becomes WIDE_TABLE_TOKEN in place
    - returns (new_text, wide tables) in document order
    """
    if "|" not in text:
        return text, []
    lines = text.split("\n")
    out: list[str] = []
    wide: list[RichTable] = []
    i, n = 0, len(lines)
    while i < n:
        nxt = lines[i + 1] if i + 1 < n else ""
        if "|" in lines[i] and _TABLE_SEP_RE.match(nxt):
            rows = [_split_table_row_raw(lines[i])]
            aligns = _parse_table_aligns(nxt)
            j = i + 2
            while j < n and "|" in lines[j] and lines[j].strip():
                rows.append(_split_table_row_raw(lines[j]))
                j += 1
            if table_col_count(rows) > max_cols:
                wide.append(RichTable(rows, aligns))
                out.append(WIDE_TABLE_TOKEN)
            else:
                out.extend(lines[i:j])  # narrow: keep original markdown
            i = j
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out), wide


# SVG diagrams are rasterized to PNG and sent as photos.
# - Telegram can't render SVG inline
# - a localized note is left in place
SVG_TOKEN = "\x00SVG\x00"
# One combined pass, fenced alternative first.
# - fenced svg block consumed whole before raw match
# - single left-to-right sub keeps document order
_SVG_BLOCK_RE = re.compile(
    r"```[ \t]*(?:svg|xml|html)?[ \t]*\r?\n\s*(<svg\b.*?</svg>)\s*\r?\n?```"  # group 1: fenced
    r"|(<svg\b[^>]*>.*?</svg>)",                                              # group 2: raw
    re.DOTALL | re.IGNORECASE,
)


def extract_svgs(text: str):
    """Extract complete svg diagrams from text for rasterizing.

    - each is replaced in place by SVG_TOKEN
    - returns (new_text, svg strings) in document order
    """
    if "<svg" not in (text or "").lower():
        return text, []
    svgs: list[str] = []

    def _take(m) -> str:
        svgs.append((m.group(1) or m.group(2)).strip())  # fenced: inner svg; else raw svg
        return SVG_TOKEN

    out = _SVG_BLOCK_RE.sub(_take, text)
    return out, svgs


# Location blocks become real map pins.
# - fenced location JSON is pulled out and sent as sendLocation
# - venue card when a place name is given
# - replaced in place by LOCATION_TOKEN
# - pin is sent as its own message after the bubble
LOCATION_TOKEN = "\x00LOCATION\x00"
_LOCATION_BLOCK_RE = re.compile(
    # Require the contiguous location or geo fence.
    # - must agree with guards in extractor and streamer
    # - a space after backticks was rejected, leaking raw JSON
    r"```(?:location|geo)[ \t]*\r?\n(.*?)\r?\n?```",
    re.DOTALL | re.IGNORECASE,
)
# Location blocks nested in 4+ backtick fences are examples.
# - extract only top-level blocks
_OUTER_FENCE_RE = re.compile(r"(`{4,})[^\n]*\n.*?\n\1", re.DOTALL)
# Cap venue title and address lengths.
# - Telegram rejects over-long ones with a 400
_VENUE_TITLE_MAX = 256
_VENUE_ADDRESS_MAX = 256


def _coerce_location(obj):
    """Validate a parsed location object into a normalized dict.

    - accepts lat/latitude and lon/lng/longitude, numbers or numeric strings
    - title and address optional; both make a venue
    - invalid coordinates return None
    """
    if not isinstance(obj, dict):
        return None
    lat = obj.get("lat", obj.get("latitude"))
    lon = obj.get("lon", obj.get("lng", obj.get("longitude")))
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    out = {"lat": lat, "lon": lon}
    # Only documented title and address keys are recognized.
    # - each capped to avoid a sendVenue 400
    title = obj.get("title")
    address = obj.get("address")
    if isinstance(title, str) and title.strip():
        out["title"] = title.strip()[:_VENUE_TITLE_MAX]
    if isinstance(address, str) and address.strip():
        out["address"] = address.strip()[:_VENUE_ADDRESS_MAX]
    return out


def extract_locations(text: str):
    """Extract location fenced blocks to send as map pins.

    - valid blocks are replaced in place by LOCATION_TOKEN
    - unparseable or out-of-range blocks stay verbatim
    - returns (new_text, locations) in document order
    """
    low = (text or "").lower()
    if "```location" not in low and "```geo" not in low:
        return text, []
    locs: list[dict] = []
    # Spans of enclosing 4+ backtick fences; contents are demos.
    outer = [(m.start(), m.end()) for m in _OUTER_FENCE_RE.finditer(text)]

    def _take(m) -> str:
        if any(a <= m.start() < b for a, b in outer):
            return m.group(0)  # nested in demo fence: leave verbatim
        try:
            obj = json.loads(m.group(1))
        except (ValueError, TypeError):
            return m.group(0)  # not JSON: leave block verbatim
        loc = _coerce_location(obj)
        if loc is None:
            return m.group(0)  # bad coordinates: leave as text
        locs.append(loc)
        return LOCATION_TOKEN

    out = _LOCATION_BLOCK_RE.sub(_take, text)
    return out, locs


# One regex over all out-of-band attachment tokens.
# - covers pins, svg diagrams, and wide tables
# - capture group keeps tokens when splitting
# - lets each attachment land where it sat in the text
_ATTACH_TOKEN_RE = re.compile(
    "(" + "|".join(re.escape(t) for t in (LOCATION_TOKEN, SVG_TOKEN, WIDE_TABLE_TOKEN)) + ")"
)


def split_on_attachment_tokens(text: str) -> list[str]:
    """Split text on attachment tokens, keeping the tokens.

    - even indices are prose, odd indices are tokens
    - no token returns a single-element list
    """
    return _ATTACH_TOKEN_RE.split(text or "")


def has_code_block(text: str) -> bool:
    """True if text contains a multi-line fenced code block."""
    return bool(_CODE_FENCE_BLOCK_RE.search(text or ""))


def split_code_blocks(text: str):
    """Split text into ordered text and code segments.

    - a code segment is a full fenced block
    - lets code go classic and the rest rich
    """
    if not has_code_block(text):
        return [("text", text)]
    out: list = []
    pos = 0
    for m in _CODE_FENCE_BLOCK_RE.finditer(text):
        if m.start() > pos:
            out.append(("text", text[pos:m.start()]))
        out.append(("code", m.group(0)))
        pos = m.end()
    if pos < len(text):
        out.append(("text", text[pos:]))
    return out or [("text", text)]


# ---- LaTeX to Unicode ----
# - Telegram can't render LaTeX; the model may still emit it
# - only unambiguous LaTeX syntax is rewritten
# - runs on non-code text only
# - prose like "$5 and $10" is untouched
_LATEX_SYMBOLS = {
    "times": "×", "cdot": "·", "div": "÷", "pm": "±", "mp": "∓",
    "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "neq": "≠", "ne": "≠",
    "approx": "≈", "equiv": "≡", "propto": "∝", "sim": "∼", "cong": "≅",
    "ll": "≪", "gg": "≫", "infty": "∞", "partial": "∂", "nabla": "∇",
    "sum": "∑", "prod": "∏", "int": "∫", "sqrt": "√", "deg": "°",
    "rightarrow": "→", "Rightarrow": "⇒", "leftarrow": "←", "Leftarrow": "⇐",
    "leftrightarrow": "↔", "to": "→", "mapsto": "↦", "implies": "⇒", "iff": "⇔",
    "ldots": "…", "cdots": "⋯", "dots": "…", "angle": "∠",
    "in": "∈", "notin": "∉", "subset": "⊂", "subseteq": "⊆", "supset": "⊃",
    "cup": "∪", "cap": "∩", "emptyset": "∅", "forall": "∀", "exists": "∃",
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "varepsilon": "ε", "zeta": "ζ", "eta": "η", "theta": "θ", "iota": "ι",
    "kappa": "κ", "lambda": "λ", "mu": "µ", "nu": "ν", "xi": "ξ", "rho": "ρ",
    "pi": "π", "sigma": "σ", "tau": "τ", "phi": "φ", "varphi": "φ", "chi": "χ",
    "psi": "ψ", "omega": "ω", "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ",
    "Lambda": "Λ", "Pi": "Π", "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
}
# Longest names first so longer commands win.
_LATEX_CMD_RE = re.compile(
    r"\\(" + "|".join(sorted(_LATEX_SYMBOLS, key=len, reverse=True)) + r")(?![A-Za-z])"
)
_SUP_SET = set("0123456789+-=()n")
_SUB_SET = set("0123456789+-=()")
_SUP_TAB = str.maketrans("0123456789+-=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")
_SUB_TAB = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")


def _script(s: str, charset: set, table: dict) -> str:
    """Translate to super/subscript, else a readable fallback.

    - unsupported chars get caret/underscore form, never dropped
    """
    if s and all(ch in charset for ch in s):
        return s.translate(table)
    return None  # caller decides the fallback


def _latex_to_unicode(s: str) -> str:
    if "\\" not in s and "$" not in s and "^" not in s and "_{" not in s:
        return s  # fast path: no LaTeX present

    def _unwrap_math(m: re.Match) -> str:
        inner = m.group(1)
        # Treat as math only with LaTeX-ish syntax.
        # - protects prose like "$5 and $10"
        return inner if re.search(r"[\\^{}]|_[\d{]", inner) else m.group(0)

    s = re.sub(r"\$\$(.+?)\$\$", _unwrap_math, s, flags=re.DOTALL)
    s = re.sub(r"\$([^$\n]+?)\$", _unwrap_math, s)
    s = re.sub(r"\\\((.+?)\\\)", r"\1", s, flags=re.DOTALL)
    s = re.sub(r"\\\[(.+?)\\\]", r"\1", s, flags=re.DOTALL)
    # Text-style commands become their inner text.
    s = re.sub(r"\\(?:text|mathrm|mathbf|mathit|operatorname)\s*\{([^{}]*)\}", r"\1", s)

    def _frac(m: re.Match) -> str:
        a, b = m.group(1).strip(), m.group(2).strip()
        wa = a if len(a) <= 1 else f"({a})"
        wb = b if len(b) <= 1 else f"({b})"
        return f"{wa}/{wb}"

    s = re.sub(r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", _frac, s)
    s = re.sub(
        r"\\sqrt\s*\{([^{}]*)\}",
        lambda m: ("√(" + m.group(1) + ")") if len(m.group(1)) > 1 else "√" + m.group(1),
        s,
    )
    s = re.sub(r"\\(?:left|right|,|;|!|quad|qquad)\s?", "", s)
    s = _LATEX_CMD_RE.sub(lambda m: _LATEX_SYMBOLS[m.group(1)], s)

    def _sup(m: re.Match) -> str:
        inner = m.group(1)
        return _script(inner, _SUP_SET, _SUP_TAB) or f"^({inner})"

    def _sub(m: re.Match) -> str:
        inner = m.group(1)
        return _script(inner, _SUB_SET, _SUB_TAB) or f"_({inner})"

    s = re.sub(r"\^\{([^{}]*)\}", _sup, s)
    s = re.sub(r"\^(\w)", lambda m: _script(m.group(1), _SUP_SET, _SUP_TAB) or m.group(0), s)
    s = re.sub(r"_\{([^{}]*)\}", _sub, s)
    # Bare x_2 becomes subscript only after alphanumerics.
    # - leaves markdown _italic_ untouched
    s = re.sub(
        r"(?<=[A-Za-z0-9])_(\d)",
        lambda m: _script(m.group(1), _SUB_SET, _SUB_TAB) or m.group(0),
        s,
    )
    return s


def _blockquotes_to_html(text: str) -> str:
    """Group runs of quote lines into blockquote blocks.

    - runs on escaped text after code and tables are stashed
    - Telegram blockquotes can't nest, so each run is one block
    - long runs become expandable blockquotes
    """
    if "&gt;" not in text:
        return text
    lines = text.split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        m = _QUOTE_LINE_RE.match(lines[i])
        if m is None:
            out.append(lines[i])
            i += 1
            continue
        inner = [m.group(1)]
        j = i + 1
        while j < n:
            mj = _QUOTE_LINE_RE.match(lines[j])
            if mj is None:
                break
            inner.append(mj.group(1))
            j += 1
        threshold = EXPANDABLE_BLOCKQUOTE_MIN_LINES
        expandable = threshold is not None and len(inner) > threshold
        tag = "<blockquote expandable>" if expandable else "<blockquote>"
        out.append(tag + "\n".join(inner) + "</blockquote>")
        i = j
    return "\n".join(out)


def md_to_html(text: str) -> str:
    """Convert a safe Markdown subset to Telegram HTML.

    - supports code, bold, italic, strike, spoiler, quotes
    - everything is escaped first
    - falls back to escaped plain text on failure
    """
    if not text:
        return ""
    try:
        # Escape everything up front.
        escaped = escape_html(text)

        # Stash fenced code behind opaque placeholders.
        # - later inline rules can't touch contents
        placeholders: list[str] = []

        def _stash(html_fragment: str) -> str:
            placeholders.append(html_fragment)
            # Placeholder token can't appear in escaped or user text.
            return f"\x00PH{len(placeholders) - 1}\x00"

        def _fence_sub(match: re.Match) -> str:
            lang = (match.group(1) or "").strip()
            body = match.group(2)
            # Strip the single trailing newline belonging to the fence.
            body = body.rstrip("\n")
            if lang:
                # Language label gives syntax highlighting.
                # - fence regex restricts language charset, so no extra escaping
                return _stash(
                    f'<pre><code class="language-{lang}">{body}</code></pre>'
                )
            return _stash(f"<pre>{body}</pre>")

        escaped = _FENCE_RE.sub(_fence_sub, escaped)
        # Tilde fences share the same group layout.
        escaped = _FENCE_TILDE_RE.sub(_fence_sub, escaped)

        # Fences without language, and inline triple-backtick form.
        def _fence_nolang_sub(match: re.Match) -> str:
            body = match.group(1).strip("\n")
            return _stash(f"<pre>{body}</pre>")

        escaped = _FENCE_NOLANG_RE.sub(_fence_nolang_sub, escaped)

        # Inline code becomes code tags, also stashed.
        def _inline_code_sub(match: re.Match) -> str:
            return _stash(f"<code>{match.group(1)}</code>")

        escaped = _INLINE_CODE_RE.sub(_inline_code_sub, escaped)

        # Tables become stashed aligned pre grids.
        escaped = _tables_to_pre(escaped, _stash)

        # ATX headers become bold lines.
        # - redundant inner bold markers are dropped
        escaped = _ATX_HEADER_RE.sub(
            lambda m: _stash("<b>" + m.group(2).replace("**", "").replace("__", "") + "</b>"),
            escaped,
        )

        # Links become anchor tags, stashed to protect URLs.
        def _link_sub(match: re.Match) -> str:
            label, url = match.group(1), match.group(2)
            if not re.match(r"(?:https?:|tg:|mailto:)", url):
                return match.group(0)  # not a real URL: keep literal
            return _stash(f'<a href="{url}">{label}</a>')

        escaped = _LINK_RE.sub(_link_sub, escaped)

        # Block quotes become blockquote tags.
        # - runs after code and tables are stashed
        # - runs before inline passes, which style quote contents
        escaped = _blockquotes_to_html(escaped)

        # LaTeX to Unicode on remaining non-code text.
        escaped = _latex_to_unicode(escaped)

        # Inline styles: bold, then strike and spoiler, italic last.
        # - italic's single marker is most fragile
        # - all may nest, including inside blockquotes
        escaped = _BOLD_STAR_RE.sub(r"<b>\1</b>", escaped)
        escaped = _BOLD_USCORE_RE.sub(r"<b>\1</b>", escaped)
        escaped = _STRIKE_RE.sub(r"<s>\1</s>", escaped)
        escaped = _SPOILER_RE.sub(r"<tg-spoiler>\1</tg-spoiler>", escaped)
        escaped = _ITALIC_STAR_RE.sub(r"<i>\1</i>", escaped)
        escaped = _ITALIC_USCORE_RE.sub(r"<i>\1</i>", escaped)

        # Restore stashed fragments in bounded passes.
        # - fragments may contain further placeholders
        # - bound prevents spinning or crashing on stray tokens
        def _restore(match: re.Match) -> str:
            idx = int(match.group(1))
            return placeholders[idx] if 0 <= idx < len(placeholders) else match.group(0)

        for _ in range(len(placeholders) + 1):
            if "\x00PH" not in escaped:
                break
            escaped = _PH_RE.sub(_restore, escaped)
        return escaped
    except Exception:
        # Never let formatting crash a send.
        # - fall back to escaped plain text
        return escape_html(text)


# Empty rendered code box: pre with no inner text.
# - comes from hard-cutting a very long line in a fence
# - a blank tap-to-copy box that must not be sent
_EMPTY_RENDER_RE = re.compile(
    r"\A<pre>(?:<code(?:\s[^>]*)?>\s*</code>)?</pre>\Z"
)


def is_empty_render(html: str) -> bool:
    """True when html is an empty code box.

    - matches empty pre, with or without code attributes
    - comes from hard-cutting a long line inside a fence
    - renders a blank tap-to-copy box; must be skipped
    """
    if not html:
        return False
    return _EMPTY_RENDER_RE.match(html.strip()) is not None


# ---- Splitting ----
def split_message(text: str, limit: int = SAFE_LIMIT) -> list[str]:
    """Split text into chunks no longer than limit.

    - prefers paragraph, then line boundaries
    - a single over-long line is hard-cut
    - empty input returns [""]
    """
    if limit <= 0:
        limit = SAFE_LIMIT
    if text is None or text == "":
        return [""]
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""

    def _flush() -> None:
        nonlocal current
        if current:
            chunks.append(current)
            current = ""

    # Split into lines, preserving structure.
    # - each piece carries its newline, so chunks rejoin exactly
    lines = text.split("\n")
    for i, line in enumerate(lines):
        piece = line if i == 0 else "\n" + line

        # Hard-cut a line longer than the limit.
        # - first segment keeps the leading newline for round-trip
        if len(piece) > limit:
            _flush()
            for start in range(0, len(piece), limit):
                chunks.append(piece[start : start + limit])
            continue

        if len(current) + len(piece) <= limit:
            current += piece
        else:
            # Chunk is full: carry this piece to the next.
            # - keeps the separating newline
            _flush()
            current = piece

    _flush()
    if not chunks:
        return [""]
    return chunks


_FENCE_LINE_RE = re.compile(r"^[ \t]*```([A-Za-z0-9_+\-.#]*)[ \t]*$")


def split_markdown(text: str, limit: int = SAFE_LIMIT) -> list[str]:
    """Split raw Markdown, repairing fences that straddle chunks.

    - close an open fence per chunk, reopen with same language
    - raw splitting keeps md_to_html from seeing cut tags
    """
    # Reserve headroom for added fence markers.
    # - reopen line plus closing line must fit the limit
    inner_limit = max(1, limit - 24)
    chunks = split_message(text, limit=inner_limit)
    if len(chunks) <= 1:
        return chunks

    repaired: list[str] = []
    open_lang: str | None = None  # language of a carried-over fence
    for chunk in chunks:
        prefix = ""
        if open_lang is not None:
            # Reopen the fence carried from the previous chunk.
            prefix = f"```{open_lang}\n"

        # Track fence state line by line.
        # - starts from the carried-over state
        in_fence = open_lang is not None
        lang_here = open_lang
        for line in chunk.split("\n"):
            m = _FENCE_LINE_RE.match(line)
            if m:
                if in_fence:
                    in_fence = False
                    lang_here = None
                else:
                    in_fence = True
                    lang_here = m.group(1) or ""

        body = prefix + chunk
        if in_fence:
            # Chunk ends inside a fence: close it.
            # - remember language so the next chunk reopens
            if not body.endswith("\n"):
                body += "\n"
            body += "```"
            open_lang = lang_here or ""
        else:
            open_lang = None
        repaired.append(body)

    return repaired


def repair_fences_across_tokens(parts: list[str]) -> list[str]:
    """Repair fences cut by attachment tokens inside code blocks.

    - close open fence at run end, reopen on next
    - even indices are prose runs; odd are sentinels, untouched
    - balanced runs are returned unchanged
    - token flush with closing fence drops the empty reopen
    - only triple-backtick fences are handled
    """
    out = list(parts)
    open_lang: str | None = None  # fence language carried across tokens
    for i in range(0, len(out), 2):  # prose runs only; sentinels untouched
        chunk = out[i]
        if not chunk.strip():
            continue  # empty prose run: carry fence state
        prefix = f"```{open_lang}\n" if open_lang is not None else ""
        in_fence = open_lang is not None
        lang_here = open_lang
        if in_fence:
            # Token flush with closing fence would make blank code box.
            # - drop the reopen and that closing line
            lines = chunk.split("\n")
            first = next((j for j, ln in enumerate(lines) if ln.strip()), None)
            if first is not None and _FENCE_LINE_RE.match(lines[first]):
                chunk = "\n".join(lines[:first] + lines[first + 1 :])
                prefix, in_fence, lang_here = "", False, None
        for line in chunk.split("\n"):
            m = _FENCE_LINE_RE.match(line)
            if m:
                in_fence, lang_here = (False, None) if in_fence else (True, m.group(1) or "")
        body = prefix + chunk
        if in_fence:  # ends inside fence: close it
            if not body.endswith("\n"):
                body += "\n"
            body += "```"
            open_lang = lang_here or ""
        else:
            open_lang = None
        out[i] = body
    return out


def _tg_len(s: str) -> int:
    """Length in UTF-16 code units, as Telegram measures.

    - emoji are one code point but two units
    """
    return len(s.encode("utf-16-le")) // 2


def render_within_limit(raw: str, hard_limit: int = HARD_LIMIT) -> list[str]:
    """Render a raw chunk to HTML within Telegram's limit.

    - escaping can expand a chunk past 4096
    - on overflow, re-split the raw source smaller
    - a hard-cut floor guarantees termination
    """
    html = md_to_html(raw) or "…"
    # Measure UTF-16 code units, not code points.
    # - emoji near 4096 would otherwise be rejected
    if _tg_len(html) <= hard_limit:
        return [html]
    # Re-split the raw source with a shrinking budget.
    raw_limit = max(256, len(raw) // 2)
    while raw_limit >= 256:
        pieces = split_markdown(raw, limit=raw_limit)
        if len(pieces) > 1:
            rendered = [md_to_html(p) or "…" for p in pieces]
            if all(_tg_len(h) <= hard_limit for h in rendered):
                return rendered
        raw_limit //= 2
    # Last resort: hard-cut the raw text.
    # - escaping happens first, so cuts yield valid HTML
    # - shrink the step until every piece fits
    # - re-verify rather than assume the escaping ratio
    step = max(64, hard_limit // 6)
    while step >= 1:
        out = [md_to_html(raw[i : i + step]) or "…" for i in range(0, len(raw), step)]
        if all(_tg_len(h) <= hard_limit for h in out):
            return out or ["…"]
        # Halve, landing on the 64 floor, then shrink to 1.
        # - tiny custom limits still yield verified pieces
        # - the default path returns on the first step
        step = 64 if 64 < step <= 128 else step // 2
    # Every single-char piece overflows: use a safe placeholder.
    # - never emit an unverified oversize piece
    return ["…"]


# A complete fenced code block on raw text.
_FENCE_BLOCK_RE = re.compile(
    r"```[ \t]*[A-Za-z0-9_+\-.#]*[ \t]*\r?\n.*?```"
    r"|~~~[ \t]*[A-Za-z0-9_+\-.#]*[ \t]*\r?\n.*?~~~",
    re.DOTALL,
)


def segment_blocks(text: str) -> list[str]:
    """Split text into segments, isolating each fenced code block.

    - one message per block makes it easily copyable
    - returns [] for empty input
    """
    if not text or not text.strip():
        return []
    segments: list[str] = []
    last = 0
    for m in _FENCE_BLOCK_RE.finditer(text):
        pre = text[last : m.start()].strip()
        if pre:
            segments.append(pre)
        segments.append(m.group(0).strip())
        last = m.end()
    tail = text[last:].strip()
    if tail:
        segments.append(tail)
    return segments or [text.strip()]


def split_closed_blocks(text: str) -> tuple[str, str]:
    """Split streaming text after the last fully closed fence.

    - returns (prefix, remainder) split after a closed block
    - returns ("", text) when no such block exists
    - lets finished snippets commit while the draft keeps streaming
    """
    if not text:
        return "", text
    end = 0
    for m in _FENCE_BLOCK_RE.finditer(text):
        after = m.end()
        # Flush only blocks the model has finished.
        # - require a newline right after the closing fence
        # - finish() commits a trailing block at turn end
        if text.startswith("\n", after):
            end = after + 1
        elif text.startswith("\r\n", after):
            end = after + 2
    if end == 0:
        return "", text
    return text[:end], text[end:]


def should_send_as_file(text: str) -> bool:
    """True for very long output better sent as a document."""
    return bool(text) and len(text) > FILE_THRESHOLD


def as_document(text: str, filename: str) -> BufferedInputFile:
    """Wrap text as an in-memory file for upload.

    - text files get a UTF-8 BOM to avoid mojibake
    """
    bom = chr(0xFEFF)  # explicit UTF-8 BOM, invisible in source
    data = text or ""
    # Case-insensitive match, mirroring ensure_text_bom.
    # - so .MD and .TXT get a BOM on both paths
    if filename.lower().endswith((".md", ".txt")) and not data.startswith(bom):
        data = bom + data
    return BufferedInputFile(data.encode("utf-8"), filename=filename)


_UTF8_BOM = b"\xef\xbb\xbf"


def ensure_text_bom(data: bytes, filename: str) -> bytes:
    """Prepend a UTF-8 BOM to md or txt bytes.

    - no-op for other types or an existing BOM
    - bytes-level twin of as_document
    """
    if filename.lower().endswith((".md", ".txt")) and not data.startswith(_UTF8_BOM):
        return _UTF8_BOM + data
    return data
