"""NBM/GFS MOS station guidance from the IEM MOS archive.

IEM archives only the 01/07/13/19 UTC cycles since February 2020.

A caveat that matters for scoring: IEM exposes the thunder fields as
`t06_1`/`t06_2`/`t12_1`/`t12_2`, and for NBS the mapping from those columns to
"thunderstorm probability" is *not* documented anywhere we could verify. On
observed runs `t06_2` sometimes exceeds the same row's `p06`, which a true
thunder probability should not do. We therefore store all four columns
verbatim and make no semantic claim here; `scoring.baselines` picks the column
empirically by correlating each candidate against observed GLM thunder, and
the report prints which one won. See docs/field-map.md.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import urllib.parse
from dataclasses import dataclass, field

from ..s3 import fetch

log = logging.getLogger(__name__)

IEM_MOS_API = "https://mesonet.agron.iastate.edu/api/1/mos.json"
ARCHIVED_CYCLES_UTC = (1, 7, 13, 19)
#: Candidate thunder columns, resolved empirically rather than assumed.
THUNDER_CANDIDATES = ("t06_1", "t06_2", "t12_1", "t12_2")
#: IEM uses -88 for "no ceiling / unlimited" in the cig column.
CIG_UNLIMITED = -88


@dataclass
class MosRow:
    site_id: str
    model: str
    runtime_utc: dt.datetime
    ftime_utc: dt.datetime
    pop_06: float | None
    pop_12: float | None
    thunder_raw: dict[str, float | None] = field(default_factory=dict)
    ceiling_code: int | None = None
    vis_code: int | None = None
    temp_f: float | None = None
    dewpoint_f: float | None = None
    raw: dict = field(default_factory=dict)


def _dtparse(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M"):
        try:
            return dt.datetime.strptime(value, fmt).replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
    return None


def _num(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_run(site_id: str, model: str, runtime_utc: dt.datetime,
              timeout: int = 90) -> list[MosRow]:
    """One model cycle for one station. Empty list when the cycle is absent."""
    params = {
        "station": site_id,
        "model": model,
        "runtime": runtime_utc.strftime("%Y-%m-%dT%H:%MZ"),
    }
    url = f"{IEM_MOS_API}?{urllib.parse.urlencode(params)}"
    try:
        payload = json.loads(fetch(url, timeout=timeout))
    except FileNotFoundError:
        return []
    rows = payload.get("data") or []
    out: list[MosRow] = []
    for r in rows:
        ftime = _dtparse(r.get("ftime"))
        if ftime is None:
            continue
        cig = _num(r.get("cig"))
        out.append(
            MosRow(
                site_id=site_id,
                model=model,
                runtime_utc=runtime_utc,
                ftime_utc=ftime,
                pop_06=_num(r.get("p06")),
                pop_12=_num(r.get("p12")),
                thunder_raw={k: _num(r.get(k)) for k in THUNDER_CANDIDATES},
                ceiling_code=None if cig is None else int(cig),
                vis_code=None if (v := _num(r.get("vis"))) is None else int(v),
                temp_f=_num(r.get("tmp")),
                dewpoint_f=_num(r.get("dpt")),
                raw=r,
            )
        )
    return out


def fetch_day(site_id: str, model: str, day: dt.date,
              cycles: tuple[int, ...] = ARCHIVED_CYCLES_UTC) -> list[MosRow]:
    out: list[MosRow] = []
    for hour in cycles:
        runtime = dt.datetime(day.year, day.month, day.day, hour, tzinfo=dt.timezone.utc)
        rows = fetch_run(site_id, model, runtime)
        log.info("MOS %s %s %s -> %d rows", site_id, model, runtime, len(rows))
        out.extend(rows)
    return out
