"""Assemble matched forecast/observation pairs and score them.

The join is always: a forecast row targeting a (local_date, daypart) against the
observed label for that same period. Everything is grouped by lead_day, daypart
and source, because a metric averaged over lead times hides the only thing the
backtest is trying to measure.

Periods whose observed label is unknown are dropped, never coerced. The drop
count travels with the result so the report can show it.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections import defaultdict
from dataclasses import dataclass, field

from .labels import LightningHour, MrmsHour, precip_class, precip_observed, thunder_observed
from .metrics import (
    Contingency, brier_ci, brier_score, brier_skill_score, confusion_matrix,
    contingency, contingency_ci, reliability,
)

log = logging.getLogger(__name__)


@dataclass
class ObservedPeriod:
    site_id: str
    local_date: dt.date
    daypart: str
    start_utc: dt.datetime
    end_utc: dt.datetime
    thunder: bool | None
    thunder_by_radius: dict[float, bool | None] = field(default_factory=dict)
    precip: bool | None = None
    precip_class: str | None = None
    metar_thunder: bool | None = None

    @property
    def key(self) -> tuple:
        return (self.site_id, self.local_date, self.daypart)


def build_observed_periods(lightning_rows, mrms_rows, metar_rows, dayparts,
                           site_id: str, radii=(5.0, 10.0, 20.0),
                           primary_radius: float = 10.0,
                           qpf_threshold: float = 0.01) -> dict[tuple, ObservedPeriod]:
    """Derive one observed label set per daypart."""
    light_by_hour = {r.hour_utc: r for r in lightning_rows}
    mrms_by_hour = {r.hour_utc: r for r in mrms_rows}

    out: dict[tuple, ObservedPeriod] = {}
    for part in dayparts:
        hours = _hour_range(part.start_utc, part.end_utc)
        lh = [light_by_hour[h] for h in hours if h in light_by_hour]
        mh = [mrms_by_hour[h] for h in hours if h in mrms_by_hour]
        metars = [m for m in metar_rows if part.start_utc <= m.valid_utc < part.end_utc]

        by_radius = {r: thunder_observed(lh, r) for r in radii}
        obs = ObservedPeriod(
            site_id=site_id,
            local_date=part.local_date,
            daypart=part.kind,
            start_utc=part.start_utc,
            end_utc=part.end_utc,
            thunder=by_radius.get(primary_radius),
            thunder_by_radius=by_radius,
            precip=precip_observed(mh, qpf_threshold),
            precip_class=precip_class(mh, lh, qpf_threshold, primary_radius),
            metar_thunder=(any(m.ts_in_body or m.vcts for m in metars) if metars else None),
        )
        out[obs.key] = obs
    return out


def _hour_range(start: dt.datetime, end: dt.datetime) -> list[dt.datetime]:
    hours, cur = [], start.replace(minute=0, second=0, microsecond=0)
    while cur < end:
        hours.append(cur)
        cur += dt.timedelta(hours=1)
    return hours


@dataclass
class ScoreCell:
    """One scored group: a source x lead_day x daypart slice."""

    source: str
    signal: str
    lead_day: int
    daypart: str
    table: Contingency
    ci: dict[str, tuple[float | None, float | None]] = field(default_factory=dict)
    dropped_unknown: int = 0

    def as_dict(self) -> dict:
        d = self.table.as_dict()
        d.update(source=self.source, signal=self.signal, lead_day=self.lead_day,
                 daypart=self.daypart, dropped_unknown=self.dropped_unknown,
                 ci={k: list(v) for k, v in self.ci.items()})
        return d


def score_thunder(forecast_rows, observed: dict[tuple, ObservedPeriod],
                  signal: str = "thunder_by_index", n_boot: int = 1000,
                  with_ci: bool = True) -> list[ScoreCell]:
    """2x2 thunder verification, grouped by source, lead day and daypart."""
    groups: dict[tuple, list[tuple[bool, bool]]] = defaultdict(list)
    dropped: dict[tuple, int] = defaultdict(int)

    for row in forecast_rows:
        f = getattr(row, signal, None)
        obs = observed.get((row.site_id, row.local_date, row.daypart))
        g = (row.source, row.lead_day, row.daypart)
        if f is None or obs is None or obs.thunder is None:
            dropped[g] += 1
            continue
        groups[g].append((bool(f), bool(obs.thunder)))

    cells = []
    for (source, lead, part), pairs in sorted(groups.items()):
        fc = [f for f, _ in pairs]
        ob = [o for _, o in pairs]
        table = contingency(fc, ob)
        ci = {}
        if with_ci and table.n:
            for metric in ("pod", "far", "csi", "bias"):
                ci[metric] = contingency_ci(fc, ob, metric, n_boot=n_boot)
        cells.append(ScoreCell(source, signal, lead, part, table, ci,
                               dropped[(source, lead, part)]))
    return cells


@dataclass
class ProbScore:
    source: str
    lead_day: int
    daypart: str
    n: int
    brier: float | None
    brier_ci: tuple[float | None, float | None]
    skill_vs_climatology: float | None
    reliability_bins: list = field(default_factory=list)
    dropped_unknown: int = 0


def score_precip_probability(forecast_rows, observed, n_boot: int = 1000,
                             bins: int = 10) -> list[ProbScore]:
    """Brier score, skill and reliability for the precipitation probability."""
    groups: dict[tuple, list[tuple[float, bool]]] = defaultdict(list)
    dropped: dict[tuple, int] = defaultdict(int)

    for row in forecast_rows:
        p = row.precip_chance
        obs = observed.get((row.site_id, row.local_date, row.daypart))
        g = (row.source, row.lead_day, row.daypart)
        if p is None or obs is None or obs.precip is None:
            dropped[g] += 1
            continue
        groups[g].append((float(p), bool(obs.precip)))

    out = []
    for (source, lead, part), pairs in sorted(groups.items()):
        probs = [p for p, _ in pairs]
        obs_l = [o for _, o in pairs]
        out.append(ProbScore(
            source=source, lead_day=lead, daypart=part, n=len(pairs),
            brier=brier_score(probs, obs_l),
            brier_ci=brier_ci(probs, obs_l, n_boot=n_boot),
            skill_vs_climatology=brier_skill_score(probs, obs_l),
            reliability_bins=reliability(probs, obs_l, bins=bins),
            dropped_unknown=dropped[(source, lead, part)],
        ))
    return out


def score_convective_vs_stratiform(forecast_rows, observed,
                                   signal: str = "thunder_by_index") -> dict:
    """Among periods with observed precip, does the thunder signal separate
    convective from stratiform?"""
    fc, ob = [], []
    dropped = 0
    for row in forecast_rows:
        f = getattr(row, signal, None)
        obs = observed.get((row.site_id, row.local_date, row.daypart))
        if f is None or obs is None or obs.precip_class not in ("convective", "stratiform"):
            dropped += 1
            continue
        fc.append(bool(f))
        ob.append(obs.precip_class == "convective")
    table = contingency(fc, ob)
    return {"signal": signal, "table": table.as_dict(), "dropped": dropped,
            "n": table.n}


def score_flight_category(forecast_hours, observed_metars, max_lead_h: float = 48.0) -> dict:
    """Confusion matrix and IFR-or-worse hit rate for the hourly forecast."""
    obs_by_hour = {}
    for m in observed_metars:
        if m.flight_category:
            obs_by_hour.setdefault(m.valid_utc.replace(minute=0, second=0, microsecond=0),
                                   m.flight_category)
    fc, ob = [], []
    for h in forecast_hours:
        if h.lead_hours > max_lead_h or not h.flight_category:
            continue
        key = h.valid_utc.replace(minute=0, second=0, microsecond=0)
        if key in obs_by_hour:
            fc.append(h.flight_category)
            ob.append(obs_by_hour[key])
    matrix = confusion_matrix(fc, ob)
    ifr_f = [c in ("IFR", "LIFR") for c in fc]
    ifr_o = [c in ("IFR", "LIFR") for c in ob]
    return {"matrix": matrix, "n": len(fc),
            "ifr_or_worse": contingency(ifr_f, ifr_o).as_dict()}
