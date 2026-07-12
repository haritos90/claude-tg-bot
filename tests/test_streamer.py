"""Unit tests for streamer pure helpers (#240)."""

from app import i18n
from app.telegram import streamer


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
    from app.telegram import markup
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
    """#240a/#294: the placeholder gerund advances with elapsed time and wraps, and is
    localized — the rotation list now comes from i18n (stream.thinking_words)."""
    from app import i18n
    words = [w for w in i18n.t("stream.thinking_words", "en").split(",") if w]
    first = streamer._thinking_label(0.0, "en")
    second = streamer._thinking_label(streamer._THINKING_ROTATE_SECS + 0.1, "en")
    assert first == words[0]
    assert second == words[1]
    # wraps around the list
    wrap = streamer._thinking_label(streamer._THINKING_ROTATE_SECS * len(words), "en")
    assert wrap == words[0]
    # localized: the Russian rotation differs from the English one
    assert streamer._thinking_label(0.0, "ru") != first


def test_sources_card_markdown_renders_list():
    """#318/#319: the research card lists WebSearch queries (🔍) and WebFetch URLs (🔗) as
    inline-code markdown LIST items (own line each, '- ' bullets, header as its own block),
    scheme + trailing slash trimmed; the header flips from in-progress to done."""
    from app import i18n
    src = [("search", "weather kyiv"), ("fetch", "https://example.com/page/")]
    live = streamer.sources_card_markdown(src, "en")
    assert live.startswith(i18n.t("stream.searching", "en"))       # in-progress header
    assert "- 🔍 `weather kyiv`" in live
    assert "- 🔗 `example.com/page`" in live                        # scheme + slash trimmed
    assert live.count("\n- ") == 2                                  # each on its own list line
    done = streamer.sources_card_markdown(src, "en", done=True)
    assert done.startswith(i18n.t("stream.sources_title", "en"))   # done header


def test_custom_emoji_gated_on_owner_premium():
    """#323: a custom (animated) emoji replaces the unicode in the thinking tag ONLY when the
    bot owner has Premium AND an id is configured; otherwise plain unicode (viewers need no
    premium). A draft failure self-heals back to unicode for the turn."""
    streamer.configure_custom_emoji("think:555,search:777")
    try:
        s = streamer.Streamer(None, 123, None)
        streamer.set_owner_premium(False)
        assert s._emoji("💭", "think") == "💭"                       # no owner premium → unicode
        streamer.set_owner_premium(True)
        assert s._emoji("💭", "think") == '<tg-emoji emoji-id="555">💭</tg-emoji>'
        assert s._emoji("🔎", "search") == '<tg-emoji emoji-id="777">🔎</tg-emoji>'
        assert s._emoji("📁", "files") == "📁"                       # no id for role → unicode
        s._custom_emoji_failed = True
        assert s._emoji("💭", "think") == "💭"                       # self-heal → unicode
    finally:
        streamer.configure_custom_emoji("")     # reset module globals for the rest of the suite
        streamer.set_owner_premium(False)


def test_set_tool_phase_routes_web_to_searching_mode():
    """#319: a web search/fetch flips "searching" MODE (the placeholder then rotates the
    search-themed gerund subset — animated), not a static phase; other tools keep a fixed
    phase label that names the file/command."""
    from app import i18n
    s = streamer.Streamer(None, 123, None)
    s.set_tool_phase("WebSearch", {"query": "q"})
    assert s._searching is True and s._phase is None
    s.set_tool_phase("Bash", {"command": "pytest -q"})
    assert s._searching is False and s._phase and "pytest" in s._phase
    # the searching gerunds are their own subset, distinct from the generic ones
    sg = streamer._thinking_label(0.0, "en", searching=True)
    assert sg in i18n.t("stream.searching_words", "en")
    assert sg != streamer._thinking_label(0.0, "en", searching=False)


def test_location_notes_replaces_every_token_and_is_noop_when_none():
    """#354/#371: each markup.LOCATION_TOKEN is swapped for the localized stream.location note
    (the draft + final paths share this helper), with none left over even when several pins
    appear; a no-op when there are no locations."""
    from app.telegram import markup
    s = streamer.Streamer(None, 123, None)
    note = i18n.t("stream.location", i18n.cached_lang(123))
    text = f"a {markup.LOCATION_TOKEN} b {markup.LOCATION_TOKEN} c"
    out = s._location_notes(text, [{"lat": 1, "lon": 2}, {"lat": 3, "lon": 4}])
    assert markup.LOCATION_TOKEN not in out            # every token expanded
    assert out.count(note) == 2                         # one note per pin, none dropped
    assert out == f"a {note} b {note} c"
    # no-op fast path when there are no locations
    assert s._location_notes("plain text", []) == "plain text"
