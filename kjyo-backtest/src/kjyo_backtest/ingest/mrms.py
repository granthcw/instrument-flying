"""MRMS precipitation type and amount at a point.

Two products:
  * PrecipFlag  -- categorical precip type on a 2-minute cadence, used to
    separate convective from stratiform precipitation.
  * MultiSensor_QPE_01H_Pass2 -- hourly precip accumulation, used for the
    "precip occurred" label. Falls back to RadarOnly when Pass2 is absent.

MRMS is a 0.01-degree CONUS grid in GRIB2. We only ever read a handful of
pixels around the field, so the whole file is decoded and immediately
discarded; nothing raw is persisted.
"""

from __future__ import annotations

import datetime as dt
import gzip
import logging
import os
import tempfile
from dataclasses import dataclass, field

import numpy as np

from ..geo import haversine_nm, nm_to_km
from ..s3 import fetch, list_keys

log = logging.getLogger(__name__)

MRMS_BUCKET = "noaa-mrms-pds"
PRECIP_FLAG_PRODUCT = "CONUS/PrecipFlag_00.00"
QPE_PRODUCT = "CONUS/MultiSensor_QPE_01H_Pass2_00.00"
QPE_FALLBACK_PRODUCT = "CONUS/RadarOnly_QPE_01H_00.00"

MM_PER_INCH = 25.4

#: MRMS PrecipFlag categories. Verified against live data -- see
#: docs/mrms-precipflag.md for the observed value census.
PRECIP_FLAG_LABELS = {
    0: "none",
    1: "warm_stratiform",
    3: "snow",
    6: "convective",
    7: "hail",
    10: "cool_stratiform",
    91: "tropical_stratiform",
    96: "tropical_convective",
}
CONVECTIVE_FLAGS = frozenset({6, 7, 96})
STRATIFORM_FLAGS = frozenset({1, 10, 91})
FROZEN_FLAGS = frozenset({3})
#: Ranked worst-first so "most severe flag in the neighbourhood" is a max().
FLAG_SEVERITY = {0: 0, 3: 1, 1: 2, 10: 2, 91: 3, 6: 4, 96: 4, 7: 5}

# MRMS encodes "no coverage" as a large negative sentinel.
MISSING_SENTINEL = -900.0


@dataclass
class PrecipFlagSample:
    valid_utc: dt.datetime
    flag_at_site: int | None
    flag_max_severity_nearby: int | None
    nearby_flags: dict[int, int] = field(default_factory=dict)


@dataclass
class QpeSample:
    valid_utc: dt.datetime
    qpe_in: float | None
    product: str


def _decode_point(blob_gz: bytes, lat: float, lon: float, radius_km: float = 0.0):
    """Decode a gzipped MRMS GRIB2 and return (site_value, nearby_values, meta).

    Uses the eccodes element API rather than xarray/cfgrib. MRMS is a 7000x3500
    CONUS grid; materialising all 24.5 M points to read ~200 of them costs about
    11.5 s per file, against 0.6 s for a batched element read. Over a full
    season backfill that is the difference between ~150 hours and ~8.
    """
    import eccodes as ec

    raw = gzip.decompress(blob_gz)
    with tempfile.NamedTemporaryFile(suffix=".grib2", delete=False) as tmp:
        tmp.write(raw)
        path = tmp.name
    try:
        with open(path, "rb") as fh:
            gid = ec.codes_grib_new_from_file(fh)
            if gid is None:
                raise ValueError("no GRIB message in file")
            try:
                ni = int(ec.codes_get(gid, "Ni"))
                nj = int(ec.codes_get(gid, "Nj"))
                lat0 = float(ec.codes_get(gid, "latitudeOfFirstGridPointInDegrees"))
                lon0 = float(ec.codes_get(gid, "longitudeOfFirstGridPointInDegrees"))
                di = float(ec.codes_get(gid, "iDirectionIncrementInDegrees"))
                dj = float(ec.codes_get(gid, "jDirectionIncrementInDegrees"))
                name = str(ec.codes_get(gid, "shortName"))

                # The grid runs north-to-south and west-to-east from (lat0, lon0),
                # with longitude expressed in the 0..360 convention.
                lon360 = lon % 360.0
                j0 = int(round((lat0 - lat) / dj))
                i0 = int(round((lon360 - lon0) / di))
                if not (0 <= j0 < nj and 0 <= i0 < ni):
                    raise ValueError(f"point {lat},{lon} is outside the MRMS domain")

                def cell_latlon(jj: int, ii: int) -> tuple[float, float]:
                    plat = lat0 - jj * dj
                    plon = lon0 + ii * di
                    return plat, (plon - 360.0 if plon > 180 else plon)

                offsets = [(0, 0)]
                if radius_km > 0:
                    pad_y = int(np.ceil(radius_km / (dj * 111.32))) + 1
                    km_per_cell_x = 111.32 * float(np.cos(np.radians(lat))) * di
                    pad_x = int(np.ceil(radius_km / max(km_per_cell_x, 1e-6))) + 1
                    offsets = [
                        (dy, dx)
                        for dy in range(-pad_y, pad_y + 1)
                        for dx in range(-pad_x, pad_x + 1)
                        if 0 <= j0 + dy < nj and 0 <= i0 + dx < ni
                    ]
                    if (0, 0) not in offsets:
                        offsets.append((0, 0))

                indices = [(j0 + dy) * ni + (i0 + dx) for dy, dx in offsets]
                # One batched read: eccodes decompresses the message once.
                values = ec.codes_get_double_elements(gid, "values", indices)

                site_val = float("nan")
                nearby: list[float] = []
                radius_nm = radius_km * 0.539957
                for (dy, dx), value in zip(offsets, values):
                    if dy == 0 and dx == 0:
                        site_val = float(value)
                    if radius_km > 0:
                        plat, plon = cell_latlon(j0 + dy, i0 + dx)
                        if haversine_nm(lat, lon, plat, plon) <= radius_nm:
                            nearby.append(float(value))
                return site_val, nearby, {"name": name, "ni": ni, "nj": nj}
            finally:
                ec.codes_release(gid)
    finally:
        if os.path.exists(path):
            os.unlink(path)


def _clean(v: float | None) -> float | None:
    if v is None or v <= MISSING_SENTINEL or not np.isfinite(v):
        return None
    return v


def precip_flag_key(when: dt.datetime) -> str:
    d = when.strftime("%Y%m%d")
    return (f"{PRECIP_FLAG_PRODUCT}/{d}/"
            f"MRMS_PrecipFlag_00.00_{d}-{when:%H%M%S}.grib2.gz")


def qpe_key(when: dt.datetime, product: str = QPE_PRODUCT) -> str:
    d = when.strftime("%Y%m%d")
    stem = product.split("/")[-1]
    return f"{product}/{d}/MRMS_{stem}_{d}-{when:%H%M%S}.grib2.gz"


def sample_precip_flag(when_utc: dt.datetime, lat: float, lon: float,
                       radius_km: float = 5.0) -> PrecipFlagSample | None:
    """Read PrecipFlag at one instant. Returns None when the file is absent."""
    url = f"https://{MRMS_BUCKET}.s3.amazonaws.com/{precip_flag_key(when_utc)}"
    try:
        blob = fetch(url)
    except FileNotFoundError:
        return None
    site, nearby, _ = _decode_point(blob, lat, lon, radius_km)
    site_i = None if _clean(site) is None else int(round(site))
    counts: dict[int, int] = {}
    for v in nearby:
        if _clean(v) is None:
            continue
        counts[int(round(v))] = counts.get(int(round(v)), 0) + 1
    worst = max(counts, key=lambda f: FLAG_SEVERITY.get(f, 0)) if counts else None
    return PrecipFlagSample(
        valid_utc=when_utc,
        flag_at_site=site_i,
        flag_max_severity_nearby=worst,
        nearby_flags=counts,
    )


def sample_qpe_hour(hour_utc: dt.datetime, lat: float, lon: float) -> QpeSample | None:
    """Hourly QPE at the site pixel, in inches. Falls back to RadarOnly."""
    for product in (QPE_PRODUCT, QPE_FALLBACK_PRODUCT):
        url = f"https://{MRMS_BUCKET}.s3.amazonaws.com/{qpe_key(hour_utc, product)}"
        try:
            blob = fetch(url)
        except FileNotFoundError:
            continue
        site, _, _ = _decode_point(blob, lat, lon, 0.0)
        mm = _clean(site)
        return QpeSample(
            valid_utc=hour_utc,
            qpe_in=None if mm is None else mm / MM_PER_INCH,
            product=product,
        )
    return None


def flag_class(flag: int | None) -> str | None:
    """Map a raw PrecipFlag to the convective/stratiform label used in scoring."""
    if flag is None:
        return None
    if flag in CONVECTIVE_FLAGS:
        return "convective"
    if flag in STRATIFORM_FLAGS:
        return "stratiform"
    if flag in FROZEN_FLAGS:
        return "frozen"
    if flag == 0:
        return "none"
    return "other"
