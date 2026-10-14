"""Subscription rate-limit windows: formatting helpers and usage fetch.

- Formatters are pure; only reset countdowns read the clock
- `fetch_account_usage` is the only network call
- Endpoint reports real percent even far from limit
"""

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime
from types import SimpleNamespace

from app import i18n

# Account usage endpoint, the source Claude Code's /usage reads.
# - Auth is the subscription OAuth bearer, not an API key
# - Read-only GET
_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
_OAUTH_BETA = "oauth-2025-04-20"
_DEFAULT_CREDS = "~/.claude/.credentials.json"
# Windows surfaced from the response: exactly two subscription limits.
# - The roughly 5-hour window and the weekly one
# - Payload gives percent 0..100 and ISO reset times
# - Normalized to fraction 0..1 and epoch seconds
# - A window added later stays hidden until listed
ACCOUNT_WINDOWS: tuple[str, ...] = ("five_hour", "seven_day")


def keep_window(key) -> bool:
    """True for one of the two tracked subscription windows."""
    return str(key) in ACCOUNT_WINDOWS


def _parse_iso_epoch(s):
    """ISO-8601 timestamp to epoch seconds, or None."""
    try:
        return int(datetime.fromisoformat(str(s)).timestamp())
    except (TypeError, ValueError):
        return None


def _status_for(frac) -> str:
    """Map a used fraction to the SDK status vocabulary.

    - Reset countdown renders when high (80%) or limited (100%)
    """
    if frac is None:
        return "allowed"
    if frac >= 1.0:
        return "rejected"
    if frac >= 0.8:
        return "allowed_warning"
    return "allowed"


def _fetch_account_usage_sync(creds_path: str, timeout: float):
    """Blocking GET of usage endpoint; returns parsed JSON or None.

    - Never raises and never logs the token
    """
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
    """Normalize the raw usage payload into the `{window: info}` shape.

    - `utilization` becomes a 0..1 fraction (API sends 0..100)
    - `resets_at` becomes epoch seconds (API sends ISO)
    - Drops windows with no number
    """
    out: dict = {}
    if not isinstance(data, dict):
        return out
    # Only the two subscription windows are read.
    for key in ACCOUNT_WINDOWS:
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
    """Fetch normalized per-window usage from the account endpoint.

    - Returns None on any failure, so caller keeps prior snapshot
    - Runs blocking HTTP in a thread
    """
    data = await asyncio.to_thread(_fetch_account_usage_sync, creds_path, timeout)
    out = normalize_account_usage(data)
    return out or None

# Window labels derive from the key, not a fixed map.
# - `five_hour` gives '5h'; `seven_day_<x>` gives '7d <X>'
_FIXED_LABELS = {"five_hour": "5h", "seven_day": "7d"}


def window_label(key: str | None) -> str:
    """Language-neutral label for a usage window key."""
    if not key:
        return "?"
    if key in _FIXED_LABELS:
        return _FIXED_LABELS[key]
    if key.startswith("seven_day_"):
        return "7d " + key[len("seven_day_"):].replace("_", " ").title()
    return key.replace("_", " ")


# Display order: account-wide windows first, others in arrival order.
WINDOW_ORDER = (
    "five_hour",
    "seven_day",
)

# Friendly label when the API sends no numeric utilization.
# - Number sent only near a limit; else status 'allowed'
# - Maps API status to a localized l10n key
_STATUS_KEY = {
    "allowed": "usage.status.ok",
    "allowed_warning": "usage.status.high",
    "rejected": "usage.status.limited",
}


def _bar(used_fraction: float, width: int = 8) -> str:
    """Render a small progress bar for a used fraction."""
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
    """Compact time-until-reset string, e.g. '2h13m', '45m', '<1m'.

    - Returns empty string when nothing useful or input is bad
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

    - Returns empty string when nothing useful to show
    """
    if info is None:
        return ""
    utilization = getattr(info, "utilization", None)
    rate_limit_type = getattr(info, "rate_limit_type", None)
    resets_at = getattr(info, "resets_at", None)
    status = getattr(info, "status", None)

    # 'overage' is translatable; other labels are language-neutral and verbatim.
    if rate_limit_type == "overage":
        label = i18n.t("usage.label.overage", lang)
    else:
        label = window_label(rate_limit_type)

    util = None
    if utilization is not None:
        try:
            util = float(utilization)
        except (TypeError, ValueError):
            util = None

    if util is not None:
        # API gave a real fraction: show bar and percent left.
        left = (1 - util) * 100
        out = f"{label} {_bar(util)} {i18n.t('usage.left', lang, pct=f'{left:.0f}')}"
    else:
        # No number yet: show window status instead of '(n/a)'.
        key = _STATUS_KEY.get(str(status))
        if key:
            body = i18n.t(key, lang)
        elif status:
            # Unknown status shows a neutral marker, never 'OK'.
            # - Only an explicit 'allowed' renders 'OK'
            body = i18n.t("usage.status.unknown", lang)
        else:
            body = ""
        out = f"{label} {body}".strip()

    # Show reset countdown only when usage is constrained.
    # - Real percent or warning/limited status; not plain 'OK'
    show_reset = util is not None or str(status) in ("allowed_warning", "rejected")
    if show_reset:
        r = _reset_in(resets_at, lang)
        if r:
            out = f"{out} · {i18n.t('usage.resets', lang, when=r)}"
    return out


def ordered_windows(rate_by_type: dict):
    """Public alias of `_ordered_present`: present (key, info) pairs."""
    return _ordered_present(rate_by_type)


def _ordered_present(rate_by_type: dict):
    """Yield (key, info) pairs for present windows in order."""
    if not rate_by_type:
        return
    seen = set()
    for key in WINDOW_ORDER:
        if key in rate_by_type and rate_by_type[key] is not None:
            seen.add(key)
            yield key, rate_by_type[key]
    # Nothing beyond the two subscription windows.


def footer_line(rate_by_type: dict, lang: str = "en", sep: str = " · ") -> str:
    """Short summary, preferring 5h then a 7d window.

    - Empty string if none
    - `sep` joins the windows; default is ' · '
    """
    if not rate_by_type:
        return ""

    keys: list[str] = []
    if rate_by_type.get("five_hour") is not None:
        keys.append("five_hour")
    # Weekly window only.
    if rate_by_type.get("seven_day") is not None:
        keys.append("seven_day")

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
