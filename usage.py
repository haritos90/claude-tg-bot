"""Pure formatting helpers for subscription rate-limit windows.

No I/O. Uses time.time() only for reset countdowns.
"""

import time

import i18n

LABELS = {
    "five_hour": "5h",
    "seven_day": "7d",
    "seven_day_opus": "7d Opus",
    "seven_day_sonnet": "7d Sonnet",
    "overage": "overage",
}

# Deterministic display order for windows.
WINDOW_ORDER = (
    "five_hour",
    "seven_day",
    "seven_day_opus",
    "seven_day_sonnet",
    "overage",
)

# Friendly label shown when the API does not send a numeric utilization (it only
# does so as you approach a window; far from the limit it sends status="allowed"
# with utilization=null). Better than a bare "(n/a)". Maps the API status to a
# localized l10n key; the text lives in the i18n table.
_STATUS_KEY = {
    "allowed": "usage.status.ok",
    "allowed_warning": "usage.status.high",
    "rejected": "usage.status.limited",
}


def _bar(used_fraction: float, width: int = 8) -> str:
    """Render a small progress bar for a used fraction in [0, 1]."""
    try:
        frac = float(used_fraction)
    except (TypeError, ValueError):
        frac = 0.0
    if frac < 0:
        frac = 0.0
    elif frac > 1:
        frac = 1.0
    filled = round(frac * width)
    if filled < 0:
        filled = 0
    elif filled > width:
        filled = width
    return "▕" + "█" * filled + "░" * (width - filled) + "▏"


def _reset_in(resets_at, lang: str = "en") -> str:
    """Compact 'time until reset' string, e.g. '2h13m', '45m', '<1m'.

    Returns "" when there is nothing useful to show or on bad input.
    """
    if resets_at is None:
        return ""
    try:
        secs = int(resets_at) - int(time.time())
    except (TypeError, ValueError):
        return ""
    if secs <= 0:
        return ""
    hours, rem = divmod(secs, 3600)
    minutes = rem // 60
    if hours:
        return i18n.t("usage.reset_hm", lang, h=hours, m=minutes)
    if minutes:
        return i18n.t("usage.reset_m", lang, m=minutes)
    return i18n.t("usage.reset_lt1m", lang)


def window_str(info, lang: str = "en") -> str:
    """One-line description of a single rate-limit window.

    Returns "" when there is nothing useful to show.
    """
    if info is None:
        return ""
    utilization = getattr(info, "utilization", None)
    rate_limit_type = getattr(info, "rate_limit_type", None)
    resets_at = getattr(info, "resets_at", None)
    status = getattr(info, "status", None)

    # "overage" is a real English word (translatable); the others are
    # language-neutral abbreviations / model names kept verbatim.
    if rate_limit_type == "overage":
        label = i18n.t("usage.label.overage", lang)
    else:
        label = LABELS.get(rate_limit_type, rate_limit_type or "?")

    util = None
    if utilization is not None:
        try:
            util = float(utilization)
        except (TypeError, ValueError):
            util = None

    if util is not None:
        # The API gave a real fraction consumed -> show a bar and "% left".
        left = (1 - util) * 100
        out = f"{label} {_bar(util)} {i18n.t('usage.left', lang, pct=f'{left:.0f}')}"
    else:
        # No number yet (typical when the window is far from full): show the
        # window status instead of a meaningless "(n/a)".
        key = _STATUS_KEY.get(str(status))
        body = i18n.t(key, lang) if key else (i18n.t("usage.status.ok", lang) if status else "")
        out = f"{label} {body}".strip()

    # The reset countdown only matters when usage is actually constrained — show
    # it when we have a real % or the window is warning/limited, but NOT for a
    # plain "OK" (when there is plenty left the countdown is just noise).
    show_reset = util is not None or str(status) in ("allowed_warning", "rejected")
    if show_reset:
        r = _reset_in(resets_at, lang)
        if r:
            out = f"{out} · {i18n.t('usage.resets', lang, when=r)}"
    return out


def _ordered_present(rate_by_type: dict):
    """Yield (key, info) pairs for present windows in deterministic order."""
    if not rate_by_type:
        return
    seen = set()
    for key in WINDOW_ORDER:
        if key in rate_by_type and rate_by_type[key] is not None:
            seen.add(key)
            yield key, rate_by_type[key]
    # Include any unexpected keys after the known ones.
    for key, info in rate_by_type.items():
        if key not in seen and info is not None:
            yield key, info


def footer_line(rate_by_type: dict, lang: str = "en") -> str:
    """Short one-line summary, preferring 5h then a 7d window. "" if none."""
    if not rate_by_type:
        return ""

    keys: list[str] = []
    if rate_by_type.get("five_hour") is not None:
        keys.append("five_hour")
    for key in ("seven_day", "seven_day_opus", "seven_day_sonnet"):
        if rate_by_type.get(key) is not None:
            keys.append(key)
            break

    parts = []
    for key in keys:
        s = window_str(rate_by_type.get(key), lang)
        if s:
            parts.append(s)
    return " · ".join(parts)


def pinned_text(rate_by_type: dict, lang: str = "en") -> str:
    """Small multi-line usage block. "" if nothing present."""
    if not rate_by_type:
        return ""
    lines = []
    for _key, info in _ordered_present(rate_by_type):
        s = window_str(info, lang)
        if s:
            lines.append(s)
    if not lines:
        return ""
    return "\n".join([i18n.t("usage.pinned_header", lang), *lines])
