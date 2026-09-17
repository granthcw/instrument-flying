"""Turn raw observations into the labels the brief scores against.

The definitions are deliberately explicit about what "unknown" means. A period
whose lightning hours were only partly ingested cannot be labelled "no thunder"
-- absence of data is not absence of lightning -- so those come back as None and
scoring drops them rather than silently counting them as correct negatives.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from collections.abc import Iterable

CONVECTIVE, STRATIFORM, NO_PRECIP, UNKNOWN = "convective", "stratiform", "none", None


@dataclass
class LightningHour:
    hour_utc: dt.datetime
    flashes_5nm: int
    flashes_10nm: int
    flashes_20nm: int
    complete: bool

    def count(self, radius_nm: float) -> int:
        return {5.0: self.flashes_5nm, 10.0: self.flashes_10nm,
                20.0: self.flashes_20nm}[radius_nm]


@dataclass
class MrmsHour:
    hour_utc: dt.datetime
    qpe_in: float | None
    flag_convective_samples: int
    flag_stratiform_samples: int
    flag_samples: int


def thunder_observed(hours: Iterable[LightningHour], radius_nm: float = 10.0,
                     min_flashes: int = 1) -> bool | None:
    """True when any hour in the period had >= min_flashes within the radius.

    Returns None when no hour is present, or when every hour that could have
    carried the signal is incomplete -- see the module docstring.
    """
    hours = list(hours)
    if not hours:
        return None
    if any(h.count(radius_nm) >= min_flashes for h in hours):
        return True          # a positive is trustworthy even from a partial hour
    if not all(h.complete for h in hours):
        return None          # a negative from incomplete data is not evidence
    return False


def precip_observed(hours: Iterable[MrmsHour], threshold_in: float = 0.01) -> bool | None:
    """True when at least one hour reached the QPE threshold."""
    hours = list(hours)
    known = [h for h in hours if h.qpe_in is not None]
    if not known:
        return None
    if any(h.qpe_in >= threshold_in for h in known):
        return True
    if len(known) < len(hours):
        return None
    return False


def precip_class(mrms_hours: Iterable[MrmsHour], lightning_hours: Iterable[LightningHour],
                 threshold_in: float = 0.01, radius_nm: float = 10.0) -> str | None:
    """Classify a period as convective, stratiform, or no precip.

    Per the brief:
      convective  -- precip occurred AND a convective PrecipFlag appeared nearby
      stratiform  -- precip occurred AND no convective flag AND no lightning
      none        -- no precip
    A period with precip, no convective flag, but lightning present is neither:
    it returns None so it is excluded rather than mislabelled as stratiform.
    """
    mrms_hours = list(mrms_hours)
    occurred = precip_observed(mrms_hours, threshold_in)
    if occurred is None:
        return UNKNOWN
    if not occurred:
        return NO_PRECIP
    if any(h.flag_convective_samples > 0 for h in mrms_hours):
        return CONVECTIVE
    thunder = thunder_observed(lightning_hours, radius_nm)
    if thunder is None:
        return UNKNOWN
    return STRATIFORM if not thunder else UNKNOWN


def hours_in_period(hours: Iterable, start_utc: dt.datetime, end_utc: dt.datetime) -> list:
    """Filter hourly records to [start, end). Hours are labelled by their start."""
    return [h for h in hours if start_utc <= h.hour_utc < end_utc]
