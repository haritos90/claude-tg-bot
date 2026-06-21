"""#188: natural-language recurring-schedule parsing + next-run computation.

PURE module (no I/O, no bot/db deps) so it is fully unit-testable. The DB store lives
in ``db`` (the ``schedules`` table) and the runner loop in ``sessions`` (``_schedule_loop``);
this module only turns a user phrase into a structured spec, computes the next fire time,
and renders a spec back to a human string.

Grammar (the ``<when>`` half of ``/schedule <when> | <prompt>``), case-insensitive:
  - daily   : ``daily at 9:00`` · ``every day at 09:00`` · ``at 9am``
  - weekly  : ``every monday at 9:00`` · ``mon at 21:30`` · ``weekly on fri at 18:00``
  - interval: ``every 30 minutes`` · ``every 2 hours`` · ``hourly``
Times accept ``HH``/``HH:MM`` (24h) or ``Ham``/``H:MMpm`` (12h).

All times are in the SERVER's local timezone (the runner uses the same ``datetime``).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

# Minimum spacing for an INTERVAL schedule, so an unattended job can't hammer the
# subscription windows (daily/weekly are naturally bounded). Mirrored by the cap the
# handler enforces at creation.
MIN_INTERVAL_SECONDS = 900  # 15 minutes

_WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "friday": 4, "fri": 4, "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}
_WD_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


class ScheduleError(ValueError):
    """Raised when a schedule phrase can't be parsed (message is user-facing)."""


def _parse_time(s: str) -> tuple[int, int]:
    """Parse ``9`` / ``9:30`` / ``09:00`` / ``9am`` / ``9:30pm`` → (hour, minute)."""
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
    """Parse a ``<when>`` phrase into a structured spec dict (raises ScheduleError)."""
    p = " ".join(phrase.strip().lower().split())
    if not p:
        raise ScheduleError("empty schedule")
    # interval: "every 30 minutes" / "30 min" / "every 2 hours" / "hourly"
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
    # weekly: "(every|weekly on) <weekday> at <time>"
    m = re.fullmatch(r"(?:every\s+|weekly\s+on\s+)?([a-z]+)\s+at\s+(.+)", p)
    if m and m.group(1) in _WEEKDAYS:
        hour, minute = _parse_time(m.group(2))
        return {"kind": "weekly", "weekday": _WEEKDAYS[m.group(1)], "hour": hour, "minute": minute}
    # daily: "(every day|daily|each day|at) <time>"
    m = re.fullmatch(r"(?:every\s+day|daily|each\s+day)\s+at\s+(.+)", p)
    if not m:
        m = re.fullmatch(r"at\s+(.+)", p)
    if m:
        hour, minute = _parse_time(m.group(1))
        return {"kind": "daily", "hour": hour, "minute": minute}
    raise ScheduleError(f"could not understand schedule {phrase!r}")


def parse_schedule(text: str) -> tuple[dict, str]:
    """Parse ``<when> | <prompt>`` → (spec, prompt). The ``|`` separator is required
    (it disambiguates the schedule phrase from the prompt). Raises ScheduleError."""
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
    """The next fire time (epoch seconds, server-local) strictly AFTER ``after_ts``.

    Daily/weekly preserve the wall-clock time across days (naive ``replace`` + ``timestamp``),
    so they track the server's local timezone including DST. Caveat (#258): a target time that
    falls inside a DST transition hour (a non-existent or repeated wall-clock time) resolves to
    whatever the platform's ``timestamp()`` picks for that hour — acceptable for a best-effort
    scheduler; the runner's 30s sweep tolerates the at-most-1h skew on those two days a year."""
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
    """Render a spec back to a short human string (English; neutral)."""
    kind = spec.get("kind")
    if kind == "interval":
        s = int(spec["seconds"])
        return f"every {s // 3600}h" if s % 3600 == 0 else f"every {s // 60}min"
    if kind == "daily":
        return f"daily at {spec['hour']:02d}:{spec['minute']:02d}"
    if kind == "weekly":
        return f"every {_WD_NAMES[spec['weekday']]} at {spec['hour']:02d}:{spec['minute']:02d}"
    return "unknown schedule"
