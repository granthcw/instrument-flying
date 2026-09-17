"""Forecast collector for The Weather Company API (api.weather.com).

This is the v1 forecast source under test. See docs/access-notes.md for why the
ForeFlight AI Connector is not.

Two things about this module are deliberately defensive:

1. **Field names are unverified.** They follow TWC's published v3 shape, but we
   have no API Hub key in this environment to confirm them against a live
   response. Parsing therefore tolerates missing keys and records which of the
   expected fields were actually present on each pull, so the first real pull
   tells us what we have rather than throwing.

2. **Icon codes are not hard-coded.** The brief is explicit that icon-to-thunder
   mappings must be confirmed against docs or observed values. The thunder
   signal is read from `thunderIndex`/`thunderCategory` where present, and
   otherwise derived from the phrase text; every (iconCode, wxPhraseLong) pair
   seen is recorded so the mapping can be built from data. See
   docs/field-map.md.
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import logging
import re
import urllib.parse
from dataclasses import dataclass, field

from ..periods import daypart, lead_day, lead_hours, DAY, NIGHT
from ..s3 import fetch

log = logging.getLogger(__name__)

BASE_URL = "https://api.weather.com"

#: Phrase-level thunder detection. Matches "Thunderstorms", "Scattered
#: T-storms", "Strong Storms"; excludes "Snow Storm"/"Wind Storm".
_THUNDER_PHRASE = re.compile(
    r"\b(thunder|t-?storm|tstorm)\w*\b|\bstrong\s+storms?\b", re.IGNORECASE
)

#: Fields we expect on each daypart. Recorded per-pull so absences are visible.
EXPECTED_DAYPART_FIELDS = (
    "iconCode", "wxPhraseLong", "precipChance", "precipType", "qpf",
    "thunderCategory", "thunderIndex", "cloudCover", "temperature", "dayOrNight",
)
EXPECTED_HOURLY_FIELDS = (
    "iconCode", "wxPhraseLong", "precipChance", "precipType", "qpf",
    "temperature", "temperatureDewPoint", "windDirection", "windSpeed",
    "validTimeUtc", "visibility",
)


def thunder_from_phrase(phrase: str | None) -> bool | None:
    """Thunder implied by the forecast phrase. None when there is no phrase."""
    if not phrase:
        return None
    return bool(_THUNDER_PHRASE.search(phrase))


@dataclass
class PullResult:
    pulled_at: dt.datetime
    endpoint: str
    url: str
    ok: bool
    status: int | None = None
    error: str | None = None
    body: bytes | None = None
    latency_ms: int | None = None

    @property
    def sha256(self) -> str | None:
        return hashlib.sha256(self.body).hexdigest() if self.body else None

    def gzipped(self) -> bytes | None:
        """Raw body, gzipped, for append-only object storage."""
        return gzip.compress(self.body) if self.body else None


def response_schema_hash(payload: dict) -> str:
    """Stable hash of a response's key structure, ignoring values.

    Lets the daily check detect a silent upstream schema change the same way the
    connector path would have used tools/list hashes.
    """
    def shape(obj, depth=0):
        if depth > 4:
            return "..."
        if isinstance(obj, dict):
            return {k: shape(v, depth + 1) for k, v in sorted(obj.items())}
        if isinstance(obj, list):
            return [shape(obj[0], depth + 1)] if obj else []
        return type(obj).__name__
    blob = json.dumps(shape(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def build_url(endpoint: str, lat: float, lon: float, api_key: str,
              units: str = "e", language: str = "en-US") -> str:
    params = {
        "geocode": f"{lat:.4f},{lon:.4f}",
        "format": "json",
        "units": units,
        "language": language,
        "apiKey": api_key,
    }
    return f"{BASE_URL}{endpoint}?{urllib.parse.urlencode(params)}"


def pull(endpoint: str, lat: float, lon: float, api_key: str, *,
         units: str = "e", language: str = "en-US", timeout: int = 45) -> PullResult:
    """One HTTP GET against a TWC endpoint. Never raises for an HTTP failure."""
    url = build_url(endpoint, lat, lon, api_key, units, language)
    started = dt.datetime.now(dt.timezone.utc)
    try:
        body = fetch(url, timeout=timeout, retries=2)
        elapsed = int((dt.datetime.now(dt.timezone.utc) - started).total_seconds() * 1000)
        return PullResult(started, endpoint, _redact(url), True, 200,
                          body=body, latency_ms=elapsed)
    except Exception as exc:
        elapsed = int((dt.datetime.now(dt.timezone.utc) - started).total_seconds() * 1000)
        return PullResult(started, endpoint, _redact(url), False,
                          error=f"{type(exc).__name__}: {exc}", latency_ms=elapsed)


def _redact(url: str) -> str:
    """Strip the API key before anything is logged or stored."""
    return re.sub(r"(apiKey=)[^&]*", r"\1REDACTED", url)


def _series(payload: dict, key: str, n: int) -> list:
    v = payload.get(key)
    if not isinstance(v, list):
        return [None] * n
    return list(v) + [None] * (n - len(v))


@dataclass
class ParsedDaypart:
    local_date: dt.date
    daypart: str
    period_start_utc: dt.datetime
    period_end_utc: dt.datetime
    lead_hours: float
    lead_day: int
    icon_code: int | None
    wx_phrase: str | None
    precip_chance: float | None
    precip_type: str | None
    qpf_in: float | None
    thunder_category: str | None
    thunder_index: int | None
    cloud_cover: float | None
    temperature_f: float | None
    thunder_by_index: bool | None
    thunder_by_phrase: bool | None
    raw: dict = field(default_factory=dict)


def parse_daily(payload: dict, pulled_at: dt.datetime, tz_name: str,
                day_start: int = 7, night_start: int = 19
                ) -> tuple[list[ParsedDaypart], dict]:
    """Parse the v3 daily response into daypart rows.

    TWC returns dayparts as one flat array of 2N entries under `daypart[0]`,
    alternating day/night. Index 0 is null after ~3pm local -- the brief calls
    this out explicitly -- so null entries are skipped rather than coerced.

    Returns (rows, diagnostics) where diagnostics records which expected fields
    were present and the (iconCode, phrase) pairs observed.
    """
    dayparts = (payload.get("daypart") or [{}])[0] or {}
    valid_utc = payload.get("validTimeUtc") or []
    n = len(dayparts.get("dayOrNight") or [])
    diagnostics = {
        "missing_fields": [f for f in EXPECTED_DAYPART_FIELDS if f not in dayparts],
        "present_fields": [f for f in EXPECTED_DAYPART_FIELDS if f in dayparts],
        "icon_phrase_pairs": {},
        "n_dayparts": n,
        "n_null_dayparts": 0,
    }
    if not n:
        return [], diagnostics

    cols = {f: _series(dayparts, f, n) for f in EXPECTED_DAYPART_FIELDS}
    rows: list[ParsedDaypart] = []

    for i in range(n):
        don = cols["dayOrNight"][i]
        if don is None:
            # The expired daypart-0 slot. Recorded, not parsed.
            diagnostics["n_null_dayparts"] += 1
            continue
        kind = DAY if str(don).upper().startswith("D") else NIGHT
        # Each calendar day contributes a D then an N entry, so the target date
        # advances every two slots regardless of which one was nulled.
        day_index = i // 2
        base_date = _base_date(valid_utc, day_index, pulled_at, tz_name)
        part = daypart(base_date, kind, tz_name, day_start, night_start)

        icon = _int(cols["iconCode"][i])
        phrase = cols["wxPhraseLong"][i]
        if icon is not None and phrase:
            diagnostics["icon_phrase_pairs"].setdefault(str(icon), str(phrase))

        t_index = _int(cols["thunderIndex"][i])
        rows.append(ParsedDaypart(
            local_date=base_date,
            daypart=kind,
            period_start_utc=part.start_utc,
            period_end_utc=part.end_utc,
            lead_hours=lead_hours(pulled_at, part.start_utc),
            lead_day=lead_day(pulled_at, base_date, tz_name),
            icon_code=icon,
            wx_phrase=phrase,
            precip_chance=_float(cols["precipChance"][i]),
            precip_type=cols["precipType"][i],
            qpf_in=_float(cols["qpf"][i]),
            thunder_category=cols["thunderCategory"][i],
            thunder_index=t_index,
            cloud_cover=_float(cols["cloudCover"][i]),
            temperature_f=_float(cols["temperature"][i]),
            thunder_by_index=None if t_index is None else t_index >= 1,
            thunder_by_phrase=thunder_from_phrase(phrase),
            raw={f: cols[f][i] for f in EXPECTED_DAYPART_FIELDS},
        ))
    return rows, diagnostics


def _base_date(valid_utc: list, day_index: int, pulled_at: dt.datetime,
               tz_name: str) -> dt.date:
    """Local calendar date for a daily-array index."""
    from zoneinfo import ZoneInfo
    if day_index < len(valid_utc) and valid_utc[day_index]:
        return dt.datetime.fromtimestamp(
            int(valid_utc[day_index]), tz=ZoneInfo(tz_name)).date()
    start = pulled_at.astimezone(ZoneInfo(tz_name)).date()
    return start + dt.timedelta(days=day_index)


@dataclass
class ParsedHour:
    valid_utc: dt.datetime
    lead_hours: float
    icon_code: int | None
    wx_phrase: str | None
    precip_chance: float | None
    precip_type: str | None
    qpf_in: float | None
    temperature_f: float | None
    dewpoint_f: float | None
    wind_dir: int | None
    wind_kt: float | None
    visibility_sm: float | None
    ceiling_ft: int | None
    thunder_by_phrase: bool | None
    raw: dict = field(default_factory=dict)


def parse_hourly(payload: dict, pulled_at: dt.datetime) -> tuple[list[ParsedHour], dict]:
    """Parse the v3 hourly response.

    Note: TWC's consumer v3 hourly product carries no cloud-ceiling field. The
    `ceiling_ft` column is therefore populated only if a ceiling key turns up in
    a live response; otherwise it stays null and hourly flight-category scoring
    falls back to the NBM ceiling/visibility baseline. This is flagged in the
    README as an open limitation, not worked around silently.
    """
    valid = payload.get("validTimeUtc") or []
    n = len(valid)
    diagnostics = {
        "missing_fields": [f for f in EXPECTED_HOURLY_FIELDS if f not in payload],
        "present_fields": [f for f in EXPECTED_HOURLY_FIELDS if f in payload],
        "icon_phrase_pairs": {},
        "n_hours": n,
        "ceiling_key": next((k for k in payload if "ceiling" in k.lower()), None),
    }
    if not n:
        return [], diagnostics

    cols = {f: _series(payload, f, n) for f in EXPECTED_HOURLY_FIELDS}
    ceil_col = _series(payload, diagnostics["ceiling_key"], n) if diagnostics["ceiling_key"] else [None] * n

    rows: list[ParsedHour] = []
    for i in range(n):
        if valid[i] is None:
            continue
        when = dt.datetime.fromtimestamp(int(valid[i]), tz=dt.timezone.utc)
        icon = _int(cols["iconCode"][i])
        phrase = cols["wxPhraseLong"][i]
        if icon is not None and phrase:
            diagnostics["icon_phrase_pairs"].setdefault(str(icon), str(phrase))
        rows.append(ParsedHour(
            valid_utc=when,
            lead_hours=lead_hours(pulled_at, when),
            icon_code=icon,
            wx_phrase=phrase,
            precip_chance=_float(cols["precipChance"][i]),
            precip_type=cols["precipType"][i],
            qpf_in=_float(cols["qpf"][i]),
            temperature_f=_float(cols["temperature"][i]),
            dewpoint_f=_float(cols["temperatureDewPoint"][i]),
            wind_dir=_int(cols["windDirection"][i]),
            wind_kt=_float(cols["windSpeed"][i]),
            visibility_sm=_float(cols["visibility"][i]),
            ceiling_ft=_int(ceil_col[i]),
            thunder_by_phrase=thunder_from_phrase(phrase),
            raw={f: cols[f][i] for f in EXPECTED_HOURLY_FIELDS},
        ))
    return rows, diagnostics


def _int(v):
    try:
        return None if v is None else int(v)
    except (TypeError, ValueError):
        return None


def _float(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None
