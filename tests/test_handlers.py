"""Unit tests for the pure helpers in handlers.py.

The message handlers themselves are closures built inside build_router() and are not
unit-tested here; the testable combining math is extracted to module-level pure
functions (the #235 album coalescer), which these tests exercise directly.
"""

import handlers


def _part(mid, blocks=None, inline=""):
    return (mid, {"blocks": blocks, "inline": inline})


def test_combine_album_text_files_join_under_header():
    """#235: several text/code files become one prompt — header once, segments joined,
    no content blocks."""
    parts = [
        _part(10, inline="--- a.txt ---\nAAA"),
        _part(11, inline="--- b.txt ---\nBBB"),
    ]
    text, blocks = handlers._combine_album_parts(parts, "Header.", "[cut]")
    assert blocks == []
    assert text == "Header.\n\n--- a.txt ---\nAAA\n\n--- b.txt ---\nBBB"


def test_combine_album_blocks_concatenated_and_ordered():
    """#235: image/PDF blocks from each item are concatenated in message_id order; with
    no inline text the prompt is just the header."""
    b1 = {"type": "image", "source": {"data": "1"}}
    b2 = {"type": "document", "source": {"data": "2"}}
    # supplied out of order on purpose — must be sorted by message_id
    parts = [_part(21, blocks=[b2]), _part(20, blocks=[b1])]
    text, blocks = handlers._combine_album_parts(parts, "Look.", "[cut]")
    assert text == "Look."
    assert blocks == [b1, b2]


def test_combine_album_mixed_blocks_and_inline():
    """#235: an album mixing a photo and a text file yields both a block and inline text."""
    img = {"type": "image", "source": {"data": "x"}}
    parts = [_part(30, blocks=[img]), _part(31, inline="--- log.txt ---\nLINE")]
    text, blocks = handlers._combine_album_parts(parts, "H.", "[cut]")
    assert blocks == [img]
    assert text == "H.\n\n--- log.txt ---\nLINE"


def test_combine_album_truncates_oversized_inline():
    """#235: combined inline text over MAX_TEXT_INLINE_CHARS is cut and labelled."""
    big = "x" * (handlers.MAX_TEXT_INLINE_CHARS + 50)
    parts = [_part(40, inline=big)]
    text, _blocks = handlers._combine_album_parts(parts, "H.", "[cut]")
    assert text.endswith("\n\n[cut]")
    # header + "\n\n" + MAX chars + "\n\n[cut]"
    assert len(text) == len("H.\n\n") + handlers.MAX_TEXT_INLINE_CHARS + len("\n\n[cut]")
