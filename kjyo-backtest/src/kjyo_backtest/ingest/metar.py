"""METAR observations from the IEM ASOS/AWOS download service.

Supplies the truth for ceiling, visibility and flight category, plus a
cross-check on thunder. At KJYO the thunder cross-check is weak by design --
see docs/thunder-reporting.md -- so GLM stays the primary thunder label.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import logging
import re
import urllib.parse
from dataclasses import dataclass

from ..s3 import fetch

log = logging.getLogger(__name__)

IEM_ASOS = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"

#: Sky-cover codes that constitute a ceiling.
CEILING_COVERS = ("BKN", "OVC", "VV")

VFR, MVFR, IFR, LIFR = "VFR", "MVFR", "IFR", "LIFR"
#: Worst-first, so `min(..., key=CATEGORY_RANK.get)` picks the limiting one.
CATEGORY_RANK = {LIFR: 0, IFR: 1, MVFR: 2, VFR: 3}

# TS as a present-weather group: optional intensity, optional descriptor,
# then TS with an optional precipitation type. Deliberately anchored so that
# tokens like "TSNO" (thunderstorm sensor inoperative) do not match.
_TS_BODY = re.compile(r"(?:^|\s)(?:[-+]|VC)?(?:TS)(?:RA|SN|GR|GS|PL|DZ)?(?=\s|$)")
_VCTS = re.compile(r"(?:^|\s)VCTS(?=\s|$)")


@dataclass
class MetarObs:
    site_id: str
    valid_utc: dt.datetime
    ceiling_ft: int | None
    vis_sm: float | None
    flight_category: str | None
    wxcodes: str | None
    temp_f: float | None
    dewpoint_f: float | None
    wind_dir: int | None
    wind_kt: float | None
    p01i_in: float | None
    ts_in_body: bool
    vcts: bool
    ltg_remark: bool
    raw_metar: str | None


def ceiling_from_layers(layers: list[tuple[str | None, float | None]]) -> int | None:
    """Lowest broken/overcast/vertical-visibility layer, in feet AGL.

    Returns None when the sky is clear or only few/scattered -- "no ceiling",
    which for flight-category purposes is unlimited, not zero.
    """
    heights = [
        int(h) for cover, h in layers
        if cover in CEILING_COVERS and h is not None
    ]
    return min(heights) if heights else None


def flight_category(ceiling_ft: int | None, vis_sm: float | None) -> str | None:
    """FAA flight category -- the worse of the ceiling and visibility category.

    Boundary handling follows the FAA table: a value sitting exactly on a
    boundary takes the *less* restrictive category (3 sm is MVFR, not IFR;
    1,000 ft is MVFR, not IFR).
    """
    if ceiling_ft is None and vis_sm is None:
        return None

    def cat_ceiling(c: int | None) -> str:
        if c is None:
            return VFR            # no ceiling reported == unlimited
        if c < 500:
            return LIFR
        if c < 1000:
            return IFR
        if c <= 3000:
            return MVFR
        return VFR

    def cat_vis(v: float | None) -> str:
        if v is None:
            return VFR
        if v < 1:
            return LIFR
        if v < 3:
            return IFR
        if v <= 5:
            return MVFR
        return VFR

    return min(cat_ceiling(ceiling_ft), cat_vis(vis_sm), key=CATEGORY_RANK.get)


def _f(value: str | None) -> float | None:
    if value is None or value in ("", "M", "None", "T"):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_rows(csv_text: str, site_id: str) -> list[MetarObs]:
    out: list[MetarObs] = []
    for row in csv.DictReader(io.StringIO(csv_text)):
        valid = row.get("valid")
        if not valid:
            continue
        try:
            when = dt.datetime.strptime(valid, "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
        layers = [
            (row.get(f"skyc{i}") or None, _f(row.get(f"skyl{i}")))
            for i in range(1, 5)
        ]
        ceiling = ceiling_from_layers(layers)
        vis = _f(row.get("vsby"))
        raw = row.get("metar") or ""
        body = raw.split(" RMK")[0]
        out.append(
            MetarObs(
                site_id=site_id,
                valid_utc=when,
                ceiling_ft=ceiling,
                vis_sm=vis,
                flight_category=flight_category(ceiling, vis),
                wxcodes=(row.get("wxcodes") or None),
                temp_f=_f(row.get("tmpf")),
                dewpoint_f=_f(row.get("dwpf")),
                wind_dir=int(d) if (d := _f(row.get("drct"))) is not None else None,
                wind_kt=_f(row.get("sknt")),
                p01i_in=_f(row.get("p01i")),
                ts_in_body=bool(_TS_BODY.search(body)),
                vcts=bool(_VCTS.search(body)),
                ltg_remark="LTG" in raw,
                raw_metar=raw or None,
            )
        )
    return out


def fetch_range(iem_id: str, site_id: str, start: dt.date, end: dt.date,
                timeout: int = 180) -> list[MetarObs]:
    """Download and parse METARs for [start, end). `end` is exclusive."""
    params = {
        "station": iem_id, "data": "all", "tz": "UTC", "format": "onlycomma",
        "latlon": "no", "report_type": "3", "missing": "empty", "trace": "0.0001",
        "year1": start.year, "month1": start.month, "day1": start.day,
        "year2": end.year, "month2": end.month, "day2": end.day,
    }
    url = f"{IEM_ASOS}?{urllib.parse.urlencode(params)}"
    text = fetch(url, timeout=timeout).decode("utf-8", errors="replace")
    rows = parse_rows(text, site_id)
    log.info("METAR %s %s..%s -> %d obs", site_id, start, end, len(rows))
    return rows
