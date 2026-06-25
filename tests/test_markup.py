"""Unit tests for markup: escaping, splitting, fence repair, code isolation,
and the render-time LaTeX→Unicode conversion (#12)."""

from app.telegram import markup
from app.telegram import table_image


def test_escape_html():
    assert markup.escape_html("<a> & b") == "&lt;a&gt; &amp; b"
    assert markup.escape_html(None) == ""
    # & escaped first so introduced entities are not double-escaped.
    assert markup.escape_html("&lt;") == "&amp;lt;"


def test_split_message_roundtrip_and_limit():
    text = "\n".join(f"line {i} " + "x" * 40 for i in range(300))
    chunks = markup.split_message(text, limit=500)
    assert len(chunks) > 1
    assert all(len(c) <= 500 for c in chunks)
    # Concatenation must reproduce the original exactly (newlines preserved).
    assert "".join(chunks) == text


def test_split_message_empty():
    assert markup.split_message("") == [""]


def test_split_markdown_repairs_straddling_fence():
    body = "```python\n" + "\n".join(f"a = {i}" for i in range(400)) + "\n```"
    chunks = markup.split_markdown(body, limit=600)
    assert len(chunks) > 1
    # Every chunk must contain a balanced number of fences so each renders as a
    # complete <pre> block instead of leaking literal backticks.
    for c in chunks:
        assert c.count("```") % 2 == 0


def test_md_to_html_fenced_code_is_pre():
    html = markup.md_to_html("```python\nx = 1\n```")
    assert html.startswith("<pre>") and 'class="language-python"' in html


def test_md_to_html_tilde_fence():
    html = markup.md_to_html("~~~js\nconst a = 1;\n~~~")
    assert "<pre>" in html and 'class="language-js"' in html


def test_segment_blocks_isolates_code():
    reply = "intro\n\n```py\nx=1\n```\n\noutro"
    segs = markup.segment_blocks(reply)
    assert segs == ["intro", "```py\nx=1\n```", "outro"]


def test_segment_blocks_plain_text():
    assert markup.segment_blocks("just text") == ["just text"]
    assert markup.segment_blocks("") == []


def test_split_closed_blocks_no_fence():
    # Plain prose: nothing to flush, all remainder.
    assert markup.split_closed_blocks("just talking here") == ("", "just talking here")
    assert markup.split_closed_blocks("") == ("", "")


def test_split_closed_blocks_open_fence_not_flushed():
    # An open (un-closed) block must NOT be flushed — it is still streaming.
    text = "intro\n```py\nx = 1"
    assert markup.split_closed_blocks(text) == ("", text)


def test_split_closed_blocks_closed_without_trailing_newline_waits():
    # Closing fence is the last thing on screen (no newline yet): don't flush —
    # finish() will commit the trailing block at turn end.
    text = "```py\nx = 1\n```"
    assert markup.split_closed_blocks(text) == ("", text)


def test_split_closed_blocks_flushes_prose_and_block():
    # A closed block followed by a newline flushes prose + block; the tail streams.
    text = "Here is code:\n```py\nx = 1\n```\nNow the rest"
    prefix, remainder = markup.split_closed_blocks(text)
    assert prefix == "Here is code:\n```py\nx = 1\n```\n"
    assert remainder == "Now the rest"
    # The flushed prefix isolates prose + the copyable code block.
    assert markup.segment_blocks(prefix) == ["Here is code:", "```py\nx = 1\n```"]


def test_split_closed_blocks_flushes_up_to_last_closed_block():
    # Two closed blocks → flush both; an open block after them stays in remainder.
    text = "```a\n1\n```\nmid\n```b\n2\n```\ntail\n```c\nopen"
    prefix, remainder = markup.split_closed_blocks(text)
    assert prefix.endswith("```\n")
    assert "```b\n2\n```" in prefix
    assert remainder == "tail\n```c\nopen"


def test_split_closed_blocks_tilde_fence():
    text = "~~~\ncode\n~~~\nafter"
    prefix, remainder = markup.split_closed_blocks(text)
    assert prefix == "~~~\ncode\n~~~\n"
    assert remainder == "after"


def test_latex_math_to_unicode():
    out = markup.md_to_html(r"$\frac{1}{2} \times x^2$ and $\sqrt{y}$")
    assert "1/2" in out and "×" in out and "x²" in out and "√" in out
    assert "$" not in out


def test_latex_protects_money():
    assert markup.md_to_html("It costs $5 and then $10.") == "It costs $5 and then $10."


def test_latex_protects_code_spans():
    html = markup.md_to_html(r"inline `\frac{a}{b}` stays literal")
    assert r"\frac{a}{b}" in html  # untouched inside <code>


def test_markdown_italics_not_eaten_by_subscript():
    html = markup.md_to_html("This is _important_ text")
    assert "<i>important</i>" in html


def test_render_within_limit_caps_entity_dense_chunk():
    # A raw chunk near SAFE_LIMIT made of '&' explodes ~5x when escaped; every
    # rendered piece must still fit Telegram's 4096 hard limit (else it is sent
    # and silently dropped), and nothing may be lost.
    raw = "&" * 3800
    pieces = markup.render_within_limit(raw)
    assert pieces
    assert all(len(p) <= markup.HARD_LIMIT for p in pieces)
    assert sum(p.count("&amp;") for p in pieces) == 3800  # every char survives


def test_render_within_limit_short_text_single_piece():
    assert markup.render_within_limit("hello world") == [markup.md_to_html("hello world")]


def test_is_empty_render_flags_blank_code_box():
    # Hard-cutting a single over-long line inside a fence can leave a lone fence
    # that renders to an empty <pre></pre> box (#70). is_empty_render must catch
    # it (with or without a language label) while leaving a real block alone.
    for empty in markup.render_within_limit("```\n```") + markup.render_within_limit("```js\n```"):
        assert markup.is_empty_render(empty)
    real = markup.md_to_html("```python\nx = 1\n```")
    assert not markup.is_empty_render(real)
    assert not markup.is_empty_render("…")  # the empty-turn placeholder is kept


def test_md_headers_and_links():
    html = markup.md_to_html("## Title\nsee [docs](https://x.io/a?b=1&c=2)")
    assert "<b>Title</b>" in html
    assert html.splitlines()[0] == "<b>Title</b>"  # leading '##' stripped
    assert '<a href="https://x.io/a?b=1&amp;c=2">docs</a>' in html


def test_md_non_url_link_left_literal():
    # A [text](ref) that isn't a real URL must not become an <a>.
    assert "<a " not in markup.md_to_html("see [x](#anchor)")


def test_md_table_to_pre_aligns_and_preserves_unicode():
    md = "| A | Bêta |\n|---|---|\n| 1 | oui |\n| 20 | non |"
    html = markup.md_to_html(md)
    assert "<pre>" in html and "</pre>" in html
    assert "Bêta" in html and "oui" in html and "non" in html
    assert "|" in html  # column separators present


def test_md_table_grid_separator_and_no_outer_pipes(monkeypatch):
    """#162: a pipe table whose separator uses `+` junctions (---+---+---) and which
    omits the outer pipes (an ASCII/grid style some models emit) must still render as a
    <pre> grid, not leak raw. Previously _TABLE_SEP_RE only accepted `|` junctions, so
    the whole table fell through to raw text."""
    md = (
        "Lang       | Compiles to          | Native ASM?\n"
        "-----------+----------------------+--------------\n"
        "Rust       | Machine code (LLVM)  | yes\n"
        "Python     | CPython bytecode     | no"
    )
    html = markup.md_to_html(md)
    assert "<pre>" in html and "</pre>" in html
    assert "Machine code (LLVM)" in html and "CPython bytecode" in html
    # The raw header/data lines must be inside ONE stashed grid, not loose text.
    assert html.count("<pre>") == 1


def test_hr_is_not_mistaken_for_a_table():
    """A thematic break (a bare run of dashes, no `|`/`+` junction) must NOT be read as
    a table separator — guards the widened #162 regex against false positives."""
    html = markup.md_to_html("intro text\n\n------\n\nmore text")
    assert "<pre>" not in html


def test_split_image_tables_extracts_wide_keeps_narrow():
    """#162: a table too wide to fit a phone as a grid is split out as a TableImage
    (sent as a photo); a narrow table stays inline text (a <pre> grid downstream)."""
    wide = (
        "Lang | Intermediate representation  | Final assembler     | Runs on\n"
        "-----+------------------------------+---------------------+----------------\n"
        "Rust | LLVM IR                      | x86-64 / ARM        | on the CPU\n"
        "Java | JVM bytecode                 | via JIT             | on the JVM"
    )
    items = markup.split_image_tables(wide)
    imgs = [it for it in items if isinstance(it, markup.TableImage)]
    assert len(imgs) == 1 and imgs[0].rows[0][0] == "Lang"     # header captured

    narrow = "A | B\n--+--\n1 | 2"
    items = markup.split_image_tables(narrow)
    assert all(isinstance(it, str) for it in items)            # stays inline text
    assert "|" in items[0]

    assert markup.split_image_tables("just prose, no table") == ["just prose, no table"]


def test_table_image_renders_png_bytes():
    """#162: a table renders to PNG bytes (DejaVu mono, Cyrillic-safe)."""
    png = table_image.render_table_png([["Lang", "ASM"], ["Rust", "yes"]])
    assert isinstance(png, (bytes, bytearray)) and png[:8] == b"\x89PNG\r\n\x1a\n"


def test_table_cell_emphasis_stripped():
    """#162: markdown emphasis inside cells (**b**/__b__/~~s~~/`c`) is stripped to plain
    text — a grid/card can't host it inline, so the raw markers must not leak."""
    md = "Name | Val\n----+----\n**Rust** | `yes`\n__Py__ | ~~no~~"
    html = markup.md_to_html(md)
    assert "**" not in html and "__" not in html and "~~" not in html and "`" not in html
    assert "Rust" in html and "yes" in html and "no" in html


# --- modern rich formatting (strikethrough / spoiler / blockquote) ----------- #
def test_md_strikethrough():
    assert markup.md_to_html("this is ~~gone~~ now") == "this is <s>gone</s> now"
    # A ``~~~`` code fence must NOT be eaten by the ~~strike~~ rule.
    html = markup.md_to_html("~~~js\nconst a = 1;\n~~~")
    assert "<pre>" in html and "<s>" not in html


def test_md_spoiler():
    assert markup.md_to_html("the answer is ||42||") == "the answer is <tg-spoiler>42</tg-spoiler>"
    # A spaced logical-or must NOT be mistaken for a spoiler.
    assert markup.md_to_html("a || b") == "a || b"


def test_md_blockquote_basic():
    html = markup.md_to_html("> hello\n> world")
    assert html == "<blockquote>hello\nworld</blockquote>"
    assert "&gt;" not in html  # the > markers are consumed, not left literal


def test_md_blockquote_inline_styles_inside():
    # Inline styles are applied INSIDE the quote (allowed by Telegram).
    html = markup.md_to_html("> **bold** and `code`")
    assert html.startswith("<blockquote>") and html.endswith("</blockquote>")
    assert "<b>bold</b>" in html and "<code>code</code>" in html


def test_md_blockquote_expandable_when_long():
    long_quote = "\n".join(f"> line {i}" for i in range(15))  # > threshold (10)
    html = markup.md_to_html(long_quote)
    assert html.startswith("<blockquote expandable>")
    short_quote = "\n".join(f"> line {i}" for i in range(3))
    assert markup.md_to_html(short_quote).startswith("<blockquote>")


def test_blockquote_not_applied_inside_code_fence():
    # A ``>`` inside a fenced code block stays literal text in <pre>, not a quote.
    html = markup.md_to_html("```\n> not a quote\n```")
    assert "<blockquote" not in html
    assert "&gt; not a quote" in html  # preserved (escaped) inside the code box


# --- #164: NATIVE Telegram tables (Bot API 10.1 sendRichMessage) -------------

def test_table_to_rich_html_basic_structure():
    rows = [["Header 1", "Header 2"], ["Value 1", "Value 2"]]
    html = markup.table_to_rich_html(rows)
    assert html.startswith("<table bordered striped>")
    assert html.endswith("</table>")
    # First row is a header (<th>), the rest are <td>.
    assert "<th>Header 1</th>" in html
    assert "<th>Header 2</th>" in html
    assert "<td>Value 1</td>" in html
    assert "<td>Value 2</td>" in html
    assert html.count("<tr>") == 2


def test_table_to_rich_html_escapes_and_keeps_emphasis():
    rows = [["Lang", "Note"], ["<b>&", "**Rust** is `fast`"]]
    html = markup.table_to_rich_html(rows)
    assert "&lt;b&gt;&amp;" in html            # raw < > & escaped
    assert "<b>Rust</b>" in html               # **bold** → <b> in a native cell
    assert "<code>fast</code>" in html         # `code` → <code>


def test_table_to_rich_html_alignments():
    rows = [["L", "C", "R"], ["1", "2", "3"]]
    html = markup.table_to_rich_html(rows, ["left", "center", "right"])
    assert '<th align="left">L</th>' in html
    assert '<th align="center">C</th>' in html
    assert '<td align="right">3</td>' in html


def test_parse_table_aligns():
    assert markup._parse_table_aligns("|:--|:-:|--:|---|") == ["left", "center", "right", None]


def test_split_rich_tables_extracts_all_tables():
    text = (
        "Intro paragraph.\n\n"
        "| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n\n"
        "Outro paragraph."
    )
    items = markup.split_rich_tables(text)
    tables = [it for it in items if isinstance(it, markup.RichTable)]
    assert len(tables) == 1
    assert tables[0].rows[0] == ["A", "B"]
    assert tables[0].rows[-1] == ["3", "4"]
    # Surrounding prose is preserved as plain-text runs, in order.
    assert any(isinstance(it, str) and "Intro" in it for it in items)
    assert any(isinstance(it, str) and "Outro" in it for it in items)


def test_split_rich_tables_no_table_is_identity():
    assert markup.split_rich_tables("just prose, no pipe") == ["just prose, no pipe"]


def test_split_rich_tables_narrow_table_also_native():
    # Unlike split_image_tables (which left narrow tables as <pre>), the native path
    # extracts narrow tables too — every table is a RichTable now.
    narrow = "| a | b |\n|---|---|\n| 1 | 2 |"
    items = markup.split_rich_tables(narrow)
    assert any(isinstance(it, markup.RichTable) for it in items)


# --- #243: route >20-column tables to the PNG image path ----------------------

def _wide_md(ncols: int, nrows: int = 2) -> str:
    header = "| " + " | ".join(f"C{i}" for i in range(ncols)) + " |"
    sep = "|" + "|".join([":--"] * ncols) + "|"
    rows = ["| " + " | ".join(f"r{r}c{i}" for i in range(ncols)) + " |" for r in range(nrows)]
    return "\n".join([header, sep, *rows])


def test_table_col_count():
    rows = markup.split_rich_tables(_wide_md(5))[0].rows
    assert markup.table_col_count(rows) == 5
    assert markup.table_col_count([]) == 0


def test_extract_wide_tables_pulls_over_limit_only():
    text = (
        "Intro.\n\n"
        + _wide_md(3)            # narrow → stays inline
        + "\n\nMiddle.\n\n"
        + _wide_md(21)           # wide → extracted
        + "\n\nOutro."
    )
    new_text, wide = markup.extract_wide_tables(text)
    assert len(wide) == 1
    assert markup.table_col_count(wide[0].rows) == 21
    # the wide table is replaced by exactly one token; the narrow table stays verbatim.
    assert new_text.count(markup.WIDE_TABLE_TOKEN) == 1
    assert "| C0 | C1 | C2 |" in new_text          # narrow table preserved
    assert "C20" not in new_text                    # wide table's cells are gone from the body
    assert "Intro." in new_text and "Outro." in new_text


def test_extract_wide_tables_at_limit_stays_inline():
    # Exactly 20 columns is within the native limit → not extracted.
    new_text, wide = markup.extract_wide_tables(_wide_md(20))
    assert wide == []
    assert new_text == _wide_md(20)


def test_extract_wide_tables_no_table_is_identity():
    assert markup.extract_wide_tables("just prose, no pipe") == ("just prose, no pipe", [])


def test_extract_wide_tables_token_reconstruction():
    # The token split must reconstruct the doc order: prose | note | prose.
    text = "Before.\n\n" + _wide_md(25) + "\n\nAfter."
    new_text, wide = markup.extract_wide_tables(text)
    parts = new_text.split(markup.WIDE_TABLE_TOKEN)
    assert len(parts) == 2
    assert "Before." in parts[0] and "After." in parts[1]
    assert markup.table_col_count(wide[0].rows) == 25


# --- #229: live task-list card (TodoWrite summary) ----------------------------

def test_summarize_todos_counts_and_glyphs():
    todos = [
        {"content": "Fix X", "status": "completed"},
        {"content": "Do Y", "status": "in_progress"},
        {"content": "Do Z", "status": "pending"},
    ]
    total, done, open_, body = markup.summarize_todos(todos)
    assert (total, done, open_) == (3, 1, 2)
    assert "✅ Fix X" in body and "🔄 Do Y" in body and "⬜ Do Z" in body
    # #339: tasks are joined by a markdown HARD break ("  \n"), NOT a bare "\n" — a soft
    # break collapses them onto one line in the rich {"markdown"} card (verified via blocks).
    assert body.split("  \n") == ["✅ Fix X", "🔄 Do Y", "⬜ Do Z"]


def test_summarize_todos_skips_blank_and_invalid():
    total, done, open_, body = markup.summarize_todos(
        [{"content": "", "status": "pending"}, "not-a-dict", {"status": "completed"}]
    )
    assert total == 0 and done == 0 and open_ == 0 and body == ""


def test_summarize_todos_truncates_long_content():
    long = "x" * 200
    total, _, _, body = markup.summarize_todos([{"content": long, "status": "pending"}])
    assert total == 1 and body.endswith("…") and len(body) < 120


def test_summarize_todos_unknown_status_is_open():
    total, done, open_, body = markup.summarize_todos([{"content": "Q", "status": "weird"}])
    assert (total, done, open_) == (1, 0, 1) and body.startswith("⬜")


# --- #176: split a reply into rich (non-code) + classic (code) segments -------

def test_split_code_blocks_separates_code_from_prose():
    t = "Intro\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```python\nx = 1\nprint(x)\n```\n\nDone."
    segs = markup.split_code_blocks(t)
    kinds = [k for k, _ in segs]
    assert kinds == ["text", "code", "text"]
    # the table stays in a TEXT segment (→ rich, native), code is its own segment
    assert "| a | b |" in segs[0][1] and "Intro" in segs[0][1]
    assert segs[1][1].startswith("```python") and "print(x)" in segs[1][1]
    assert "Done." in segs[2][1]


def test_split_code_blocks_no_code_is_single_text():
    assert markup.split_code_blocks("just prose, no fence") == [("text", "just prose, no fence")]
    assert markup.has_code_block("inline `code` only") is False
    assert markup.has_code_block("```\nblock\n```") is True


def test_ensure_text_bom():  # #206
    bom = b"\xef\xbb\xbf"
    # .md / .txt with non-ASCII gain a BOM so mobile viewers detect UTF-8.
    body = "café".encode("utf-8")
    assert markup.ensure_text_bom(body, "report.md") == bom + body
    assert markup.ensure_text_bom(body, "notes.TXT") == bom + body  # case-insensitive
    # Idempotent — never double-BOMs.
    assert markup.ensure_text_bom(bom + body, "report.md") == bom + body
    # Other file types are shipped verbatim (a BOM would corrupt them).
    png = b"\x89PNG\r\n"
    assert markup.ensure_text_bom(png, "chart.png") == png
    assert markup.ensure_text_bom(b"#!/bin/sh\n", "run.sh") == b"#!/bin/sh\n"


# was (#226, rejected — superseded by #237; kept per the revert policy):
# def test_contains_table_detects_full_partial_and_rejects_non_tables():
#     full = "| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |"
#     assert markup.contains_table(full) is True
#     assert markup.contains_table("| A | B |") is False
# def test_placeholder_tables_replaces_table_keeps_prose():
#     body = "Intro line\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\nAfter text"
#     assert markup.placeholder_tables(body, placeholder="[T]") == "Intro line\n\n[T]\n\nAfter text"


def test_clip_partial_table_keeps_only_complete_rows():
    """#237: for draft streaming, a still-being-typed final table line is clipped so the
    draft is always a VALID table prefix (complete rows only); a newline-terminated table
    and non-table text are left untouched."""
    # mid-row (no trailing newline) → drop the in-progress last row
    streaming = "| A | B |\n|---|---|\n| 1 | 2 |\n| 3"
    assert markup.clip_partial_table(streaming) == "| A | B |\n|---|---|\n| 1 | 2 |"
    # row just completed (trailing newline) → keep everything
    done_row = "| A | B |\n|---|---|\n| 1 | 2 |\n"
    assert markup.clip_partial_table(done_row) == done_row
    # header typed, separator still in progress → drop the partial separator
    sep_partial = "| A | B |\n|---"
    assert markup.clip_partial_table(sep_partial) == "| A | B |"
    # a "complete"-looking last row with NO trailing newline can't be told apart from one
    # still being typed mid-stream, so it is conservatively clipped — it rejoins one token
    # later when its newline arrives (this is the safe row-by-row behavior).
    no_nl = "| A | B |\n|---|---|\n| 1 | 2 |"
    assert markup.clip_partial_table(no_nl) == "| A | B |\n|---|---|"
    # no table → unchanged (even mid-word)
    assert markup.clip_partial_table("just some prose be") == "just some prose be"
    # prose before a streaming table: prose kept, in-progress row dropped
    mixed = "Intro\n\n| A | B |\n|---|---|\n| 9"
    assert markup.clip_partial_table(mixed) == "Intro\n\n| A | B |\n|---|---|"


def test_extract_svgs_fenced_and_raw():
    """#295: complete <svg> blocks (fenced ```svg or raw) are pulled out and replaced by a
    token; surrounding prose is kept; no <svg> leaves the text untouched."""
    from app.telegram import markup
    # fenced ```svg block
    fenced = "Here is the schematic:\n\n```svg\n<svg width='10'><rect/></svg>\n```\n\nDone."
    out, svgs = markup.extract_svgs(fenced)
    assert len(svgs) == 1 and svgs[0].startswith("<svg") and svgs[0].endswith("</svg>")
    assert markup.SVG_TOKEN in out and "<svg" not in out and "```" not in out
    assert "Here is the schematic" in out and "Done." in out
    # raw unfenced <svg>
    raw = "before <svg viewBox='0 0 2 2'><line/></svg> after"
    out2, svgs2 = markup.extract_svgs(raw)
    assert len(svgs2) == 1 and markup.SVG_TOKEN in out2 and "<svg" not in out2
    # two diagrams → two tokens, document order
    two = "<svg id='a'></svg>\nmid\n<svg id='b'></svg>"
    out3, svgs3 = markup.extract_svgs(two)
    assert len(svgs3) == 2 and "id='a'" in svgs3[0] and "id='b'" in svgs3[1]
    assert out3.count(markup.SVG_TOKEN) == 2
    # #301: mixed raw-THEN-fenced keeps document order (raw 'a' before fenced 'b')
    mixed = "<svg id='a'></svg>\n\n```svg\n<svg id='b'></svg>\n```\n"
    out4, svgs4 = markup.extract_svgs(mixed)
    assert len(svgs4) == 2 and "id='a'" in svgs4[0] and "id='b'" in svgs4[1]
    assert "```" not in out4 and out4.count(markup.SVG_TOKEN) == 2
    # no svg → unchanged, empty list
    assert markup.extract_svgs("plain text") == ("plain text", [])


def test_extract_locations():
    """#344: a fenced ```location block with valid lat/lon is pulled out → a token + a coerced
    dict; a venue keeps title+address; bad/out-of-range/non-JSON blocks stay as text; no block
    leaves the text untouched."""
    from app.telegram import markup
    # plain pin (lat/lon only) → token + dict, surrounding prose kept
    pin = "It is here:\n\n```location\n{\"lat\": 48.8584, \"lon\": 2.2945}\n```\n\nEnjoy."
    out, locs = markup.extract_locations(pin)
    assert len(locs) == 1 and locs[0] == {"lat": 48.8584, "lon": 2.2945}
    assert markup.LOCATION_TOKEN in out and "```" not in out
    assert "It is here" in out and "Enjoy." in out
    # venue (title+address) + key aliases (latitude/longitude) → both carried through
    venue = ("```location\n{\"latitude\": 51.5, \"longitude\": -0.12, "
             "\"title\": \"Big Ben\", \"address\": \"London\"}\n```")
    _o, vlocs = markup.extract_locations(venue)
    assert vlocs == [{"lat": 51.5, "lon": -0.12, "title": "Big Ben", "address": "London"}]
    # ```geo alias + numeric strings are coerced
    geo = "```geo\n{\"lat\": \"40\", \"lng\": \"-3\"}\n```"
    _o2, glocs = markup.extract_locations(geo)
    assert glocs == [{"lat": 40.0, "lon": -3.0}]
    # two blocks → two tokens in document order
    two = "```location\n{\"lat\":1,\"lon\":2}\n```\nmid\n```location\n{\"lat\":3,\"lon\":4}\n```"
    o3, locs3 = markup.extract_locations(two)
    assert [p["lat"] for p in locs3] == [1.0, 3.0] and o3.count(markup.LOCATION_TOKEN) == 2
    # out-of-range coords → left as text, NOT sent as a pin
    bad = "```location\n{\"lat\": 999, \"lon\": 0}\n```"
    o4, locs4 = markup.extract_locations(bad)
    assert locs4 == [] and o4 == bad
    # non-JSON body → left verbatim
    junk = "```location\nnot json\n```"
    o5, locs5 = markup.extract_locations(junk)
    assert locs5 == [] and o5 == junk
    # no location block → unchanged, empty list
    assert markup.extract_locations("plain text") == ("plain text", [])


def test_render_svg_png_smoke():
    """#295: a minimal SVG rasterizes to a valid PNG; junk raises so the caller can fall back."""
    from app.telegram import svg_image
    png = svg_image.render_svg_png(
        "<svg xmlns='http://www.w3.org/2000/svg' width='20' height='20'>"
        "<rect width='20' height='20' fill='#888'/></svg>"
    )
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 50
    import pytest
    with pytest.raises(ValueError):
        svg_image.render_svg_png("not an svg")
