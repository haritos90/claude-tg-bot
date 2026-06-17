"""Subscription rate-limit windows: pure formatting helpers + the account-usage fetch.

The formatters (``window_str`` / ``footer_line`` / ``pinned_text`` / ``_bar`` / …)
are PURE (no I/O; ``time.time()`` only for reset countdowns). The one network
function is :func:`fetch_account_usage` (#135) — it GETs the account usage endpoint
the Claude Code ``/usage`` uses, which reports the REAL per-window % even far from a
limit (the SDK ``rate_limit_event`` only sends ``utilization`` as you approach one).
"""

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime
from types import SimpleNamespace

import i18n

# Account usage endpoint (the source Claude Code's /usage reads). Authenticated with
# the subscription OAuth bearer from ~/.claude/.credentials.json + the OAuth beta
# header — NOT an API key (subscription billing is preserved; this is a read-only GET).
_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
_OAUTH_BETA = "oauth-2025-04-20"
_DEFAULT_CREDS = "~/.claude/.credentials.json"
# Windows we surface, in the response. The endpoint reports `utilization` as a
# PERCENT (0..100) and `resets_at` as an ISO-8601 string — both normalized below to
# the RateLimitInfo shape the formatters expect (fraction 0..1 + epoch seconds).
_ACCOUNT_WINDOWS = ("five_hour", "seven_day", "seven_day_opus", "seven_day_sonnet", "overage")


def _parse_iso_epoch(s):
    """ISO-8601 (e.g. '2026-06-16T18:30:00.74+00:00') → epoch seconds, or None."""
    try:
        return int(datetime.fromisoformat(str(s)).timestamp())
    except (TypeError, ValueError):
        return None


def _status_for(frac) -> str:
    """Map a used FRACTION to the same status vocabulary the SDK events use, so the
    formatter renders the reset countdown when high (≥80%) / limited (≥100%)."""
    if frac is None:
        return "allowed"
    if frac >= 1.0:
        return "rejected"
    if frac >= 0.8:
        return "allowed_warning"
    return "allowed"


def _fetch_account_usage_sync(creds_path: str, timeout: float):
    """Blocking GET of the usage endpoint. Returns the parsed JSON dict, or None on
    any failure (missing/garbled creds, non-200, network). Never raises; never logs
    the token."""
    try:
        with open(os.path.expanduser(creds_path), encoding="utf-8") as fh:
            tok = json.load(fh)["claudeAiOauth"]["accessToken"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    req = urllib.request.Request(
        _USAGE_URL,
        headers={
            "Authorization": f"Bearer {tok}",
            "anthropic-beta": _OAUTH_BETA,
            "Accept": "application/json",
            "User-Agent": "claude-tg-bot",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status != 200:
                return None
            data = json.load(r)
        return data if isinstance(data, dict) else None
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


def normalize_account_usage(data) -> dict:
    """Normalize the raw /api/oauth/usage payload into the ``{window: info}`` shape
    the formatters consume: ``utilization`` as a 0..1 FRACTION (API sends 0..100),
    ``resets_at`` as epoch seconds (API sends ISO). Drops windows with no number."""
    out: dict = {}
    if not isinstance(data, dict):
        return out
    for key in _ACCOUNT_WINDOWS:
        entry = data.get(key)
        if not isinstance(entry, dict):
            continue
        util = entry.get("utilization")
        if util is None:
            continue
        try:
            frac = max(0.0, float(util) / 100.0)
        except (TypeError, ValueError):
            continue
        out[key] = SimpleNamespace(
            rate_limit_type=key,
            utilization=frac,
            resets_at=_parse_iso_epoch(entry.get("resets_at")),
            status=_status_for(frac),
        )
    return out


async def fetch_account_usage(creds_path: str = _DEFAULT_CREDS, timeout: float = 15.0):
    """Fetch the REAL per-window usage from the account endpoint (#135), normalized to
    the RateLimitInfo shape (``utilization`` 0..1, ``resets_at`` epoch). Returns the
    ``{window: info}`` dict, or None on any failure — so the caller keeps its prior
    snapshot. Runs the blocking HTTP in a thread so the event loop is never stalled."""
    data = await asyncio.to_thread(_fetch_account_usage_sync, creds_path, timeout)
    out = normalize_account_usage(data)
    return out or None

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
        if key:
            body = i18n.t(key, lang)
        elif status:
            # #135/#137: an unknown-but-present status used to fall back to
            # "OK" — which over-asserts (we'd show "5h OK" for a state we don't
            # actually understand). Show a neutral marker; only an explicit
            # 'allowed' (via _STATUS_KEY) ever renders "OK".
            body = i18n.t("usage.status.unknown", lang)
        else:
            body = ""
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


def footer_line(rate_by_type: dict, lang: str = "en", sep: str = " · ") -> str:
    """Short summary, preferring 5h then a 7d window. "" if none. ``sep`` joins the
    windows — default " · " (one line); pass "\\n" for the owner's 2-line 5h/7d
    display (#169)."""
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
    return sep.join(parts)


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
