"""Unit tests for the i18n localization layer.

- catalog integrity: English present, placeholders and tags agree
- `t()` lookup, format, fallback; locale normalization
- per-user cache and display helpers; pure pytest
"""

import re

from app import i18n

_PLACEHOLDER = re.compile(r"{(\w+)}")
_TAG = re.compile(r"</?[a-zA-Z][a-zA-Z0-9]*")


def _placeholders(s: str) -> set:
    return set(_PLACEHOLDER.findall(s))


def _tags(s: str) -> list:
    # Sorted multiset of tag names catches dropped or duplicated tags.
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
    # Render each row per locale with dummy placeholder values.
    # - catches placeholder names colliding with `t()` parameters
    # - catches stray format fields; none may raise
    for key, row in i18n.CATALOG.items():
        kwargs = {name: "X" for name in _placeholders(row["en"])}
        for lang in row:
            out = i18n.t(key, lang, **kwargs)
            assert "{" not in out and "}" not in out, f"unfilled placeholder in {key}/{lang}"


def test_lang_placeholder_does_not_collide_with_param():
    # Catalog placeholders must not clash with positional-only `lang`.
    out = i18n.t("settings.header", "ru", mode="код", model="opus", perm_line="",
                 usage="footer", stream="вкл", memory="выкл", drafts="вкл",
                 language="Русский")
    assert "Русский" in out


def test_t_basic_and_format():
    assert i18n.t("common.error", "en") == "Error."
    assert i18n.t("common.error", "ru") == "Ошибка."
    # Kwargs are formatted into the chosen locale.
    msg = i18n.t("session.clear_error", "ru", err="boom")
    assert "сесси" in msg and "boom" in msg


def test_t_falls_back_to_english_for_missing_locale():
    # An unsupported locale falls back to English, never crashes.
    assert i18n.t("common.error", "de") == "Error."


def test_t_unknown_key_returns_key():
    assert i18n.t("no.such.key", "ru") == "no.such.key"


def test_t_bad_format_args_do_not_crash():
    # A missing required placeholder returns unformatted text, not an error.
    out = i18n.t("model.set", "en")  # expects {model} and {defer}
    assert isinstance(out, str) and out


def test_normalize_lang():
    assert i18n.normalize_lang("ru") == "ru"
    assert i18n.normalize_lang("ru-RU") == "ru"
    assert i18n.normalize_lang("en-US") == "en"
    assert i18n.normalize_lang("de") == "en"  # unsupported falls back to default
    assert i18n.normalize_lang(None) == "en"
    assert i18n.normalize_lang("") == "en"


def test_user_lang_cache():
    uid = 999_001
    i18n.forget_lang(uid)
    assert not i18n.has_lang(uid)
    assert i18n.cached_lang(uid) == i18n.DEFAULT_LANG  # default before resolution
    i18n.remember_lang(uid, "ru")
    assert i18n.has_lang(uid) and i18n.cached_lang(uid) == "ru"
    # An invalid locale is coerced to the default.
    i18n.remember_lang(uid, "zz")
    assert i18n.cached_lang(uid) == i18n.DEFAULT_LANG
    i18n.forget_lang(uid)


def test_display_helpers():
    assert i18n.onoff(True, "ru") == "вкл" and i18n.onoff(False, "ru") == "выкл"
    assert i18n.yesno(True, "ru") == "да" and i18n.yesno(False, "ru") == "нет"
    assert i18n.mode_word("code", "ru") == "код"
    assert i18n.mode_word("chat", "ru") == "чат"
    assert i18n.lang_name("ru") == "Русский"
    assert i18n.lang_name("xx") == "xx"  # unknown code returns the code itself


def test_stream_rotation_words_parity_across_locales():
    """Rotating thinking-word subsets have equal counts in every locale.

    - thinking_words is 30, searching_words is 16
    """
    for key, expect in (("stream.thinking_words", 30), ("stream.searching_words", 16)):
        row = i18n.CATALOG[key]
        counts = {lang: len([w for w in text.split(",") if w.strip()])
                  for lang, text in row.items()}
        assert len(set(counts.values())) == 1, f"{key} length differs across locales: {counts}"
        assert all(c == expect for c in counts.values()), f"{key} expected {expect}: {counts}"


def test_every_key_used_in_code_exists():
    """Every literal i18n key in code must be cataloged.

    - a missing key renders raw; `t()` never crashes
    - covers `i18n.t` and `i18n.maybe_t` keys
    - comment-only lines are skipped
    """
    import pathlib
    pat = re.compile(r'i18n\.(?:t|maybe_t)\(\s*"([a-z0-9_.]+)"')
    missing = set()
    for path in pathlib.Path(__file__).resolve().parent.parent.joinpath("app").rglob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#"):
                continue
            missing.update(k for k in pat.findall(line) if k not in i18n.CATALOG)
    assert not missing, sorted(missing)
