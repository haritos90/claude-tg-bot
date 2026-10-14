"""Unit tests for streamer pure helpers."""

from app import i18n
from app.telegram import streamer


def test_tool_phase_label_maps_tools_to_phrases():
    """A tool call maps to a short phase for `<tg-thinking>`."""
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
    # unknown tool: generic; no tool: thinking
    assert streamer.tool_phase_label("Frobnicate", None) == "⚙️ Running Frobnicate…"
    assert streamer.tool_phase_label("", None) == "💭 Thinking…"


def test_wide_table_notes_replaces_token_and_is_noop_when_narrow():
    """Draft and final paths share `_wide_table_notes`.

    - a >20-column table token becomes the localized note
    - so the draft matches the final bubble
    - no-op when there is none
    """
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
    """Reasoning deltas accumulate, tail-capped.

    - resuming reasoning drops a stale tool phase
    """
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
    """The placeholder gerund advances with elapsed time and wraps.

    - localized: the rotation list comes from i18n
    """
    from app import i18n
    words = [w for w in i18n.t("stream.thinking_words", "en").split(",") if w]
    first = streamer._thinking_label(0.0, "en")
    second = streamer._thinking_label(streamer._THINKING_ROTATE_SECS + 0.1, "en")
    assert first == words[0]
    assert second == words[1]
    # wraps around the list
    wrap = streamer._thinking_label(streamer._THINKING_ROTATE_SECS * len(words), "en")
    assert wrap == words[0]
    # localized: the Russian rotation differs from English
    assert streamer._thinking_label(0.0, "ru") != first


def test_sources_card_markdown_renders_list():
    """The research card lists WebSearch queries and WebFetch URLs.

    - inline-code markdown list items, one per line
    - scheme and trailing slash trimmed
    - header flips from in-progress to done
    """
    from app import i18n
    src = [("search", "weather kyiv"), ("fetch", "https://example.com/page/")]
    live = streamer.sources_card_markdown(src, "en")
    assert live.startswith(i18n.t("stream.searching", "en"))       # in-progress header
    assert "- 🔍 `weather kyiv`" in live
    assert "- 🔗 `example.com/page`" in live                        # scheme and slash trimmed
    assert live.count("\n- ") == 2                                  # each on its own list line
    done = streamer.sources_card_markdown(src, "en", done=True)
    assert done.startswith(i18n.t("stream.sources_title", "en"))   # done header


def test_custom_emoji_gated_on_owner_premium():
    """Custom animated emoji needs bot-owner Premium and a configured id.

    - otherwise plain unicode (viewers need no premium)
    - a draft failure self-heals to unicode for the turn
    """
    streamer.configure_custom_emoji("think:555,search:777")
    try:
        s = streamer.Streamer(None, 123, None)
        streamer.set_owner_premium(False)
        assert s._emoji("💭", "think") == "💭"                       # no owner premium: unicode
        streamer.set_owner_premium(True)
        assert s._emoji("💭", "think") == '<tg-emoji emoji-id="555">💭</tg-emoji>'
        assert s._emoji("🔎", "search") == '<tg-emoji emoji-id="777">🔎</tg-emoji>'
        assert s._emoji("📁", "files") == "📁"                       # no id for role: unicode
        s._custom_emoji_failed = True
        assert s._emoji("💭", "think") == "💭"                       # self-heal: unicode
    finally:
        streamer.configure_custom_emoji("")     # reset module globals for the suite
        streamer.set_owner_premium(False)


def test_set_tool_phase_routes_web_to_searching_mode():
    """Web search/fetch flips a 'searching' mode, not a static phase.

    - placeholder then rotates the search-themed gerund subset
    - other tools keep a fixed phase naming the file/command
    """
    from app import i18n
    s = streamer.Streamer(None, 123, None)
    s.set_tool_phase("WebSearch", {"query": "q"})
    assert s._searching is True and s._phase is None
    s.set_tool_phase("Bash", {"command": "pytest -q"})
    assert s._searching is False and s._phase and "pytest" in s._phase
    # Searching gerunds are their own subset, distinct from generic ones.
    sg = streamer._thinking_label(0.0, "en", searching=True)
    assert sg in i18n.t("stream.searching_words", "en")
    assert sg != streamer._thinking_label(0.0, "en", searching=False)


def test_location_notes_replaces_every_token_and_is_noop_when_none():
    """Each `markup.LOCATION_TOKEN` is swapped for the localized location note.

    - draft and final paths share this helper
    - none left over even with several pins
    - no-op when there are no locations
    """
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


def test_commit_rich_interleaved_pins_split_and_drop_placeholder():
    """A pins reply is split at each `LOCATION_TOKEN`.

    - native pin sent right where it sat, in order
    - venue card when named, else a plain pin
    - consecutive tokens send back-to-back, no empty bubble
    - placeholder deleted first; footer rides last text bubble
    """
    import asyncio
    from app.telegram import markup

    class _FakeBot:
        def __init__(self):
            self.calls: list = []

        async def __call__(self, method):        # `SendRichMessage` call
            self.calls.append(("rich", method.rich_message.get("markdown")))

        async def delete_message(self, chat_id, message_id):
            self.calls.append(("delete", message_id))
            return True

        async def send_message(self, **kw):
            self.calls.append(("html", kw.get("text")))

        async def send_location(self, **kw):
            self.calls.append(("pin", (kw["latitude"], kw["longitude"])))
            return object()                      # truthy so `_safe` sees delivery

        async def send_venue(self, **kw):
            self.calls.append(("venue", kw["title"]))
            return object()

    bot = _FakeBot()
    s = streamer.Streamer(bot, 123, None)
    s.message_id = 42                            # a live streaming placeholder to clear
    tok = markup.LOCATION_TOKEN
    rich_text = f"Intro{tok}Middle{tok}{tok}End"  # 3 pins, two back-to-back
    locations = [
        {"lat": 48.8584, "lon": 2.2945, "title": "Eiffel Tower", "address": "Paris"},
        {"lat": 1.0, "lon": 2.0},
        {"lat": 3.0, "lon": 4.0},
    ]
    asyncio.run(s._commit_rich_interleaved(rich_text, locations, [], [], "5h: 10%", silent_first=True))
    kinds = [c[0] for c in bot.calls]
    # Placeholder cleared first, then interleaved run in document order.
    # - back-to-back pins land consecutively, no empty bubble
    assert bot.calls[0] == ("delete", 42)
    assert kinds == ["delete", "rich", "venue", "rich", "pin", "pin", "rich"]
    assert "Intro" in bot.calls[1][1] and "Middle" in bot.calls[3][1] and "End" in bot.calls[6][1]
    assert all(c[1] and c[1].strip() for c in bot.calls if c[0] == "rich")   # never an empty bubble
    # A named point becomes a venue card; others become pins.
    # - all three are delivered
    assert bot.calls[2] == ("venue", "Eiffel Tower")
    assert ("pin", (1.0, 2.0)) in bot.calls and ("pin", (3.0, 4.0)) in bot.calls
    assert "10%" in bot.calls[6][1]              # footer rides last non-empty text bubble
    assert s.message_id is None                  # placeholder reference cleared


def test_commit_rich_interleaved_footer_alone_when_reply_is_pure_attachments():
    """An attachments-only reply still sends each plus a footer.

    - footer is its own message
    - nothing is lost
    """
    import asyncio
    from app.telegram import markup

    class _FakeBot:
        def __init__(self):
            self.calls: list = []

        async def __call__(self, method):
            self.calls.append(("rich", method.rich_message.get("markdown")))

        async def send_message(self, **kw):
            self.calls.append(("html", kw.get("text")))

        async def send_location(self, **kw):
            self.calls.append(("pin", (kw["latitude"], kw["longitude"])))
            return object()

    bot = _FakeBot()
    s = streamer.Streamer(bot, 123, None)
    s.message_id = None                          # DM draft has no placeholder
    tok = markup.LOCATION_TOKEN
    asyncio.run(s._commit_rich_interleaved(f"{tok}{tok}", [{"lat": 1, "lon": 2}, {"lat": 3, "lon": 4}],
                                           [], [], "5h: 42%", silent_first=True))
    kinds = [c[0] for c in bot.calls]
    assert kinds == ["pin", "pin", "html"]       # both pins, then footer alone
    assert "42%" in bot.calls[-1][1]
    assert not any(c[0] == "rich" for c in bot.calls)   # no empty text bubble sent


def test_commit_rich_interleaved_mixes_diagrams_tables_and_pins_in_order(monkeypatch):
    """Diagrams and wide tables also interleave at their token's spot.

    - each sends as a PNG photo at its token
    - mixed with pins and prose in document order
    """
    import asyncio
    from app.telegram import markup

    # Stub CPU-heavy rasterization: assert order, not pixels.
    monkeypatch.setattr(streamer.svg_image, "render_svg_png", lambda svg: b"SVGPNG")
    monkeypatch.setattr(streamer.table_image, "render_table_png", lambda rows: b"TBLPNG")

    class _FakeTable:
        rows = [["a", "b"]]

    class _FakeBot:
        def __init__(self):
            self.calls: list = []

        async def __call__(self, method):
            self.calls.append(("rich", method.rich_message.get("markdown")))

        async def send_photo(self, **kw):
            self.calls.append(("photo", kw["photo"].filename))

        async def send_location(self, **kw):
            self.calls.append(("pin", (kw["latitude"], kw["longitude"])))
            return object()

    bot = _FakeBot()
    s = streamer.Streamer(bot, 123, None)
    s.message_id = None
    svg, tbl, loc = markup.SVG_TOKEN, markup.WIDE_TABLE_TOKEN, markup.LOCATION_TOKEN
    rich_text = f"Alpha{svg}Beta{tbl}Gamma{loc}Delta"
    asyncio.run(s._commit_rich_interleaved(
        rich_text, [{"lat": 1.0, "lon": 2.0}], ["<svg/>"], [_FakeTable()],
        "5h: 7%", silent_first=True,
    ))
    kinds = [c[0] for c in bot.calls]
    assert kinds == ["rich", "photo", "rich", "photo", "rich", "pin", "rich"]
    # Each attachment lands at its own spot, typed by filename.
    assert bot.calls[1] == ("photo", "diagram.png")   # the `<svg>` diagram
    assert bot.calls[3] == ("photo", "table.png")     # the wide table
    assert bot.calls[5] == ("pin", (1.0, 2.0))
    assert "Alpha" in bot.calls[0][1] and "Delta" in bot.calls[6][1]
    assert "7%" in bot.calls[6][1]                     # footer on the last prose bubble


def test_commit_rich_interleaved_oversize_segment_splits_on_rich_failure():
    """A failed single rich send falls back to per-segment sends.

    - fallback size-splits the run and sends each piece as HTML
    - an oversize run beside a pin is delivered in parts
    - keypad rides the last piece only
    """
    import asyncio
    from app.telegram import markup

    class _FakeBot:
        def __init__(self):
            self.calls: list = []

        async def __call__(self, method):        # force the single send to fail
            raise RuntimeError("message is too long")

        async def send_message(self, **kw):
            self.calls.append(("html", kw.get("text"), kw.get("reply_markup")))
            return object()                      # a real Message is truthy

        async def send_location(self, **kw):
            self.calls.append(("pin", (kw["latitude"], kw["longitude"])))
            return object()

    bot = _FakeBot()
    s = streamer.Streamer(bot, 123, None)
    s.message_id = None
    tok = markup.LOCATION_TOKEN
    # Entity-dense text: md_to_html escapes '&' to '&amp;' (5x).
    # - each raw SAFE_LIMIT chunk renders past Telegram's 4096 ceiling
    # - `render_within_limit` re-splits so every piece fits
    big = "A & B & C & D & E & F & G & H\n" * 350
    # Oversize run is last: it both splits and carries keypad.
    # - exercises the per-piece keypad line
    # - keypad on every piece would fail
    rich_text = f"lead paragraph{tok}{big}"          # lead, pin, then oversize run
    asyncio.run(s._commit_rich_interleaved(
        rich_text, [{"lat": 1.0, "lon": 2.0}], [], [], "5h: 5%",
        silent_first=True, reply_markup="KP"))
    calls = bot.calls
    # The pin is delivered and marks the run split.
    assert ("pin", (1.0, 2.0)) in calls
    pin_idx = calls.index(("pin", (1.0, 2.0)))
    lead = [c for c in calls[:pin_idx] if c[0] == "html"]            # short lead run, before pin
    big_pieces = [c for c in calls[pin_idx + 1:] if c[0] == "html"]  # oversize run, after pin, split
    assert len(lead) == 1                                            # lead: one piece, ordered first
    assert len(big_pieces) >= 2                                      # oversize run splits into pieces
    # Every emitted piece stays under Telegram's per-message ceiling.
    assert all(len(c[1]) <= markup.HARD_LIMIT for c in lead + big_pieces)
    # No prose is lost in the re-split.
    # - every '&' from the oversize run survives
    # - a hard-cut dropping characters would fail
    import html as _html
    assert sum(_html.unescape(c[1]).count("&") for c in big_pieces) == big.count("&")
    # Keypad rides exactly the last oversize-run piece.
    # - keypad on every piece would fail here
    assert big_pieces[-1][2] == "KP"
    assert all(c[2] is None for c in big_pieces[:-1])
    assert lead[0][2] is None                                       # non-final segment: no keypad
