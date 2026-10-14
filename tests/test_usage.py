"""Tests for account-usage fetch and normalization.

- `utilization` is a percent (0..100); `resets_at` is ISO-8601
- converts to RateLimitInfo: fraction 0..1 and epoch seconds
- drops windows with no number
- maps used fraction to the status vocabulary
"""

import asyncio

from app.storage import usage


def test_normalize_percent_to_fraction_and_iso_to_epoch():
    data = {
        "five_hour": {"utilization": 38.0, "resets_at": "2026-06-16T18:30:00+00:00"},
        "seven_day": {"utilization": 68.0, "resets_at": "2026-06-17T04:00:00+00:00"},
        "seven_day_opus": None,                       # absent window: dropped
        "seven_day_sonnet": {"utilization": 0.0, "resets_at": "2026-06-17T03:59:59+00:00"},
        "extra_usage": {"is_enabled": False},          # no utilization: dropped
    }
    out = usage.normalize_account_usage(data)
    # Only the two subscription windows; per-model windows dropped.
    assert set(out) == {"five_hour", "seven_day"}
    assert abs(out["five_hour"].utilization - 0.38) < 1e-9
    assert out["five_hour"].rate_limit_type == "five_hour"
    assert out["five_hour"].status == "allowed"        # 0.38 is below 0.8
    assert isinstance(out["five_hour"].resets_at, int) and out["five_hour"].resets_at > 0
    zero = usage.normalize_account_usage({"seven_day": {"utilization": 0.0, "resets_at": None}})
    assert zero["seven_day"].utilization == 0.0        # 0% kept (it is a number)


def test_normalize_status_thresholds():
    out = usage.normalize_account_usage({
        "five_hour": {"utilization": 85.0, "resets_at": None},
        "seven_day": {"utilization": 100.0, "resets_at": None},
    })
    assert out["five_hour"].status == "allowed_warning"   # at least 80%
    assert out["seven_day"].status == "rejected"          # at least 100%
    assert out["five_hour"].resets_at is None             # bad or None ISO gives None


def test_normalize_garbage_returns_empty():
    assert usage.normalize_account_usage(None) == {}
    assert usage.normalize_account_usage({"five_hour": {"utilization": "nope"}}) == {}


def test_window_str_renders_real_percent_left():
    """The normalized fraction flows through the formatter as '% left'."""
    out = usage.normalize_account_usage({"five_hour": {"utilization": 38.0, "resets_at": None}})
    s = usage.window_str(out["five_hour"], "en")
    assert "62% left" in s and s.startswith("5h")


def test_fetch_account_usage_uses_normalizer_and_fails_soft(monkeypatch):
    async def _run():
        monkeypatch.setattr(usage, "_fetch_account_usage_sync",
                            lambda creds, timeout: {"five_hour": {"utilization": 50.0, "resets_at": None}})
        out = await usage.fetch_account_usage()
        assert out and abs(out["five_hour"].utilization - 0.5) < 1e-9
        # Any failure (None payload) returns None, keeping the prior snapshot.
        monkeypatch.setattr(usage, "_fetch_account_usage_sync", lambda creds, timeout: None)
        assert await usage.fetch_account_usage() is None

    asyncio.run(_run())
