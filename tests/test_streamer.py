"""Unit tests for streamer pure helpers (#240)."""

import streamer


def test_tool_phase_label_maps_tools_to_phrases():
    """#240b: a tool call → a short '<emoji> doing X…' phase for the <tg-thinking> block."""
    assert streamer.tool_phase_label("Bash", {"command": "pytest -q"}) == "⚙️ Running pytest -q…"
    assert streamer.tool_phase_label("Bash", {}) == "⚙️ Running a command…"
    # only the first line of a multi-line command, truncated
    long = "x" * 60
    out = streamer.tool_phase_label("Bash", {"command": long})
    assert out.startswith("⚙️ Running ") and out.endswith("…") and len(out) < 60
    assert streamer.tool_phase_label("Read", {"file_path": "/a/b/sessions.py"}) == "📖 Reading sessions.py…"
    assert streamer.tool_phase_label("Edit", {"file_path": "x.py"}) == "✏️ Editing x.py…"
    assert streamer.tool_phase_label("WebSearch", {"query": "q"}) == "🌐 Searching the web…"
    assert streamer.tool_phase_label("Glob", {}) == "🔍 Finding files…"
    # unknown tool → generic; no tool → thinking
    assert streamer.tool_phase_label("Frobnicate", None) == "⚙️ Running Frobnicate…"
    assert streamer.tool_phase_label("", None) == "💭 Thinking…"


def test_wide_table_notes_replaces_token_and_is_noop_when_narrow():
    """#256: the draft + final paths share _wide_table_notes — a >20-col table's token is
    swapped for the localized note (so the draft matches the final bubble); no-op when none."""
    import markup
    s = streamer.Streamer(None, 123, None)
    header = "| " + " | ".join(f"c{i}" for i in range(21)) + " |"
    sep = "|" + "---|" * 21
    rowline = "| " + " | ".join("x" for _ in range(21)) + " |"
    body, wide = markup.extract_wide_tables("\n".join([header, sep, rowline]))
    assert wide and markup.WIDE_TABLE_TOKEN in body
    out = s._wide_table_notes(body, wide)
    assert markup.WIDE_TABLE_TOKEN not in out      # token expanded
    assert "21" in out                             # the column count is surfaced
    # no-op fast path when nothing is wide
    assert s._wide_table_notes("plain text", []) == "plain text"


def test_add_reasoning_accumulates_caps_and_clears_phase():
    """#240c: reasoning deltas accumulate (tail-capped) and resuming reasoning drops a
    stale tool phase so the live block reflects current activity."""
    s = streamer.Streamer(None, 123, None)
    s.set_phase("⚙️ Running pytest…")
    s.add_reasoning("Let me think about ")
    s.add_reasoning("the problem.")
    assert s._reasoning == "Let me think about the problem."
    assert s._phase is None              # resuming reasoning cleared the phase
    # empty delta is a no-op
    s.add_reasoning("")
    assert s._reasoning == "Let me think about the problem."
    # retained reasoning is tail-capped
    s.add_reasoning("z" * (streamer._REASONING_MAX + 500))
    assert len(s._reasoning) == streamer._REASONING_MAX
    assert s._reasoning.endswith("z")


def test_thinking_label_rotates():
    """#240a: the placeholder gerund advances with elapsed time and wraps."""
    first = streamer._thinking_label(0.0)
    second = streamer._thinking_label(streamer._THINKING_ROTATE_SECS + 0.1)
    assert first == streamer._THINKING_WORDS[0]
    assert second == streamer._THINKING_WORDS[1]
    # wraps around the list
    wrap = streamer._thinking_label(streamer._THINKING_ROTATE_SECS * len(streamer._THINKING_WORDS))
    assert wrap == streamer._THINKING_WORDS[0]
