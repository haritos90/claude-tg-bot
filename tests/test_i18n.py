"""Unit tests for the i18n localization layer (#63).

Covers the l10n table's integrity (every row has English; en/ru agree on
placeholders and HTML tags), the t() lookup/format/fallback behaviour, locale
normalization, the per-user cache, and the display helpers. Pure pytest — no
async, no I/O.
"""

import re

from app import i18n

_PLACEHOLDER = re.compile(r"{(\w+)}")
_TAG = re.compile(r"</?[a-zA-Z][a-zA-Z0-9]*")


def _placeholders(s: str) -> set:
    return set(_PLACEHOLDER.findall(s))


def _tags(s: str) -> list:
    # Multiset of tag names (sorted) so a dropped/duplicated tag is caught.
    return sorted(t.lstrip("</").lower() for t in _TAG.findall(s))


def test_every_row_has_english():
    for key, row in i18n.CATALOG.items():
        assert "en" in row and row["en"], f"missing English for {key}"


def test_placeholders_match_across_locales():
    for key, row in i18n.CATALOG.items():
        en = _placeholders(row["en"])
        for lang, text in row.items():
            assert _placeholders(text) == en, f"placeholder mismatch in {key}/{lang}"


def test_html_tags_match_across_locales():
    for key, row in i18n.CATALOG.items():
        en = _tags(row["en"])
        for lang, text in row.items():
            assert _tags(text) == en, f"HTML tag mismatch in {key}/{lang}"


def test_default_lang_is_supported():
    assert i18n.DEFAULT_LANG in i18n.LANGUAGES


def test_every_row_renders_in_every_locale():
    # Render each row in each locale with dummy values for its placeholders; this
    # would catch e.g. a placeholder named like a t() parameter (collision) or a
    # stray format field. None may raise.
    for key, row in i18n.CATALOG.items():
        kwargs = {name: "X" for name in _placeholders(row["en"])}
        for lang in row:
            out = i18n.t(key, lang, **kwargs)
            assert "{" not in out and "}" not in out, f"unfilled placeholder in {key}/{lang}"


def test_lang_placeholder_does_not_collide_with_param():
    # A catalog placeholder supplied via kwargs must not clash with t()'s own
    # positional-only `lang` parameter (regression: settings.header used {lang}).
    out = i18n.t("settings.header", "ru", mode="код", model="opus", perm_line="",
                 usage="footer", stream="вкл", memory="выкл", drafts="вкл",
                 language="Русский")
    assert "Русский" in out


def test_t_basic_and_format():
    assert i18n.t("common.error", "en") == "Error."
    assert i18n.t("common.error", "ru") == "Ошибка."
    # kwargs are formatted into the chosen locale (Russian text + the value).
    msg = i18n.t("session.clear_error", "ru", err="boom")
    assert "сесси" in msg and "boom" in msg


def test_t_falls_back_to_english_for_missing_locale():
    # An unsupported locale falls back to the English column, never crashes.
    assert i18n.t("common.error", "de") == "Error."


def test_t_unknown_key_returns_key():
    assert i18n.t("no.such.key", "ru") == "no.such.key"


def test_t_bad_format_args_do_not_crash():
    # Missing a required placeholder returns the unformatted text, not an error.
    out = i18n.t("model.set", "en")  # expects {model} and {defer}
    assert isinstance(out, str) and out


def test_normalize_lang():
    assert i18n.normalize_lang("ru") == "ru"
    assert i18n.normalize_lang("ru-RU") == "ru"
    assert i18n.normalize_lang("en-US") == "en"
    assert i18n.normalize_lang("de") == "en"  # unsupported -> default
    assert i18n.normalize_lang(None) == "en"
    assert i18n.normalize_lang("") == "en"


def test_user_lang_cache():
    uid = 999_001
    i18n.forget_lang(uid)
    assert not i18n.has_lang(uid)
    assert i18n.cached_lang(uid) == i18n.DEFAULT_LANG  # default before resolution
    i18n.remember_lang(uid, "ru")
    assert i18n.has_lang(uid) and i18n.cached_lang(uid) == "ru"
    # An invalid locale is coerced to the default rather than stored verbatim.
    i18n.remember_lang(uid, "zz")
    assert i18n.cached_lang(uid) == i18n.DEFAULT_LANG
    i18n.forget_lang(uid)


def test_display_helpers():
    assert i18n.onoff(True, "ru") == "вкл" and i18n.onoff(False, "ru") == "выкл"
    assert i18n.yesno(True, "ru") == "да" and i18n.yesno(False, "ru") == "нет"
    assert i18n.mode_word("code", "ru") == "код"
    assert i18n.mode_word("chat", "ru") == "чат"
    assert i18n.lang_name("ru") == "Русский"
    assert i18n.lang_name("xx") == "xx"  # unknown code -> code itself


def test_stream_rotation_words_parity_across_locales():
    """#316/#319: the rotating <tg-thinking> gerund subsets must have the SAME count in every
    locale (thinking_words shipped once as 17 en vs 12 ru with no test). Pin equal length per
    subset so neither drifts: thinking_words == 30, searching_words == 16."""
    for key, expect in (("stream.thinking_words", 30), ("stream.searching_words", 16)):
        row = i18n.CATALOG[key]
        counts = {lang: len([w for w in text.split(",") if w.strip()])
                  for lang, text in row.items()}
        assert len(set(counts.values())) == 1, f"{key} length differs across locales: {counts}"
        assert all(c == expect for c in counts.values()), f"{key} expected {expect}: {counts}"
