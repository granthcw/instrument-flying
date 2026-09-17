"""Daypart and lead-time arithmetic.

Everything is stored in UTC. Local dayparts are derived here so that DST is
handled in exactly one place -- Leesburg shifts twice a year, and a daypart
that silently runs 11 or 13 hours would quietly corrupt the scoring.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

DAY = "day"
NIGHT = "night"


@dataclass(frozen=True)
class Daypart:
    """A local day/night period, with its UTC bounds.

    `local_date` is the calendar date the period is labelled with. A night
    period starts on `local_date` at 19:00 and ends the next morning, which is
    the convention ForeFlight and TWC both use for their night dayparts.
    """

    local_date: dt.date
    kind: str            # DAY | NIGHT
    start_utc: dt.datetime
    end_utc: dt.datetime

    @property
    def key(self) -> str:
        return f"{self.local_date.isoformat()}:{self.kind}"

    def contains(self, when_utc: dt.datetime) -> bool:
        return self.start_utc <= when_utc < self.end_utc


def _localize(date: dt.date, hour: int, tz: ZoneInfo) -> dt.datetime:
    """Local wall-clock time -> UTC, resolving DST gaps forward.

    On the spring-forward date 02:00 does not exist locally. Our dayparts start
    at 07:00 and 19:00 so this never bites in practice, but resolving it
    explicitly keeps the function safe if the split is reconfigured.
    """
    naive = dt.datetime.combine(date, dt.time(hour=hour))
    local = naive.replace(tzinfo=tz)
    # A nonexistent local time round-trips to a different wall clock; nudge it.
    if local.astimezone(dt.timezone.utc).astimezone(tz).hour != hour:
        local = (naive + dt.timedelta(hours=1)).replace(tzinfo=tz)
    return local.astimezone(dt.timezone.utc)


def daypart(local_date: dt.date, kind: str, tz_name: str,
            day_start: int = 7, night_start: int = 19) -> Daypart:
    tz = ZoneInfo(tz_name)
    if kind == DAY:
        start = _localize(local_date, day_start, tz)
        end = _localize(local_date, night_start, tz)
    elif kind == NIGHT:
        start = _localize(local_date, night_start, tz)
        end = _localize(local_date + dt.timedelta(days=1), day_start, tz)
    else:
        raise ValueError(f"unknown daypart kind: {kind!r}")
    return Daypart(local_date=local_date, kind=kind, start_utc=start, end_utc=end)


def dayparts_between(first: dt.date, last: dt.date, tz_name: str,
                     day_start: int = 7, night_start: int = 19) -> list[Daypart]:
    out: list[Daypart] = []
    day = first
    while day <= last:
        out.append(daypart(day, DAY, tz_name, day_start, night_start))
        out.append(daypart(day, NIGHT, tz_name, day_start, night_start))
        day += dt.timedelta(days=1)
    return out


def daypart_for(when_utc: dt.datetime, tz_name: str,
                day_start: int = 7, night_start: int = 19) -> Daypart:
    """Which daypart a UTC instant falls in."""
    if when_utc.tzinfo is None:
        when_utc = when_utc.replace(tzinfo=dt.timezone.utc)
    local = when_utc.astimezone(ZoneInfo(tz_name))
    if day_start <= local.hour < night_start:
        return daypart(local.date(), DAY, tz_name, day_start, night_start)
    # Before the morning boundary the night period belongs to the previous date.
    base = local.date() if local.hour >= night_start else local.date() - dt.timedelta(days=1)
    return daypart(base, NIGHT, tz_name, day_start, night_start)


def lead_hours(pulled_at_utc: dt.datetime, period_start_utc: dt.datetime) -> float:
    return (period_start_utc - pulled_at_utc).total_seconds() / 3600.0


def lead_day(pulled_at_utc: dt.datetime, target_local_date: dt.date, tz_name: str) -> int:
    """Local calendar days between the pull and the target date."""
    pull_local_date = pulled_at_utc.astimezone(ZoneInfo(tz_name)).date()
    return (target_local_date - pull_local_date).days
