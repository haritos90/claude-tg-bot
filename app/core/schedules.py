"""Parse natural-language recurring schedules and compute next runs.

- Pure module: no I/O, no bot or db dependencies
- Grammar: daily, weekly on a weekday, or interval
- Times accept 24h `HH:MM` or 12h `H:MMpm`
- All times use the server's local timezone
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

# Minimum spacing for interval schedules.
# - Stops unattended jobs hammering the subscription windows
# - The handler enforces the same cap at creation
MIN_INTERVAL_SECONDS = 900  # 15 minutes

_WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "friday": 4, "fri": 4, "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}
_WD_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


class ScheduleError(ValueError):
    """Raised when a schedule phrase cannot be parsed.

    - Message is user-facing
    """


def _parse_time(s: str) -> tuple[int, int]:
    """Parse a 24h or 12h time into (hour, minute)."""
    t = s.strip().lower().replace(" ", "")
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(am|pm)?", t)
    if not m:
        raise ScheduleError(f"could not read a time from {s!r}")
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    ap = m.group(3)
    if ap:
        if not 1 <= hour <= 12:
            raise ScheduleError(f"12-hour time out of range in {s!r}")
        if ap == "pm" and hour != 12:
            hour += 12
        elif ap == "am" and hour == 12:
            hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ScheduleError(f"time out of range in {s!r}")
    return hour, minute


def parse_phrase(phrase: str) -> dict:
    """Parse a when-phrase into a spec dict.

    - Raises ScheduleError on unparseable input
    """
    p = " ".join(phrase.strip().lower().split())
    if not p:
        raise ScheduleError("empty schedule")
    # interval: every N minutes or hours, hourly
    if p in ("hourly", "every hour"):
        return {"kind": "interval", "seconds": 3600}
    m = re.fullmatch(r"(?:every\s+)?(\d+)\s*(min(?:ute)?s?|h(?:our)?s?)", p)
    if m:
        n = int(m.group(1))
        secs = n * 3600 if m.group(2).startswith("h") else n * 60
        if secs < MIN_INTERVAL_SECONDS:
            raise ScheduleError(
                f"interval too short — minimum is {MIN_INTERVAL_SECONDS // 60} minutes"
            )
        return {"kind": "interval", "seconds": secs}
    # weekly: every/weekly on weekday at time
    m = re.fullmatch(r"(?:every\s+|weekly\s+on\s+)?([a-z]+)\s+at\s+(.+)", p)
    if m and m.group(1) in _WEEKDAYS:
        hour, minute = _parse_time(m.group(2))
        return {"kind": "weekly", "weekday": _WEEKDAYS[m.group(1)], "hour": hour, "minute": minute}
    # daily: every day, daily, each day, or at time
    m = re.fullmatch(r"(?:every\s+day|daily|each\s+day)\s+at\s+(.+)", p)
    if not m:
        m = re.fullmatch(r"at\s+(.+)", p)
    if m:
        hour, minute = _parse_time(m.group(1))
        return {"kind": "daily", "hour": hour, "minute": minute}
    raise ScheduleError(f"could not understand schedule {phrase!r}")


def parse_schedule(text: str) -> tuple[dict, str]:
    """Parse `<when> | <prompt>` into (spec, prompt).

    - The pipe separator is required
    - Raises ScheduleError
    """
    if "|" not in text:
        raise ScheduleError(
            "use: <when> | <prompt>  e.g.  every day at 9:00 | summarize my GitHub notifications"
        )
    phrase, prompt = text.split("|", 1)
    spec = parse_phrase(phrase)
    prompt = prompt.strip()
    if not prompt:
        raise ScheduleError("the prompt (after '|') is empty")
    return spec, prompt


def next_run_after(spec: dict, after_ts: float) -> float:
    """Return the next fire time strictly after `after_ts`.

    - Epoch seconds, server-local
    - Daily/weekly keep wall-clock time across DST changes
    - Times inside a DST transition hour resolve per platform
    - Skew of up to one hour twice a year
    """
    kind = spec.get("kind")
    if kind == "interval":
        return after_ts + int(spec["seconds"])
    base = datetime.fromtimestamp(after_ts)
    if kind == "daily":
        cand = base.replace(hour=spec["hour"], minute=spec["minute"], second=0, microsecond=0)
        if cand.timestamp() <= after_ts:
            cand += timedelta(days=1)
        return cand.timestamp()
    if kind == "weekly":
        cand = base.replace(hour=spec["hour"], minute=spec["minute"], second=0, microsecond=0)
        cand += timedelta(days=(spec["weekday"] - cand.weekday()) % 7)
        if cand.timestamp() <= after_ts:
            cand += timedelta(days=7)
        return cand.timestamp()
    raise ScheduleError(f"unknown schedule kind {kind!r}")


def describe(spec: dict) -> str:
    """Render a spec as a short English string."""
    kind = spec.get("kind")
    if kind == "interval":
        s = int(spec["seconds"])
        return f"every {s // 3600}h" if s % 3600 == 0 else f"every {s // 60}min"
    if kind == "daily":
        return f"daily at {spec['hour']:02d}:{spec['minute']:02d}"
    if kind == "weekly":
        return f"every {_WD_NAMES[spec['weekday']]} at {spec['hour']:02d}:{spec['minute']:02d}"
    return "unknown schedule"
