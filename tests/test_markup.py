"""Unit tests for markup: escaping, splitting, fence repair, code isolation,
and the render-time LaTeX→Unicode conversion (#12)."""

import markup


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


def test_md_table_to_pre_aligns_and_preserves_cyrillic():
    md = "| A | Бета |\n|---|---|\n| 1 | да |\n| 20 | нет |"
    html = markup.md_to_html(md)
    assert "<pre>" in html and "</pre>" in html
    assert "Бета" in html and "да" in html and "нет" in html
    assert "|" in html  # column separators present


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
