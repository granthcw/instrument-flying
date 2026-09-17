"""SPC convective outlooks, evaluated point-in-polygon at a site.

Pulled from SPC's own archive, which serves per-issuance GeoJSON directly:
    /products/outlook/archive/{YYYY}/day{N}otlk_{YYYYMMDD}_{HHMM}_cat.lyr.geojson

IEM's geojson/spc_outlook.py endpoint has moved and now redirects to the API
index, so SPC is used as the source of record instead.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass

from ..s3 import fetch

log = logging.getLogger(__name__)

SPC_ARCHIVE = "https://www.spc.noaa.gov/products/outlook/archive"

#: Categorical outlook ranking, least to most severe.
CATEGORY_RANK = {
    "TSTM": 1, "MRGL": 2, "SLGT": 3, "ENH": 4, "MDT": 5, "HIGH": 6,
}
DAY_CYCLES = {
    1: ("0100", "1200", "1300", "1630", "2000"),
    2: ("0600", "1730"),
    3: ("0730",),
}


@dataclass
class SpcOutlook:
    site_id: str
    day: int
    issue_utc: dt.datetime
    valid_local_date: dt.date
    category: str | None
    category_rank: int
    url: str


def _point_in_ring(lat: float, lon: float, ring: list) -> bool:
    """Ray-casting test for one linear ring of [lon, lat] pairs."""
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > lat) != (y2 > lat):
            xin = (x2 - x1) * (lat - y1) / (y2 - y1) + x1
            if lon < xin:
                inside = not inside
    return inside


def _point_in_geometry(lat: float, lon: float, geom: dict) -> bool:
    """Point-in-polygon honouring holes, for Polygon and MultiPolygon."""
    gtype = geom.get("type")
    polys = []
    if gtype == "Polygon":
        polys = [geom["coordinates"]]
    elif gtype == "MultiPolygon":
        polys = geom["coordinates"]
    else:
        return False
    for poly in polys:
        if not poly:
            continue
        if _point_in_ring(lat, lon, poly[0]):
            # Inside the outer ring -- reject if it falls in a hole.
            if not any(_point_in_ring(lat, lon, hole) for hole in poly[1:]):
                return True
    return False


def outlook_url(issue_date: dt.date, day: int, cycle: str) -> str:
    return (f"{SPC_ARCHIVE}/{issue_date.year}/"
            f"day{day}otlk_{issue_date:%Y%m%d}_{cycle}_cat.lyr.geojson")


def fetch_outlook(site_id: str, lat: float, lon: float, issue_date: dt.date,
                  day: int, cycle: str) -> SpcOutlook | None:
    """Highest-severity category covering the site for one issuance."""
    url = outlook_url(issue_date, day, cycle)
    try:
        payload = json.loads(fetch(url, timeout=60))
    except FileNotFoundError:
        return None

    best: str | None = None
    for feat in payload.get("features", []):
        props = feat.get("properties") or {}
        label = props.get("LABEL") or props.get("DN") or props.get("label")
        geom = feat.get("geometry")
        if not label or not geom:
            continue
        label = str(label).upper()
        if label not in CATEGORY_RANK:
            continue
        if CATEGORY_RANK[label] <= CATEGORY_RANK.get(best or "", 0):
            continue
        if _point_in_geometry(lat, lon, geom):
            best = label

    issue_utc = dt.datetime.combine(
        issue_date, dt.time(int(cycle[:2]), int(cycle[2:])), tzinfo=dt.timezone.utc
    )
    # Day-N outlooks are valid for the convective day starting 12Z N-1 days out.
    valid_date = issue_date + dt.timedelta(days=day - 1)
    return SpcOutlook(
        site_id=site_id, day=day, issue_utc=issue_utc, valid_local_date=valid_date,
        category=best, category_rank=CATEGORY_RANK.get(best or "", 0), url=url,
    )


def fetch_day(site_id: str, lat: float, lon: float, issue_date: dt.date) -> list[SpcOutlook]:
    out = []
    for day, cycles in DAY_CYCLES.items():
        for cycle in cycles:
            o = fetch_outlook(site_id, lat, lon, issue_date, day, cycle)
            if o is not None:
                out.append(o)
    return out
