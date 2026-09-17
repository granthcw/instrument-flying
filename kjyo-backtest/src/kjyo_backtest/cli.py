"""Command-line entrypoints for every collect, ingest and report job.

Usage:  python -m kjyo_backtest.cli <command> [options]
`make help` lists the same commands with their scheduling.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sys

from . import db
from .config import load
from .ingest import glm as glm_ingest
from .ingest import metar as metar_ingest
from .ingest import mos as mos_ingest
from .ingest import mrms as mrms_ingest
from .ingest import spc as spc_ingest

log = logging.getLogger("kjyo")


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def _yesterday_utc() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)


def _sites(cfg, only: str | None):
    sites = cfg.active_sites()
    return [s for s in sites if s.id == only] if only else sites


# --------------------------------------------------------------- METAR -----

def cmd_ingest_metar(args) -> int:
    cfg = load()
    day = args.date or _yesterday_utc()
    total = 0
    with db.connection() as conn:
        db.sync_sites(conn, list(cfg.sites.values()))
        for site in _sites(cfg, args.site):
            job = db.start_job(conn, "ingest_metar", day)
            try:
                obs = metar_ingest.fetch_range(
                    site.iem_id, site.id, day, day + dt.timedelta(days=1))
                n = db.write_metar(conn, obs)
                db.finish_job(conn, job, True, n)
                total += n
                log.info("metar %s %s -> %d rows", site.id, day, n)
            except Exception as exc:
                db.finish_job(conn, job, False, 0, error=str(exc))
                raise
    print(json.dumps({"job": "ingest_metar", "date": str(day), "rows": total}))
    return 0


# ----------------------------------------------------------------- GLM -----

def cmd_ingest_glm(args) -> int:
    cfg = load()
    day = args.date or _yesterday_utc()
    total = 0
    with db.connection() as conn:
        db.sync_sites(conn, list(cfg.sites.values()))
        for site in _sites(cfg, args.site):
            job = db.start_job(conn, "ingest_glm", day)
            try:
                aggs = glm_ingest.aggregate_day(
                    day, site.lat, site.lon, cfg.radii_nm, workers=args.workers)
                n = db.write_lightning(conn, site.id, aggs, glm_ingest.bucket_for(day))
                incomplete = sum(1 for a in aggs if not a.complete)
                db.finish_job(conn, job, True, n, {"incomplete_hours": incomplete})
                total += n
                log.info("glm %s %s -> %d hours (%d incomplete)", site.id, day, n, incomplete)
            except Exception as exc:
                db.finish_job(conn, job, False, 0, error=str(exc))
                raise
    print(json.dumps({"job": "ingest_glm", "date": str(day), "rows": total}))
    return 0


# ---------------------------------------------------------------- MRMS -----

def cmd_ingest_mrms(args) -> int:
    cfg = load()
    day = args.date or _yesterday_utc()
    step = int(cfg.raw["observed"]["precip"]["flag_sample_minutes"])
    radius_km = float(cfg.raw["observed"]["precip"]["flag_radius_km"])
    total = 0
    with db.connection() as conn:
        db.sync_sites(conn, list(cfg.sites.values()))
        for site in _sites(cfg, args.site):
            job = db.start_job(conn, "ingest_mrms", day)
            try:
                rows = []
                for hour in range(24):
                    base = dt.datetime(day.year, day.month, day.day, hour,
                                       tzinfo=dt.timezone.utc)
                    conv = strat = samples = 0
                    worst = None
                    site_flags: list[int] = []
                    for minute in range(0, 60, step):
                        s = mrms_ingest.sample_precip_flag(
                            base + dt.timedelta(minutes=minute),
                            site.lat, site.lon, radius_km)
                        if s is None:
                            continue
                        samples += 1
                        if s.flag_at_site is not None:
                            site_flags.append(s.flag_at_site)
                        for flag, count in s.nearby_flags.items():
                            if flag in mrms_ingest.CONVECTIVE_FLAGS:
                                conv += count
                            elif flag in mrms_ingest.STRATIFORM_FLAGS:
                                strat += count
                        w = s.flag_max_severity_nearby
                        if w is not None and (
                            worst is None
                            or mrms_ingest.FLAG_SEVERITY.get(w, 0)
                            > mrms_ingest.FLAG_SEVERITY.get(worst, 0)
                        ):
                            worst = w
                    qpe = mrms_ingest.sample_qpe_hour(
                        base + dt.timedelta(hours=1), site.lat, site.lon)
                    modal = max(set(site_flags), key=site_flags.count) if site_flags else None
                    rows.append((site.id, base,
                                 qpe.qpe_in if qpe else None,
                                 qpe.product if qpe else None,
                                 samples, conv, strat, worst, modal))
                n = db.executemany(conn, db.UPSERT_MRMS, rows)
                db.finish_job(conn, job, True, n)
                total += n
                log.info("mrms %s %s -> %d hours", site.id, day, n)
            except Exception as exc:
                db.finish_job(conn, job, False, 0, error=str(exc))
                raise
    print(json.dumps({"job": "ingest_mrms", "date": str(day), "rows": total}))
    return 0


# ------------------------------------------------------------ baselines ----

def cmd_ingest_mos(args) -> int:
    cfg = load()
    day = args.date or _yesterday_utc()
    cycles = tuple(cfg.raw["sources"]["mos"]["archived_cycles_utc"])
    models = list(cfg.raw["sources"]["mos"]["models"])
    total = 0
    with db.connection() as conn:
        db.sync_sites(conn, list(cfg.sites.values()))
        for site in _sites(cfg, args.site):
            job = db.start_job(conn, "ingest_mos", day)
            try:
                n = 0
                for model in models:
                    n += db.write_mos(conn, mos_ingest.fetch_day(site.id, model, day, cycles))
                db.finish_job(conn, job, True, n)
                total += n
                log.info("mos %s %s -> %d rows", site.id, day, n)
            except Exception as exc:
                db.finish_job(conn, job, False, 0, error=str(exc))
                raise
    print(json.dumps({"job": "ingest_mos", "date": str(day), "rows": total}))
    return 0


def cmd_ingest_spc(args) -> int:
    cfg = load()
    day = args.date or _yesterday_utc()
    total = 0
    with db.connection() as conn:
        db.sync_sites(conn, list(cfg.sites.values()))
        for site in _sites(cfg, args.site):
            job = db.start_job(conn, "ingest_spc", day)
            try:
                n = db.write_spc(conn, spc_ingest.fetch_day(site.id, site.lat, site.lon, day))
                db.finish_job(conn, job, True, n)
                total += n
                log.info("spc %s %s -> %d rows", site.id, day, n)
            except Exception as exc:
                db.finish_job(conn, job, False, 0, error=str(exc))
                raise
    print(json.dumps({"job": "ingest_spc", "date": str(day), "rows": total}))
    return 0


# ---------------------------------------------------- thunder reporting ----

def cmd_thunder_check(args) -> int:
    """Count TS/VCTS/LTG in a site's METAR archive.

    The brief's first Phase 2 task: establish whether KJYO's AWOS reports
    thunder often enough to serve as truth. Runs without a database.
    """
    cfg = load()
    site = cfg.sites[args.site or cfg.focal_site.id]
    start = args.start or dt.date(dt.date.today().year - 2, 5, 1)
    end = args.end or dt.date.today()
    obs = metar_ingest.fetch_range(site.iem_id, site.id, start, end)
    ts = sum(1 for o in obs if o.ts_in_body)
    vcts = sum(1 for o in obs if o.vcts)
    ltg = sum(1 for o in obs if o.ltg_remark)
    out = {
        "site": site.id, "start": str(start), "end": str(end),
        "metars": len(obs), "ts_in_body": ts, "vcts": vcts,
        "any_thunder": sum(1 for o in obs if o.ts_in_body or o.vcts),
        "ltg_remark": ltg,
        "pct_any_thunder": round(100 * sum(1 for o in obs if o.ts_in_body or o.vcts)
                                 / max(len(obs), 1), 3),
    }
    print(json.dumps(out, indent=2))
    return 0


# ------------------------------------------------------------- forecasts ---

def cmd_collect_forecast(args) -> int:
    """Pull the forecast under test and store raw + parsed rows."""
    from .collect import runner
    return runner.run(load(), dry_run=args.dry_run)


def cmd_report(args) -> int:
    from .report import render
    out = render.build(load(), output=args.output)
    print(f"wrote {out}")
    return 0


def cmd_heartbeat(args) -> int:
    from . import alerts
    return alerts.heartbeat(load(), dry_run=args.dry_run)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kjyo-backtest", description=__doc__)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    def add(name, fn, help_text, dated=True, site=True):
        sp = sub.add_parser(name, help=help_text)
        sp.set_defaults(func=fn)
        if dated:
            sp.add_argument("--date", type=_date, help="UTC date (default: yesterday)")
        if site:
            sp.add_argument("--site", help="limit to one site id")
        return sp

    add("ingest-metar", cmd_ingest_metar, "METAR observations from IEM")
    g = add("ingest-glm", cmd_ingest_glm, "GLM lightning flash counts")
    g.add_argument("--workers", type=int, default=16)
    add("ingest-mrms", cmd_ingest_mrms, "MRMS precip flag and QPE")
    add("ingest-mos", cmd_ingest_mos, "NBM/GFS MOS baseline")
    add("ingest-spc", cmd_ingest_spc, "SPC convective outlook baseline")

    tc = add("thunder-check", cmd_thunder_check, "census TS/VCTS in a METAR archive", dated=False)
    tc.add_argument("--start", type=_date)
    tc.add_argument("--end", type=_date)

    cf = add("collect-forecast", cmd_collect_forecast, "pull the forecast under test",
             dated=False, site=False)
    cf.add_argument("--dry-run", action="store_true")

    rp = add("report", cmd_report, "render the HTML report", dated=False, site=False)
    rp.add_argument("--output", default="reports/kjyo_backtest.html")

    hb = add("heartbeat", cmd_heartbeat, "daily health check and alert",
             dated=False, site=False)
    hb.add_argument("--dry-run", action="store_true")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
