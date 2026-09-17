"""Typed access to config/config.yaml."""

from __future__ import annotations

import datetime as dt
import functools
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "config" / "config.yaml"


@dataclass(frozen=True)
class Site:
    id: str
    name: str
    iem_id: str
    lat: float
    lon: float
    elev_ft: int
    tz: str
    role: str
    thunder_truth: bool


@dataclass(frozen=True)
class Config:
    raw: dict

    @property
    def sites(self) -> dict[str, Site]:
        return {
            s["id"]: Site(
                id=s["id"], name=s["name"], iem_id=s["iem_id"], lat=float(s["lat"]),
                lon=float(s["lon"]), elev_ft=int(s["elev_ft"]), tz=s["tz"],
                role=s["role"], thunder_truth=bool(s["thunder_truth"]),
            )
            for s in self.raw["sites"]
        }

    @property
    def focal_site(self) -> Site:
        for site in self.sites.values():
            if site.role == "focal":
                return site
        raise ValueError("no site with role: focal in config")

    def active_sites(self) -> list[Site]:
        """Sites collected in v1 -- everything but the schema-ready placeholders."""
        return [s for s in self.sites.values() if s.role in ("focal", "cross_check")]

    @property
    def radii_nm(self) -> tuple[float, ...]:
        return tuple(float(r) for r in self.raw["observed"]["lightning"]["radii_nm"])

    @property
    def primary_radius_nm(self) -> float:
        return float(self.raw["observed"]["lightning"]["primary_radius_nm"])

    @property
    def qpf_threshold_in(self) -> float:
        return float(self.raw["observed"]["precip"]["qpf_threshold_in"])

    @property
    def day_start_hour(self) -> int:
        return int(self.raw["periods"]["day_start_local"].split(":")[0])

    @property
    def night_start_hour(self) -> int:
        return int(self.raw["periods"]["night_start_local"].split(":")[0])

    def backfill_dates(self, today: dt.date | None = None) -> list[dt.date]:
        """Every date in the configured convective seasons, up to today."""
        today = today or dt.date.today()
        out: list[dt.date] = []
        for season in self.raw["backfill"]["seasons"]:
            year = int(season["year"])
            sm, sd = (int(x) for x in season["start"].split("-"))
            em, ed = (int(x) for x in season["end"].split("-"))
            day, last = dt.date(year, sm, sd), dt.date(year, em, ed)
            while day <= min(last, today):
                out.append(day)
                day += dt.timedelta(days=1)
        return out


@functools.lru_cache(maxsize=4)
def load(path: str | os.PathLike | None = None) -> Config:
    p = Path(path) if path else Path(os.environ.get("KJYO_CONFIG", DEFAULT_CONFIG))
    return Config(raw=yaml.safe_load(p.read_text()))
