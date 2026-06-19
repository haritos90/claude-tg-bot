"""Unit tests for the #188 schedule parser + next-run computation (pure)."""

from datetime import datetime

import pytest

import schedules


def test_parse_daily_forms():
    for phrase in ("every day at 9:00", "daily at 09:00", "at 9am", "each day at 9"):
        spec = schedules.parse_phrase(phrase)
        assert spec == {"kind": "daily", "hour": 9, "minute": 0}, phrase


def test_parse_12h_pm():
    assert schedules.parse_phrase("at 9:30pm") == {"kind": "daily", "hour": 21, "minute": 30}
    assert schedules.parse_phrase("at 12am") == {"kind": "daily", "hour": 0, "minute": 0}
    assert schedules.parse_phrase("at 12pm") == {"kind": "daily", "hour": 12, "minute": 0}


def test_parse_weekly():
    assert schedules.parse_phrase("every monday at 18:00") == {
        "kind": "weekly", "weekday": 0, "hour": 18, "minute": 0}
    assert schedules.parse_phrase("weekly on fri at 6:00")["weekday"] == 4
    assert schedules.parse_phrase("sun at 7:30") == {
        "kind": "weekly", "weekday": 6, "hour": 7, "minute": 30}


def test_parse_interval():
    assert schedules.parse_phrase("every 2 hours") == {"kind": "interval", "seconds": 7200}
    assert schedules.parse_phrase("every 30 minutes") == {"kind": "interval", "seconds": 1800}
    assert schedules.parse_phrase("hourly") == {"kind": "interval", "seconds": 3600}


def test_interval_minimum_enforced():
    with pytest.raises(schedules.ScheduleError):
        schedules.parse_phrase("every 5 minutes")


def test_parse_schedule_requires_pipe_and_prompt():
    with pytest.raises(schedules.ScheduleError):
        schedules.parse_schedule("every day at 9:00 do something")  # no pipe
    with pytest.raises(schedules.ScheduleError):
        schedules.parse_schedule("every day at 9:00 | ")            # empty prompt
    spec, prompt = schedules.parse_schedule("every day at 9:00 | summarize notifications")
    assert spec["kind"] == "daily" and prompt == "summarize notifications"


def test_bad_phrase_raises():
    for bad in ("", "sometimes", "at 99:99", "every fortnight at 9:00"):
        with pytest.raises(schedules.ScheduleError):
            schedules.parse_phrase(bad)


def test_next_run_daily_advances_past_now():
    # 2026-06-19 12:00 local; daily at 09:00 → next is the 20th 09:00.
    now = datetime(2026, 6, 19, 12, 0, 0).timestamp()
    nxt = schedules.next_run_after({"kind": "daily", "hour": 9, "minute": 0}, now)
    d = datetime.fromtimestamp(nxt)
    assert (d.hour, d.minute) == (9, 0) and d.day == 20


def test_next_run_daily_later_today():
    now = datetime(2026, 6, 19, 8, 0, 0).timestamp()
    nxt = schedules.next_run_after({"kind": "daily", "hour": 9, "minute": 0}, now)
    d = datetime.fromtimestamp(nxt)
    assert d.day == 19 and (d.hour, d.minute) == (9, 0)


def test_next_run_interval():
    now = 1_000_000.0
    assert schedules.next_run_after({"kind": "interval", "seconds": 1800}, now) == now + 1800


def test_next_run_weekly_is_in_future_on_target_weekday():
    now = datetime(2026, 6, 19, 12, 0, 0).timestamp()  # Friday
    nxt = schedules.next_run_after({"kind": "weekly", "weekday": 0, "hour": 9, "minute": 0}, now)
    d = datetime.fromtimestamp(nxt)
    assert d.weekday() == 0 and nxt > now


def test_describe_roundtrip():
    assert schedules.describe({"kind": "daily", "hour": 9, "minute": 5}) == "daily at 09:05"
    assert schedules.describe({"kind": "interval", "seconds": 7200}) == "every 2h"
    assert schedules.describe({"kind": "weekly", "weekday": 0, "hour": 18, "minute": 0}) == "every Mon at 18:00"
