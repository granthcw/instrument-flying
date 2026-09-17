"""GOES GLM lightning: flash counts near a site, aggregated per hour.

GLM L2 LCFA granules cover 20 seconds each, so a UTC day is 4,320 files of
roughly 350 KB. We stream them, keep only the flashes inside the widest scoring
radius, and throw the raw granule away -- the brief calls for aggregates only,
and storing 1.5 GB/day of raw netCDF would serve no purpose.

GOES-East moved from GOES-16 to GOES-19 on 2025-04-04; `bucket_for` picks the
right archive so backfill and forward collection use one code path.
"""

from __future__ import annotations

import datetime as dt
import io
import logging
import os
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field

import netCDF4
import numpy as np

from ..geo import bounding_box, haversine_nm
from ..s3 import fetch_many, list_keys

log = logging.getLogger(__name__)

GOES19_START = dt.date(2025, 4, 4)
GLM_PRODUCT = "GLM-L2-LCFA"
#: quality_flag == 0 is the "good" flash population in the L2 product.
GOOD_QUALITY = 0


def bucket_for(day: dt.date) -> str:
    """The GOES-East archive that carries a given date."""
    return "noaa-goes19" if day >= GOES19_START else "noaa-goes16"


@dataclass
class GlmHourAgg:
    """Flash counts for one site-hour, at each scoring radius."""

    hour_utc: dt.datetime
    counts: dict[float, int] = field(default_factory=dict)
    granules_expected: int = 0
    granules_read: int = 0
    granules_missing: int = 0
    granules_failed: int = 0

    @property
    def complete(self) -> bool:
        """True when we read every granule we expected for the hour.

        Incompleteness matters: a zero flash count from a partly-read hour is
        not evidence of "no thunder", and scoring must be able to drop it.
        """
        return self.granules_failed == 0 and self.granules_read == self.granules_expected


def _granule_hour_prefix(day: dt.date, hour: int) -> str:
    return f"{GLM_PRODUCT}/{day.year}/{day.timetuple().tm_yday:03d}/{hour:02d}/"


def _read_flashes(blob: bytes) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (lat, lon, utc_datetime64) for good-quality flashes in a granule.

    netCDF4 needs a real file for the classic reader in some builds, so the
    in-memory path is tried first and falls back to a temp file.
    """
    try:
        ds = netCDF4.Dataset("inmem", mode="r", memory=blob)
    except Exception:
        with tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as tmp:
            tmp.write(blob)
            path = tmp.name
        try:
            ds = netCDF4.Dataset(path)
        finally:
            os.unlink(path)
    with ds:
        if "flash_lat" not in ds.variables or len(ds.dimensions.get("number_of_flashes", [])) == 0:
            empty = np.array([], dtype="float64")
            return empty, empty, np.array([], dtype="datetime64[ns]")
        lat = np.asarray(ds.variables["flash_lat"][:], dtype="float64")
        lon = np.asarray(ds.variables["flash_lon"][:], dtype="float64")
        qf = np.asarray(ds.variables["flash_quality_flag"][:], dtype="int32")
        tvar = ds.variables["flash_time_offset_of_first_event"]
        # units are "seconds since <granule window start>"; num2date handles the
        # scale_factor/add_offset that netCDF4 has already applied.
        times = netCDF4.num2date(
            np.asarray(tvar[:], dtype="float64"),
            tvar.units,
            only_use_cftime_datetimes=False,
            only_use_python_datetimes=True,
        )
        times = np.array([np.datetime64(t) for t in np.atleast_1d(times)], dtype="datetime64[ns]")

    good = qf == GOOD_QUALITY
    return lat[good], lon[good], times[good]


def aggregate_hour(
    day: dt.date,
    hour: int,
    site_lat: float,
    site_lon: float,
    radii_nm: tuple[float, ...] = (5.0, 10.0, 20.0),
    workers: int = 16,
) -> GlmHourAgg:
    """Count flashes within each radius of a site for one UTC hour."""
    bucket = bucket_for(day)
    keys = list_keys(bucket, _granule_hour_prefix(day, hour))
    agg = GlmHourAgg(
        hour_utc=dt.datetime(day.year, day.month, day.day, hour, tzinfo=dt.timezone.utc),
        counts={r: 0 for r in radii_nm},
        granules_expected=len(keys),
    )
    if not keys:
        return agg

    widest = max(radii_nm)
    min_lat, max_lat, min_lon, max_lon = bounding_box(site_lat, site_lon, widest)
    urls = [f"https://{bucket}.s3.amazonaws.com/{k}" for k in keys]

    for _url, blob, err in fetch_many(urls, workers=workers):
        if err is not None:
            agg.granules_failed += 1
            continue
        if blob is None:
            agg.granules_missing += 1
            continue
        try:
            lat, lon, _times = _read_flashes(blob)
        except Exception as exc:
            log.warning("unreadable GLM granule %s: %s", _url, exc)
            agg.granules_failed += 1
            continue
        agg.granules_read += 1
        if lat.size == 0:
            continue
        # Cheap box filter first; haversine only on the handful that survive.
        near = (lat >= min_lat) & (lat <= max_lat) & (lon >= min_lon) & (lon <= max_lon)
        if not near.any():
            continue
        for flat, flon in zip(lat[near], lon[near]):
            d = haversine_nm(site_lat, site_lon, float(flat), float(flon))
            for r in radii_nm:
                if d <= r:
                    agg.counts[r] += 1
    return agg


def aggregate_day(
    day: dt.date,
    site_lat: float,
    site_lon: float,
    radii_nm: tuple[float, ...] = (5.0, 10.0, 20.0),
    hours: range | None = None,
    workers: int = 16,
) -> list[GlmHourAgg]:
    """Aggregate every UTC hour of a day. Returns one row per hour."""
    out = []
    for hour in (hours if hours is not None else range(24)):
        agg = aggregate_hour(day, hour, site_lat, site_lon, radii_nm, workers=workers)
        log.info(
            "GLM %s %02dZ: %s (granules %d/%d, missing %d, failed %d)",
            day, hour, agg.counts, agg.granules_read, agg.granules_expected,
            agg.granules_missing, agg.granules_failed,
        )
        out.append(agg)
    return out
