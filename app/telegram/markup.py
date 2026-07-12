"""Telegram formatting helpers.

Telegram's hard limit is 4096 characters per message; we use a safe limit of
3900 to leave room for HTML entities and minor overhead.

Public surface (callers in streamer.py / handlers.py depend on these):
  - escape_html(s) -> str
  - md_to_html(text) -> str
  - split_message(text, limit=3900) -> list[str]
  - should_send_as_file(text) -> bool
  - as_document(text, filename) -> aiogram BufferedInputFile
"""

from __future__ import annotations

import json
import re

from aiogram.types import BufferedInputFile

SAFE_LIMIT = 3900
# Telegram's hard per-message ceiling. split_markdown sizes by RAW length, but
# md_to_html escaping/markup can expand a chunk past this; render_within_limit
# re-splits so a rendered message never exceeds it (and gets silently dropped).
HARD_LIMIT = 4096
# #241: a RICH message (sendRichMessage / sendRichMessageDraft) allows up to 32768 UTF-8
# chars — far above the classic 4096. The draft streams the whole growing reply up to this
# (not just the classic ~3900 tail), and the rich final message is one bubble well past 4096.
RICH_LIMIT = 32768
# #243: a native Telegram rich table renders at most 20 columns (rich-message-spec.md:82).
# A wider table is routed to the PNG-image path instead (extract_wide_tables + render_table_png).
RICH_TABLE_MAX_COLS = 20
# Above this length the caller may prefer to send a .md document instead of
# spamming the chat with many chunks.
FILE_THRESHOLD = SAFE_LIMIT * 3


# --------------------------------------------------------------------------- #
# Escaping
# --------------------------------------------------------------------------- #
def escape_html(s: str) -> str:
    """Escape the three characters Telegram HTML treats specially.

    Order matters: ``&`` must be escaped first so we do not double-escape the
    ``&`` we introduce for ``<`` and ``>``.
    """
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# --------------------------------------------------------------------------- #
# Markdown -> Telegram HTML
# --------------------------------------------------------------------------- #
# Telegram HTML supports: b, i, u, s, code, pre, a, tg-spoiler, and blockquote
# (including <blockquote expandable>). See the README "Message formatting" section
# and the Telegram docs linked there for the full tag list + nesting rules.
# Strategy: HTML-escape EVERYTHING first, then re-apply a small, safe subset of
# Markdown by operating on the already-escaped text. Because the source has been
# escaped, any user-supplied ``<`` / ``>`` / ``&`` cannot form rogue tags; the
# only tags present are the ones we deliberately insert below.

_FENCE_RE = re.compile(
    r"```[ \t]*([A-Za-z0-9_+\-.#]*)[ \t]*\r?\n(.*?)```",
    re.DOTALL,
)
# Same as _FENCE_RE for ~~~ fences (some models emit these instead of ```).
_FENCE_TILDE_RE = re.compile(
    r"~~~[ \t]*([A-Za-z0-9_+\-.#]*)[ \t]*\r?\n(.*?)~~~",
    re.DOTALL,
)
_FENCE_NOLANG_RE = re.compile(r"```(.*?)```", re.DOTALL)
# #176: one FULL fenced code block (``` or ~~~, language optional). Requires a newline
# after the opener, so an inline ``…`` span is NOT matched — only real multi-line blocks.
_CODE_FENCE_BLOCK_RE = re.compile(
    r"```[ \t]*[A-Za-z0-9_+\-.#]*[ \t]*\r?\n.*?```"
    r"|~~~[ \t]*[A-Za-z0-9_+\-.#]*[ \t]*\r?\n.*?~~~",
    re.DOTALL,
)
# #353: a ``` or ~~~ fence open/close line (language optional). Used by demote_headings to
# leave a ``# comment`` INSIDE a code fence untouched (mirrors split_markdown's fence
# tracking via _FENCE_LINE_RE, but also accepts ~~~ fences).
_FENCE_TOGGLE_RE = re.compile(r"^[ \t]*(?:```|~~~)")
_INLINE_CODE_RE = re.compile(r"`([^`\n]+?)`")
_BOLD_STAR_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_BOLD_USCORE_RE = re.compile(r"__(.+?)__", re.DOTALL)
_ITALIC_STAR_RE = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", re.DOTALL)
_ITALIC_USCORE_RE = re.compile(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])", re.DOTALL)
# [text](url) links and ATX (#..) headers; placeholder token for the stash.
_LINK_RE = re.compile(r"\[([^\]\n]+)\]\(\s*([^)\s]+)\s*\)")
_ATX_HEADER_RE = re.compile(r"(?m)^[ \t]{0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_PH_RE = re.compile(r"\x00PH(\d+)\x00")
# A markdown table separator row (the line under the header). Accepts BOTH the GFM
# pipe form |---|:--:|---| AND the grid/ASCII form ---+---+--- — some models emit `+`
# at the column junctions and drop the outer pipes, which used to defeat detection so
# the whole table rendered raw (#162). Junction char is `|` or `+`; data rows still use
# `|` (split by _split_table_row), so only this separator line needed widening.
_TABLE_SEP_RE = re.compile(
    r"^[ \t]*[|+]?[ \t]*:?-{2,}:?[ \t]*(?:[|+][ \t]*:?-{2,}:?[ \t]*)+[|+]?[ \t]*$"
)

# Auto grid/cards (#162): a rendered grid wider than this many monospace chars won't
# fit a phone (a wide <pre> forces horizontal scroll / wraps and reads poorly), so
# it is rendered as vertical per-row "cards" instead. Narrower tables stay a <pre> grid.
_TABLE_GRID_MAX_WIDTH = 46
# Markdown emphasis markers dropped from table cells: a <pre> grid is monospace and a
# card bolds its title via tags, so raw **/__/~~/` would only show literally (the leaked
# ** in **Rust**). Inner text is kept.
_CELL_EMPH_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__|~~(.+?)~~|`([^`]+)`")

# --- modern rich formatting (Telegram "rich message formatting options") ------ #
# ~~strikethrough~~ (GitHub). Guarded so the tildes of a ``~~~`` code fence (which
# is stashed before this runs anyway) can never be mistaken for strikethrough.
_STRIKE_RE = re.compile(r"(?<!~)~~(?!~)([^\n]+?)(?<!~)~~(?!~)")
# ||spoiler|| (Discord/GitHub). Conservative — requires non-space inner edges so a
# logical-or like ``a || b`` (spaces around it) is never read as a spoiler.
_SPOILER_RE = re.compile(r"(?<!\|)\|\|(?!\|)(?=\S)([^\n]+?)(?<=\S)\|\|(?!\|)")
# A blockquote line AFTER escaping (``>`` became ``&gt;``), optional single space.
_QUOTE_LINE_RE = re.compile(r"^&gt;[ \t]?(.*)$")
# A run of ``> `` lines longer than this collapses to <blockquote expandable> so a
# long quote doesn't flood the chat; shorter runs stay an always-open <blockquote>.
# Set to None to never collapse (every quote stays open). See README.
EXPANDABLE_BLOCKQUOTE_MIN_LINES: int | None = 10


def _table_disp_len(s: str) -> int:
    """Visible width of an already-HTML-escaped cell (entities show as 1 char)."""
    return len(s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">"))


def _strip_cell_emphasis(s: str) -> str:
    """Drop markdown emphasis markers (**b**/__b__/~~s~~/`c`) from a table cell, keeping
    the inner text — a grid/card can't host them inline so the raw markers would leak."""
    prev = None
    out = s
    while prev != out:
        prev = out
        out = _CELL_EMPH_RE.sub(lambda m: next(g for g in m.groups() if g is not None), out)
    return out


def _split_table_row(line: str) -> list[str]:
    """Split a `| a | b |` row into trimmed, emphasis-stripped cells (outer pipes
    optional)."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [_strip_cell_emphasis(c.strip()) for c in s.split("|")]


def _render_table_pre(rows: list[list[str]]) -> str:
    """Render parsed rows (already HTML-escaped) as a column-aligned <pre> grid.

    Telegram HTML has no <table>, so a monospace block keeps the columns lined up
    — far more readable than raw `| a | b |` pipes wrapping mid-cell.
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
    """Render a wide table (won't fit a phone as a grid) as vertical per-row cards: the
    first column is a bold title, the remaining columns become `label: value` lines under
    it (the header row supplies the labels). No horizontal overflow — mobile-friendly.
    Cells are already HTML-escaped + emphasis-stripped; the title is bolded via tags."""
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
    """Pick the table layout by width (#162): an aligned <pre> grid when it fits a phone,
    else vertical cards. Both receive already-escaped, emphasis-stripped cells."""
    ncol = max(len(r) for r in rows)
    padded = [r + [""] * (ncol - len(r)) for r in rows]
    widths = [max(_table_disp_len(r[c]) for r in padded) for c in range(ncol)]
    grid_w = sum(widths) + 3 * (ncol - 1)  # " | " joins between columns
    if grid_w <= _TABLE_GRID_MAX_WIDTH or len(rows) < 2:
        return _render_table_pre(rows)
    return _render_table_cards(rows)


# #162: WIDE tables are now sent as IMAGES (table_image.render_table_png) rather than a
# wrapping <pre> grid — Telegram has no native table and a wide grid runs off the bubble
# (cramped). The split is decided by split_image_tables() below and the photo is sent
# by the streamer (a photo can't live inside an HTML text message). _render_table_auto /
# _render_table_cards above are the earlier text-only attempt (cards were rejected in
# review); kept for reference / non-image fallback.

class TableImage:
    """A wide table to be sent as a PNG photo (#162) instead of a text grid. Holds the
    parsed, emphasis-stripped (NOT HTML-escaped) rows for table_image.render_table_png."""

    __slots__ = ("rows",)

    def __init__(self, rows: list[list[str]]):
        self.rows = rows


def _table_is_wide(rows: list[list[str]]) -> bool:
    """True when the rendered grid would be wider than a phone (> _TABLE_GRID_MAX_WIDTH)
    — those tables are sent as an image rather than a wrapping <pre> grid (#162)."""
    if len(rows) < 2:
        return False
    ncol = max(len(r) for r in rows)
    padded = [r + [""] * (ncol - len(r)) for r in rows]
    widths = [max(_table_disp_len(r[c]) for r in padded) for c in range(ncol)]
    return sum(widths) + 3 * (ncol - 1) > _TABLE_GRID_MAX_WIDTH


def split_image_tables(text: str):
    """Split raw model text into ordered items: plain-text runs (str) and wide tables
    (TableImage) to be sent as a photo (#162). Narrow tables stay inside the text runs
    (md_to_html renders them as a <pre> grid). Returns [text] when there are no wide
    tables, so table-free output is unchanged."""
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
                buf.extend(lines[i:j])          # narrow → keep raw lines for the grid
            i = j
        else:
            buf.append(lines[i])
            i += 1
    if buf:
        items.append("\n".join(buf))
    return items or [text]


def _tables_to_pre(text: str, stash) -> str:
    """Replace GitHub-style markdown tables with stashed, aligned <pre> grids (#162).
    Wide tables meant to become images are extracted upstream (split_image_tables), so
    here every detected table is narrow enough to render as a grid."""
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


# --------------------------------------------------------------------------- #
# Streaming-table rendering — history (see the TODO ledger for the full trail):
#   #162 — markdown tables rendered as a <pre> monospace grid / PNG image. Wide
#          multi-column grids wrap to mush on a phone. Replaced by #164.
#   #164 — final tables sent as NATIVE Telegram rich tables (table_to_rich_html →
#          sendRichMessage). #176 sends the whole reply as ONE {"markdown"} rich
#          message; #172 streams the same {"markdown"} via sendRichMessageDraft.
#   #226 — bug: a table mid-stream shows only its first row, the full table snaps in
#          at finish. Attempt 1 re-rendered the table frontier as a <pre> grid (re-did
#          #162's wrapping) and attempt 2 hid the table behind a placeholder line —
#          BOTH rejected on-device. Those two helpers are kept commented just below.
#   #237 — the live fix: clip_partial_table() below. The draft and finish() share the
#          same {"markdown"} renderer, so a COMPLETE table renders identically; we only
#          ever feed the draft a VALID prefix (drop the in-progress trailing row), so the
#          native table grows row-by-row with no snap.
#
# was (#226, rejected — superseded by #237; kept per revert policy):
# def contains_table(text: str) -> bool:
#     if "|" not in text:
#         return False
#     lines = text.split("\n")
#     for i in range(len(lines) - 1):
#         if "|" in lines[i] and _TABLE_SEP_RE.match(lines[i + 1]):
#             return True
#     return False
#
# def placeholder_tables(text: str, placeholder: str = "📊 …") -> str:
#     # replaced each table with one placeholder line (hid it during the stream).
#     if "|" not in text:
#         return text
#     lines = text.split("\n")
#     out: list[str] = []
#     i, n = 0, len(lines)
#     while i < n:
#         nxt = lines[i + 1] if i + 1 < n else ""
#         if "|" in lines[i] and _TABLE_SEP_RE.match(nxt):
#             out.append(placeholder)
#             j = i + 2
#             while j < n and "|" in lines[j] and lines[j].strip():
#                 j += 1
#             i = j
#         else:
#             out.append(lines[i])
#             i += 1
#     return "\n".join(out)

# A trailing line that is a PARTIAL table separator still being typed (e.g. "|---" or
# "| :--" before the row is closed) — chars are only the separator alphabet, with at
# least one dash. Used to clip an in-progress separator from a streaming draft.
_PARTIAL_SEP_RE = re.compile(r"^[ \t]*[|+]?[ \t:|+-]*-[ \t:|+-]*$")


def clip_partial_table(text: str) -> str:
    """#237 (supersedes #226): for DRAFT streaming only — drop a still-being-typed final
    table line so the draft never contains a half-built (invalid GFM) table.

    The draft (`sendRichMessageDraft {"markdown": …}`) and the final message
    (`_commit_rich_markdown` → `sendRichMessage {"markdown": full_text}`) use the SAME rich
    renderer, so a COMPLETE-so-far markdown table renders identically in both. The old
    "only the first row streams, the whole table snaps in at finish" came from the draft
    carrying a row/separator mid-type — not valid GFM, so Telegram showed the header line
    alone. By clipping the trailing in-progress line (the last line when the text doesn't
    end in a newline) whenever it belongs to a table, every draft frame is a VALID PREFIX
    of the final message: the native table grows row-by-row with no snap.

    Only the trailing partial line is touched; a row that is already newline-terminated is
    complete and kept. No-op when the text ends in a newline or has no table. Pure + testable.

    CONFIRMED working on-device 2026-06-19 (#237): tables stream row-by-row with no snap. Do
    NOT revert to the #162/#226 grid or placeholder approaches (see the history block above)."""
    if "|" not in text or text.endswith("\n"):
        return text
    lines = text.split("\n")
    last = lines[-1]
    is_partial_row = "|" in last
    is_partial_sep = bool(_PARTIAL_SEP_RE.match(last))
    if not (is_partial_row or is_partial_sep):
        return text
    above = lines[:-1]
    # Walk up the contiguous block of table-ish lines that the last line belongs to.
    k = len(above)
    while k > 0 and ("|" in above[k - 1] or _TABLE_SEP_RE.match(above[k - 1])):
        k -= 1
    block = above[k:]
    established = any(_TABLE_SEP_RE.match(line) for line in block)   # header+separator seen
    header_then_partial_sep = is_partial_sep and bool(block) and "|" in block[-1]
    if established or header_then_partial_sep:
        return "\n".join(above)
    return text


def demote_headings(text: str) -> str:
    """#353: demote ATX headings (``# ``..``###### ``) to ``**bold**`` for the RICH
    ``{"markdown"}`` path (draft + commit).

    Telegram renders a markdown heading BLOCK in its own heading typography — larger /
    heavier, and a visually DISTINCT face on some clients — so ``## Heading`` reads as a
    different FONT beside the body paragraph font (the "jumping fonts" feedback). The rich
    reply is streamed and persisted verbatim as ``{"markdown"}``, so those headings reach
    Telegram raw. Demoting them keeps the whole reply in ONE (body) font, headings just
    bold — MIRRORING what the classic-HTML fallback already does (``md_to_html`` step 3c).

    No CONTENT decoration is added: whatever the model put on the heading line (a leading
    emoji or not) is preserved verbatim, so the per-heading emoji choice stays the AGENT's. A
    non-breaking-space SPACER paragraph is inserted BOTH above AND below each demoted heading
    (#360, extending the #353 V2 above-only spacer): a bold paragraph gets only a small
    inter-paragraph margin where a heading BLOCK had a larger one, so the heading is set off on
    both sides (verified on-device — the nbsp renders as the gap and, unlike a blank line, is
    not trimmed). The ABOVE spacer is skipped for a first-content heading (no blank line at the
    message top); the BELOW spacer is added lazily — only once real content follows, so it
    never trails the message frontier — and adjacent headings/spacers never stack (one gap).

    The transform is LINE-LOCAL and SKIPS fenced code (a ``# comment`` inside a ``` / ~~~
    block is left alone — fence state at any position is fixed by the text BEFORE it, so a
    streaming draft and the full text agree on what is code). Each draft frame stays VALID
    markdown: a COMPLETE heading demotes identically in the draft and the final (no snap), and
    a heading still being TYPED renders as a complete, early-closed ``**bold**`` span that just
    extends as more text arrives — like a half-typed ``**bold**`` (#237), and crucially with NO
    heading-FONT flash that then snaps to bold. Pure + testable; no-op when the text has no
    ``#``. Inner ``**``/``__`` in the title are dropped (the whole line is already bold),
    matching md_to_html step 3c."""
    if "#" not in text:
        return text
    out: list[str] = []
    in_fence = False
    # #360: a just-demoted heading awaits its BELOW nbsp spacer, added lazily on the next line
    # so it appears only once real content follows (never trailing the message frontier).
    pending_after = False

    def _add_spacer() -> None:
        # a U+00A0 paragraph = the visual gap (a blank line alone is trimmed, an nbsp is not).
        # Deduped: never stack two spacers (e.g. between adjacent headings) -> a single gap.
        if next((x for x in reversed(out) if x != ""), None) == "\u00A0":
            return
        if out and out[-1] != "":
            out.append("")
        out.append("\u00A0")
        out.append("")

    # #368: after flushing a heading's BELOW spacer, swallow the model's own blank line(s) too —
    # the spacer already supplies the gap, so a heading followed by 2+ blank lines no longer
    # emits an extra empty paragraph.
    skip_blank = False
    for line in text.split("\n"):
        if pending_after:               # #360: flush the BELOW spacer for the previous heading
            _add_spacer()
            pending_after = False
            skip_blank = True
        if skip_blank:
            if line == "":
                continue                # the spacer's trailing blank stands in for the model's
            skip_blank = False
        if _FENCE_TOGGLE_RE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        m = _ATX_HEADER_RE.match(line) if not in_fence else None
        if m is None:
            out.append(line)
            continue
        # #353 (V2) + #360: nbsp SPACER paragraph above (skipped for first content) AND below
        # the demoted heading, so the bold heading is set off on both sides like a block was.
        # was (#353, above-only): if out: [blank?]; out.append(nbsp); out.append("").
        if out:
            _add_spacer()
        out.append("**" + m.group(2).replace("**", "").replace("__", "") + "**")
        pending_after = True            # #360: BELOW spacer added when the next content arrives
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# NATIVE Telegram tables — Bot API 10.1 rich messages (#164)
# --------------------------------------------------------------------------- #
# Telegram Bot API 10.1 (2026-06-11) added sendRichMessage + an `html` field on
# InputRichMessage that DOES render <table>/<tr>/<th>/<td> with bordered/striped,
# colspan/rowspan, align/valign and <caption> (RichBlockTable). So a markdown
# table no longer needs a PNG (table_image) or a monospace <pre> grid — we emit
# real Telegram HTML and the client lays out (and side-scrolls) the columns.
#
# The PNG path (split_image_tables / TableImage / table_image.render_table_png)
# and the <pre> grid (_render_table_pre via _tables_to_pre) are KEPT above as a
# fallback / revert but are no longer on the live send path (the streamer routes
# every table through split_rich_tables → RichTable → sendRichMessage; #164).

# Inline cell emphasis we DO keep for native cells (a rich HTML cell can host
# tags, unlike the monospace grid which had to strip them). Bold + inline code
# are the common ones in model tables; kept conservative (paired markers only).
_CELL_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_CELL_CODE_RE = re.compile(r"`([^`]+)`")


class RichTable:
    """A markdown table to be sent as a NATIVE Telegram table (#164) via
    sendRichMessage. Holds the raw (NOT yet HTML-escaped) rows — first row is the
    header — plus per-column alignments parsed from the ``:--:`` separator."""

    __slots__ = ("rows", "aligns")

    def __init__(self, rows: list[list[str]], aligns: list | None = None):
        self.rows = rows
        self.aligns = aligns or []


def _split_table_row_raw(line: str) -> list[str]:
    """Split a ``| a | b |`` row into trimmed cells, KEEPING markdown emphasis
    (the native-table path converts **/`` `` to tags rather than stripping them)."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _parse_table_aligns(sep_line: str) -> list:
    """Parse a markdown separator row (``|:--|:-:|--:|``) into per-column
    alignments: ``"left"`` / ``"center"`` / ``"right"`` / None (default)."""
    out: list = []
    for c in _split_table_row_raw(sep_line):
        c = c.strip()
        left, right = c.startswith(":"), c.endswith(":")
        out.append("center" if left and right else "right" if right else "left" if left else None)
    return out


def _cell_rich_html(cell: str) -> str:
    """Escape a cell then re-introduce the common inline tags (bold, inline code)
    a Telegram rich cell can render. Escaping runs first, so ``*``/`` ` `` markers
    survive to be converted; everything else stays literal/escaped."""
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
    """Render parsed rows as a NATIVE Telegram ``<table>`` (Bot API 10.1 rich HTML).
    First row → ``<th>`` header cells; the rest → ``<td>``. Per-column ``align`` is
    applied from ``aligns``; the table is bordered + zebra-striped by default."""
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
    """Split raw model text into ordered items: plain-text runs (str) and tables
    (:class:`RichTable`) to be sent as native Telegram tables (#164). EVERY markdown
    table is extracted (narrow and wide alike) — unlike split_image_tables, which
    only pulled wide ones for the PNG path. Returns ``[text]`` when there is no
    table, so table-free output is unchanged."""
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
    """Column count of a parsed table = the widest row's cell count (#243)."""
    return max((len(r) for r in rows), default=0)


# #229: glyphs for the live task-list card (TodoWrite statuses).
_TODO_GLYPH = {"completed": "✅", "in_progress": "🔄", "pending": "⬜"}
_TODO_CELL_MAX = 90  # cap each task line so the card stays compact


def summarize_todos(todos: list) -> tuple[int, int, int, str]:
    """#229: turn a TodoWrite ``todos`` list into ``(total, done, open, body)`` for the
    live task-list card. Each item is a dict with ``content`` (+ ``status``:
    pending|in_progress|completed). Returns the body as one glyph-prefixed line per task;
    blank/invalid entries are skipped. ``total`` is the count of rendered lines."""
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
    # #339: join with a markdown HARD break ("  \n", two trailing spaces), NOT a bare "\n":
    # in Telegram's rich {"markdown"} field a single "\n" is a SOFT break = space, so the
    # glyph lines (plain text, not "- " list items) would all COLLAPSE onto one line. The
    # hard break renders each task on its own line. (Verified via parsed rich_message.blocks.)
    # was: "\n".join(lines)
    return total, done, total - done, "  \n".join(lines)


# #243: a sentinel marking where a >20-column table was removed from the rich-markdown
# body. NUL never appears in model text, so split/replace on it is unambiguous. The caller
# replaces each occurrence with a localized "sent as an image" note (the table itself goes
# as a PNG photo) — see streamer._commit.
WIDE_TABLE_TOKEN = "\x00WIDE_TABLE\x00"


def extract_wide_tables(text: str, max_cols: int = RICH_TABLE_MAX_COLS):
    """#243: pull out markdown tables with MORE than ``max_cols`` columns (a native rich
    table caps at 20 — rich-message-spec.md:82). Each wide table is replaced IN PLACE by
    ``WIDE_TABLE_TOKEN`` on its own line; narrow tables and all other text are kept verbatim.
    Returns ``(new_text, [RichTable, ...])`` in document order. When nothing is wide returns
    ``(text, [])`` so the common case is untouched."""
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
                out.extend(lines[i:j])  # narrow table → keep the original markdown verbatim
            i = j
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out), wide


# #295: chat replies can include an <svg> diagram (a schematic, chart, floor plan…). Telegram
# can't render SVG inline, so each complete <svg>…</svg> is pulled out, rasterized to PNG, and
# sent as a photo; a localized note is left where it was. Mirrors the wide-table token scheme.
SVG_TOKEN = "\x00SVG\x00"
# #301: ONE combined pass, fenced-alternative first so a fenced ```svg block is consumed as a
# whole (and the fence dropped) before its inner <svg> can match the raw alternative. A single
# left-to-right sub keeps the captured SVGs in true document order — a separate fenced-then-raw
# pass put all fenced ones ahead of all raw ones regardless of position.
_SVG_BLOCK_RE = re.compile(
    r"```[ \t]*(?:svg|xml|html)?[ \t]*\r?\n\s*(<svg\b.*?</svg>)\s*\r?\n?```"  # group 1: fenced
    r"|(<svg\b[^>]*>.*?</svg>)",                                              # group 2: raw
    re.DOTALL | re.IGNORECASE,
)


def extract_svgs(text: str):
    """#295: pull complete ``<svg>…</svg>`` diagrams (fenced ```svg or raw) out of ``text`` so
    they can be rasterized and sent as images instead of dumping raw XML in the bubble. Each is
    replaced IN PLACE by ``SVG_TOKEN``; returns ``(new_text, [svg_str, …])`` in document order.
    No ``<svg`` → ``(text, [])`` so the common case is untouched."""
    if "<svg" not in (text or "").lower():
        return text, []
    svgs: list[str] = []

    def _take(m) -> str:
        svgs.append((m.group(1) or m.group(2)).strip())  # fenced -> inner svg; else the raw svg
        return SVG_TOKEN

    out = _SVG_BLOCK_RE.sub(_take, text)
    return out, svgs


# #344: a chat OR code reply can place a point on the map — the user asks "where is X", for
# coordinates, or to "show it on a map". Telegram has no inline map, so a fenced ```location
# block carrying a small JSON object is pulled out and sent as a real sendLocation pin (or a
# sendVenue card when it names a place). Mirrors the SVG / wide-table token scheme: the block
# is replaced IN PLACE by LOCATION_TOKEN and a localized note is left where it was; the pin is
# delivered as its own message after the bubble. The <svg>→PNG path (above) is untouched.
LOCATION_TOKEN = "\x00LOCATION\x00"
_LOCATION_BLOCK_RE = re.compile(
    # #354: require the CONTIGUOUS ```location / ```geo fence (no space after the backticks) so
    # the regex agrees with the guards in extract_locations + streamer._hide_unclosed_location,
    # which test the contiguous literal. A ``` location block (leading space) the regex once
    # matched was rejected by those guards → its raw JSON reached the bubble and no pin was sent.
    # was: r"```[ \t]*(?:location|geo)[ \t]*\r?\n(.*?)\r?\n?```"
    r"```(?:location|geo)[ \t]*\r?\n(.*?)\r?\n?```",
    re.DOTALL | re.IGNORECASE,
)
# #347: a ```location block NESTED inside a longer (4+ backtick) fence is an EXAMPLE — the docs /
# the model demoing the feature wrap the 3-backtick block in a ```` fence — not a live pin. Match
# those outer spans so extract_locations skips any block inside one (it extracts only top-level).
_OUTER_FENCE_RE = re.compile(r"(`{4,})[^\n]*\n.*?\n\1", re.DOTALL)
# #347: Telegram rejects an over-long venue title/address with a 400 (and the venue send has no
# silent retry), so the model-supplied strings are capped to safe lengths before sending.
_VENUE_TITLE_MAX = 256
_VENUE_ADDRESS_MAX = 256


def _coerce_location(obj):
    """#344: validate one parsed ```location JSON object → a normalized ``{"lat","lon"[,"title",
    "address"]}`` dict, or ``None`` if it is not a usable point. Accepts ``lat``/``latitude`` and
    ``lon``/``lng``/``longitude`` (numbers or numeric strings); ``title``/``address`` are optional
    strings (both present → a venue card). Out-of-range or non-numeric coordinates are rejected so
    a malformed block is left as text, never sent as a bogus pin."""
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
    # #347: only the documented `title`/`address` keys (was: also `name`/`addr` — dropped the
    # undocumented aliases to keep the recognized schema tight), each capped so an over-long
    # model string can't make sendVenue return a 400.
    title = obj.get("title")
    address = obj.get("address")
    if isinstance(title, str) and title.strip():
        out["title"] = title.strip()[:_VENUE_TITLE_MAX]
    if isinstance(address, str) and address.strip():
        out["address"] = address.strip()[:_VENUE_ADDRESS_MAX]
    return out


def extract_locations(text: str):
    """#344: pull complete ```location (or ```geo) blocks out of ``text`` so each can be sent as a
    real Telegram map pin instead of dumping raw JSON in the bubble. The fenced block must hold a
    JSON object with ``lat``/``lon`` (``title``+``address`` optional → a venue). Each VALID block
    is replaced IN PLACE by ``LOCATION_TOKEN``; returns ``(new_text, [loc, …])`` in document order.
    An unparseable / out-of-range block is left verbatim so nothing is lost. No ```` ```location ````
    → ``(text, [])`` so the common case is untouched."""
    low = (text or "").lower()
    if "```location" not in low and "```geo" not in low:
        return text, []
    locs: list[dict] = []
    # #347: spans of any enclosing 4+ backtick fence — a ```location inside one is a demo, not a pin.
    outer = [(m.start(), m.end()) for m in _OUTER_FENCE_RE.finditer(text)]

    def _take(m) -> str:
        if any(a <= m.start() < b for a, b in outer):
            return m.group(0)  # #347: nested in a demo fence → leave verbatim, no pin
        try:
            obj = json.loads(m.group(1))
        except (ValueError, TypeError):
            return m.group(0)  # not JSON → leave the block exactly as the user wrote it
        loc = _coerce_location(obj)
        if loc is None:
            return m.group(0)  # missing / out-of-range coords → leave as text, never a bad pin
        locs.append(loc)
        return LOCATION_TOKEN

    out = _LOCATION_BLOCK_RE.sub(_take, text)
    return out, locs


def has_code_block(text: str) -> bool:
    """True if ``text`` contains a real (multi-line) fenced code block (#176)."""
    return bool(_CODE_FENCE_BLOCK_RE.search(text or ""))


def split_code_blocks(text: str):
    """Split text into ordered ``("text", str)`` and ``("code", str)`` segments (#176):
    a ``"code"`` segment is a full fenced block (``` or ~~~). Non-code runs (prose,
    tables, lists, headings) are kept as-is. Lets the streamer send code as a CLASSIC
    message (a REAL code block + copy) and everything else as RICH (consistent font +
    native tables) — the only way to get both in one Telegram reply."""
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


# --------------------------------------------------------------------------- #
# LaTeX -> Unicode (render-time fallback; #51)
# --------------------------------------------------------------------------- #
# Telegram can't render LaTeX. The chat system prompt asks the model to write
# plain Unicode (#43), but code mode and stray output still leak LaTeX, so we
# convert the common, UNAMBIGUOUS constructs at render time. This runs only on
# NON-code text (md_to_html stashes code first), and only rewrites LaTeX-specific
# syntax (backslash commands, ^{}/_{} scripts, math delimiters) so prose like
# "$5 and $10" or "a_b" is left untouched.
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
# Longest names first so e.g. \leftrightarrow wins over \leftarrow.
_LATEX_CMD_RE = re.compile(
    r"\\(" + "|".join(sorted(_LATEX_SYMBOLS, key=len, reverse=True)) + r")(?![A-Za-z])"
)
_SUP_SET = set("0123456789+-=()n")
_SUB_SET = set("0123456789+-=()")
_SUP_TAB = str.maketrans("0123456789+-=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")
_SUB_TAB = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")


def _script(s: str, charset: set, table: dict) -> str:
    """Translate s to super/sub-script if every char is supported, else give a
    readable caret/underscore fallback so nothing is silently dropped."""
    if s and all(ch in charset for ch in s):
        return s.translate(table)
    return None  # caller decides the fallback


def _latex_to_unicode(s: str) -> str:
    if "\\" not in s and "$" not in s and "^" not in s and "_{" not in s:
        return s  # fast path: nothing LaTeX-ish present

    def _unwrap_math(m: re.Match) -> str:
        inner = m.group(1)
        # Only treat as math if it actually contains LaTeX-ish syntax — protects
        # prose like "$5 and $10" (no backslash/^/sub/brace) from being mangled.
        return inner if re.search(r"[\\^{}]|_[\d{]", inner) else m.group(0)

    s = re.sub(r"\$\$(.+?)\$\$", _unwrap_math, s, flags=re.DOTALL)
    s = re.sub(r"\$([^$\n]+?)\$", _unwrap_math, s)
    s = re.sub(r"\\\((.+?)\\\)", r"\1", s, flags=re.DOTALL)
    s = re.sub(r"\\\[(.+?)\\\]", r"\1", s, flags=re.DOTALL)
    # \text{..}, \mathrm{..}, \mathbf{..}, \operatorname{..} → inner text.
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
    # Bare x_2 → subscript ONLY when preceded by an alphanumeric (so markdown
    # _italic_ — underscore followed by a letter at a word edge — is untouched).
    s = re.sub(
        r"(?<=[A-Za-z0-9])_(\d)",
        lambda m: _script(m.group(1), _SUB_SET, _SUB_TAB) or m.group(0),
        s,
    )
    return s


def _blockquotes_to_html(text: str) -> str:
    """Group runs of markdown ``> `` lines into Telegram <blockquote> blocks.

    Operates on already-escaped text (so ``>`` is ``&gt;``) AFTER code/tables are
    stashed, so a ``>`` inside code is never touched. Telegram blockquotes can't
    nest, so each run is flattened into ONE block; inline styles inside it are
    applied by the later bold/italic/strike/spoiler passes (those are allowed
    inside a blockquote). A run longer than EXPANDABLE_BLOCKQUOTE_MIN_LINES becomes
    a collapsible <blockquote expandable>.
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
    """Convert a SAFE subset of Markdown to Telegram HTML.

    Supported: fenced code blocks, inline code, **bold**/__bold__,
    *italic*/_italic_, ~~strikethrough~~, ||spoiler||, and ``> `` block quotes
    (a long run collapses to <blockquote expandable>). Everything is HTML-escaped
    first, so the output is always valid for ``parse_mode="HTML"``. If anything
    goes wrong we fall back to a fully-escaped plain string so a message is never
    lost.
    """
    if not text:
        return ""
    try:
        # 1) Escape the whole thing up front.
        escaped = escape_html(text)

        # 2) Pull out fenced code blocks first and replace them with opaque
        #    placeholders so later inline rules cannot touch their contents.
        placeholders: list[str] = []

        def _stash(html_fragment: str) -> str:
            placeholders.append(html_fragment)
            # Use a token that cannot appear after escaping or in user text and
            # will not be matched by the inline rules below.
            return f"\x00PH{len(placeholders) - 1}\x00"

        def _fence_sub(match: re.Match) -> str:
            lang = (match.group(1) or "").strip()
            body = match.group(2)
            # Strip a single trailing newline that belongs to the fence syntax.
            body = body.rstrip("\n")
            if lang:
                # Telegram renders <pre><code class="language-x"> with a language
                # label + syntax highlighting. The fence regex restricts the
                # language to a safe charset, so it needs no extra escaping.
                return _stash(
                    f'<pre><code class="language-{lang}">{body}</code></pre>'
                )
            return _stash(f"<pre>{body}</pre>")

        escaped = _FENCE_RE.sub(_fence_sub, escaped)
        # ~~~ fences use the same group layout, so reuse _fence_sub.
        escaped = _FENCE_TILDE_RE.sub(_fence_sub, escaped)

        # Fences without a language line / inline ``` ... ``` form.
        def _fence_nolang_sub(match: re.Match) -> str:
            body = match.group(1).strip("\n")
            return _stash(f"<pre>{body}</pre>")

        escaped = _FENCE_NOLANG_RE.sub(_fence_nolang_sub, escaped)

        # 3) Inline code -> <code>, also stashed so bold/italic skip it.
        def _inline_code_sub(match: re.Match) -> str:
            return _stash(f"<code>{match.group(1)}</code>")

        escaped = _INLINE_CODE_RE.sub(_inline_code_sub, escaped)

        # 3b) Markdown tables → a column-aligned <pre> grid (Telegram HTML has no
        #     <table>); stashed so the inline rules below don't touch the grid.
        escaped = _tables_to_pre(escaped, _stash)

        # 3c) ATX headers (#..######) → bold lines (Telegram has no <h*>). The
        #     whole header is bold, so redundant ** / __ inside it are dropped.
        escaped = _ATX_HEADER_RE.sub(
            lambda m: _stash("<b>" + m.group(2).replace("**", "").replace("__", "") + "</b>"),
            escaped,
        )

        # 3d) Links [text](url) → <a> (stashed so bold/italic skip the URL).
        def _link_sub(match: re.Match) -> str:
            label, url = match.group(1), match.group(2)
            if not re.match(r"(?:https?:|tg:|mailto:)", url):
                return match.group(0)  # not a real URL — leave the text literal
            return _stash(f'<a href="{url}">{label}</a>')

        escaped = _LINK_RE.sub(_link_sub, escaped)

        # 3d2) Block quotes: group ``> `` line runs into <blockquote> (long runs
        #     collapse to <blockquote expandable>). Done after code/tables are
        #     stashed (so quotes inside code are untouched) and before the inline
        #     passes (which then style the quote's contents — allowed inside it).
        escaped = _blockquotes_to_html(escaped)

        # 3e) LaTeX → Unicode on the remaining (non-code) text (#51). Code spans
        #     are already stashed as placeholders, so they are never touched.
        escaped = _latex_to_unicode(escaped)

        # 4) Inline styles. Bold first so ** is consumed before * italic; then
        #    ~~strike~~ and ||spoiler||; italic last (its single * / _ is the most
        #    fragile). All of these may nest and may sit inside a <blockquote>.
        escaped = _BOLD_STAR_RE.sub(r"<b>\1</b>", escaped)
        escaped = _BOLD_USCORE_RE.sub(r"<b>\1</b>", escaped)
        escaped = _STRIKE_RE.sub(r"<s>\1</s>", escaped)
        escaped = _SPOILER_RE.sub(r"<tg-spoiler>\1</tg-spoiler>", escaped)
        escaped = _ITALIC_STAR_RE.sub(r"<i>\1</i>", escaped)
        escaped = _ITALIC_USCORE_RE.sub(r"<i>\1</i>", escaped)

        # 5) Restore stashed fragments. Loop because a stashed fragment (header /
        #    table / link) can itself contain another placeholder; bound the
        #    passes (and the index) so a stray token can never spin or crash.
        def _restore(match: re.Match) -> str:
            idx = int(match.group(1))
            return placeholders[idx] if 0 <= idx < len(placeholders) else match.group(0)

        for _ in range(len(placeholders) + 1):
            if "\x00PH" not in escaped:
                break
            escaped = _PH_RE.sub(_restore, escaped)
        return escaped
    except Exception:
        # Never let formatting crash a send; fall back to plain escaped text.
        return escape_html(text)


# An empty rendered code box: <pre></pre> or <pre><code class="language-x">
# </code></pre> with no inner text. When split_message hard-cuts a single very
# long line inside a fence (minified JS, base64, a data URI), a lone fence can
# render to one of these — a blank tap-to-copy box that should never be sent.
_EMPTY_RENDER_RE = re.compile(
    r"\A<pre>(?:<code(?:\s[^>]*)?>\s*</code>)?</pre>\Z"
)


def is_empty_render(html: str) -> bool:
    """True when *html* is an empty code box with no inner text.

    Matches ``<pre></pre>`` and ``<pre><code class="language-x"></code></pre>``
    (any ``<code>`` attributes) after stripping surrounding whitespace. Such
    chunks come from hard-cutting a single over-long line inside a fence; they
    render as a blank tap-to-copy box and must be skipped before sending.
    """
    if not html:
        return False
    return _EMPTY_RENDER_RE.match(html.strip()) is not None


# --------------------------------------------------------------------------- #
# Splitting
# --------------------------------------------------------------------------- #
def split_message(text: str, limit: int = SAFE_LIMIT) -> list[str]:
    """Split *text* into chunks no longer than *limit* characters.

    Prefers paragraph (blank-line) and then line boundaries so we never cut in
    the middle of a line when it can be avoided. A single line longer than the
    limit is hard-cut. Never returns an empty list (returns ``[""]`` for empty
    input so the caller can simply skip empty chunks).
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

    # Split into lines, preserving structure. Each "piece" carries the newline
    # that split() removed (for every line after the first) so concatenating all
    # chunks reproduces the original text exactly.
    lines = text.split("\n")
    for i, line in enumerate(lines):
        piece = line if i == 0 else "\n" + line

        # A single line (with its leading newline) longer than the limit must be
        # hard-cut. The first hard-cut segment keeps the leading newline so the
        # round-trip is preserved.
        if len(piece) > limit:
            _flush()
            for start in range(0, len(piece), limit):
                chunks.append(piece[start : start + limit])
            continue

        if len(current) + len(piece) <= limit:
            current += piece
        else:
            # The current chunk is full. Carry this piece (newline included) to
            # the next chunk so the separating newline is not lost.
            _flush()
            current = piece

    _flush()
    if not chunks:
        return [""]
    return chunks


_FENCE_LINE_RE = re.compile(r"^[ \t]*```([A-Za-z0-9_+\-.#]*)[ \t]*$")


def split_markdown(text: str, limit: int = SAFE_LIMIT) -> list[str]:
    """Split raw Markdown into chunks, repairing fenced code blocks that
    straddle a chunk boundary.

    Splitting raw text (then rendering each chunk independently) is required so
    md_to_html never sees a tag cut in half. But a plain raw split can leave an
    incomplete ``` fence in each half, so neither renders as <pre> and the user
    sees literal backticks. Here we close any open fence at the end of a chunk
    and reopen it (with the same language hint) at the start of the next, so
    every chunk contains complete, independently-renderable fences.
    """
    # Reserve a little headroom for the fence markers we may add per chunk
    # (a reopened ```lang line plus a closing ``` line) so a repaired chunk
    # still stays within `limit`.
    inner_limit = max(1, limit - 24)
    chunks = split_message(text, limit=inner_limit)
    if len(chunks) <= 1:
        return chunks

    repaired: list[str] = []
    open_lang: str | None = None  # language of a fence carried over, if any
    for chunk in chunks:
        prefix = ""
        if open_lang is not None:
            # Reopen the fence carried from the previous chunk.
            prefix = f"```{open_lang}\n"

        # Walk the chunk's lines to track fence open/close state. Start from the
        # carried-over state so a fence opened in a prior chunk counts as open.
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
            # This chunk ends inside a fence: close it now and remember the
            # language so the next chunk reopens it.
            if not body.endswith("\n"):
                body += "\n"
            body += "```"
            open_lang = lang_here or ""
        else:
            open_lang = None
        repaired.append(body)

    return repaired


def render_within_limit(raw: str, hard_limit: int = HARD_LIMIT) -> list[str]:
    """Render one raw-Markdown chunk to HTML, guaranteeing each result fits
    Telegram's hard per-message limit.

    split_markdown sizes chunks by RAW character count, but md_to_html escapes
    ``&``/``<``/``>`` (up to ~5x) and adds tags, so an entity-dense raw chunk can
    render past 4096 — Telegram then rejects the send and it is silently dropped.
    Here we render, and when the HTML overflows we re-split the RAW source smaller
    and re-render (never splitting rendered HTML, which would cut a tag), with a
    hard-cut floor so a pathological single long line still terminates.
    """
    html = md_to_html(raw) or "…"
    if len(html) <= hard_limit:
        return [html]
    # Re-split the raw source on boundaries with a shrinking budget.
    raw_limit = max(256, len(raw) // 2)
    while raw_limit >= 256:
        pieces = split_markdown(raw, limit=raw_limit)
        if len(pieces) > 1:
            rendered = [md_to_html(p) or "…" for p in pieces]
            if all(len(h) <= hard_limit for h in rendered):
                return rendered
        raw_limit //= 2
    # Last resort: hard-cut the RAW text. md_to_html escapes first, so even a cut
    # mid-fence yields valid (escaped) HTML, never a broken tag. ``&`` expands to
    # 5 chars; a raw step of hard_limit//6 keeps each rendered piece in bounds.
    step = max(256, hard_limit // 6)
    out: list[str] = []
    for i in range(0, len(raw), step):
        out.append(md_to_html(raw[i : i + step]) or "…")
    return out or ["…"]


# A complete fenced code block (``` or ~~~), language optional, on raw text.
_FENCE_BLOCK_RE = re.compile(
    r"```[ \t]*[A-Za-z0-9_+\-.#]*[ \t]*\r?\n.*?```"
    r"|~~~[ \t]*[A-Za-z0-9_+\-.#]*[ \t]*\r?\n.*?~~~",
    re.DOTALL,
)


def segment_blocks(text: str) -> list[str]:
    """Split raw model text into ordered segments, ISOLATING each fenced code
    block into its own segment.

    Sending each code block as its own message makes it trivially copyable
    (long-press the message → Copy grabs the whole snippet) on every Telegram
    client — including those that don't show a per-block copy button and only
    copy the tapped token. Prose between/around blocks forms its own segments.
    Returns [] for empty input; a single segment when there are no code blocks.
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
    """Split streaming text at the end of the last FULLY-CLOSED fenced block.

    Returns ``(prefix, remainder)``: *prefix* is everything up to and including
    the last fenced code block that is both closed AND followed by a newline
    (proof the model has moved past it, so it will not grow further); *remainder*
    is the still-streaming tail. Returns ``("", text)`` when no such block exists.

    Used for LIVE code-block splitting while streaming (#93): the prefix is
    committed as its own message(s) — prose split off, the code block isolated
    into a copyable message — and the remainder keeps streaming in the draft, so
    a finished snippet becomes copyable immediately and the live draft stays
    smooth (it no longer carries a completed block whose closing tag would snap
    the animation).
    """
    if not text:
        return "", text
    end = 0
    for m in _FENCE_BLOCK_RE.finditer(text):
        after = m.end()
        # Only flush a block the model has definitively finished: require a
        # newline right after the closing fence. A block whose closing fence is
        # the last thing on screen might still grow (more backticks); finish()
        # commits such a trailing block at turn end anyway.
        if text.startswith("\n", after):
            end = after + 1
        elif text.startswith("\r\n", after):
            end = after + 2
    if end == 0:
        return "", text
    return text[:end], text[end:]


def should_send_as_file(text: str) -> bool:
    """True for very long output the caller may prefer to send as a document."""
    return bool(text) and len(text) > FILE_THRESHOLD


def as_document(text: str, filename: str) -> BufferedInputFile:
    """Wrap *text* as an in-memory file aiogram can upload.

    Text documents get a UTF-8 BOM so clients that would otherwise guess a legacy
    charset (rendering Cyrillic/other non-ASCII as mojibake) detect UTF-8.
    """
    bom = chr(0xFEFF)  # UTF-8 BOM, written explicitly (it is invisible in source)
    data = text or ""
    # #209: case-insensitive match, mirroring ensure_text_bom (the bytes-level twin),
    # so a `.MD`/`.TXT` is BOM'd by both paths. was: filename.endswith((".md", ".txt"))
    if filename.lower().endswith((".md", ".txt")) and not data.startswith(bom):
        data = bom + data
    return BufferedInputFile(data.encode("utf-8"), filename=filename)


_UTF8_BOM = b"\xef\xbb\xbf"


def ensure_text_bom(data: bytes, filename: str) -> bytes:
    """#206: prepend a UTF-8 BOM to a user-facing ``.md``/``.txt`` file's bytes when
    absent, so mobile/legacy viewers detect UTF-8 instead of guessing a charset and
    rendering non-ASCII (Cyrillic, accents, CJK, …) as mojibake. Language-agnostic; a
    no-op for other file types and for content that already carries a BOM. The
    bytes-level twin of :func:`as_document` (which BOMs ``str`` content), used when the
    bot ships an agent-created file verbatim (the outbox channel)."""
    if filename.lower().endswith((".md", ".txt")) and not data.startswith(_UTF8_BOM):
        return _UTF8_BOM + data
    return data
