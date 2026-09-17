"""Postgres access.

Every writer is an upsert on the table's natural key, so re-running any date
produces identical rows -- the brief's idempotency requirement. psycopg is
imported lazily so the pure-function tests run without a database.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
from contextlib import contextmanager

log = logging.getLogger(__name__)


def _connect():
    import psycopg
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env and fill it in."
        )
    return psycopg.connect(url, autocommit=False)


@contextmanager
def connection():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _j(value):
    """Serialize dict/list columns; pass everything else through."""
    return json.dumps(value) if isinstance(value, (dict, list)) else value


def executemany(conn, sql: str, rows: list[tuple]) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(sql, [tuple(_j(v) for v in r) for r in rows])
    return len(rows)


# ------------------------------------------------------------- sites -------

UPSERT_SITE = """
insert into sites (id, name, iem_id, lat, lon, elev_ft, tz, role, thunder_truth)
values (%s,%s,%s,%s,%s,%s,%s,%s,%s)
on conflict (id) do update set
  name=excluded.name, iem_id=excluded.iem_id, lat=excluded.lat, lon=excluded.lon,
  elev_ft=excluded.elev_ft, tz=excluded.tz, role=excluded.role,
  thunder_truth=excluded.thunder_truth
"""


def sync_sites(conn, sites) -> int:
    return executemany(conn, UPSERT_SITE, [
        (s.id, s.name, s.iem_id, s.lat, s.lon, s.elev_ft, s.tz, s.role, s.thunder_truth)
        for s in sites
    ])


# -------------------------------------------------------- observations -----

UPSERT_METAR = """
insert into obs_metar (site_id, valid_utc, ceiling_ft, vis_sm, flight_category,
  wxcodes, temp_f, dewpoint_f, wind_dir, wind_kt, p01i_in, ts_in_body, vcts,
  ltg_remark, raw_metar)
values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
on conflict (site_id, valid_utc) do update set
  ceiling_ft=excluded.ceiling_ft, vis_sm=excluded.vis_sm,
  flight_category=excluded.flight_category, wxcodes=excluded.wxcodes,
  temp_f=excluded.temp_f, dewpoint_f=excluded.dewpoint_f,
  wind_dir=excluded.wind_dir, wind_kt=excluded.wind_kt, p01i_in=excluded.p01i_in,
  ts_in_body=excluded.ts_in_body, vcts=excluded.vcts,
  ltg_remark=excluded.ltg_remark, raw_metar=excluded.raw_metar,
  ingested_at=now()
"""


def write_metar(conn, obs) -> int:
    return executemany(conn, UPSERT_METAR, [
        (o.site_id, o.valid_utc, o.ceiling_ft, o.vis_sm, o.flight_category,
         o.wxcodes, o.temp_f, o.dewpoint_f, o.wind_dir, o.wind_kt, o.p01i_in,
         o.ts_in_body, o.vcts, o.ltg_remark, o.raw_metar)
        for o in obs
    ])


UPSERT_LIGHTNING = """
insert into obs_lightning_agg (site_id, hour_utc, flashes_5nm, flashes_10nm,
  flashes_20nm, granules_expected, granules_read, granules_missing,
  granules_failed, complete, satellite)
values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
on conflict (site_id, hour_utc) do update set
  flashes_5nm=excluded.flashes_5nm, flashes_10nm=excluded.flashes_10nm,
  flashes_20nm=excluded.flashes_20nm,
  granules_expected=excluded.granules_expected,
  granules_read=excluded.granules_read, granules_missing=excluded.granules_missing,
  granules_failed=excluded.granules_failed, complete=excluded.complete,
  satellite=excluded.satellite, ingested_at=now()
"""


def write_lightning(conn, site_id: str, aggs, satellite: str) -> int:
    return executemany(conn, UPSERT_LIGHTNING, [
        (site_id, a.hour_utc, a.counts.get(5.0, 0), a.counts.get(10.0, 0),
         a.counts.get(20.0, 0), a.granules_expected, a.granules_read,
         a.granules_missing, a.granules_failed, a.complete, satellite)
        for a in aggs
    ])


UPSERT_MRMS = """
insert into obs_mrms_agg (site_id, hour_utc, qpe_in, qpe_product, flag_samples,
  flag_convective_samples, flag_stratiform_samples, flag_max_severity,
  flag_at_site_modal)
values (%s,%s,%s,%s,%s,%s,%s,%s,%s)
on conflict (site_id, hour_utc) do update set
  qpe_in=excluded.qpe_in, qpe_product=excluded.qpe_product,
  flag_samples=excluded.flag_samples,
  flag_convective_samples=excluded.flag_convective_samples,
  flag_stratiform_samples=excluded.flag_stratiform_samples,
  flag_max_severity=excluded.flag_max_severity,
  flag_at_site_modal=excluded.flag_at_site_modal, ingested_at=now()
"""

UPSERT_MOS = """
insert into baseline_mos (site_id, model, runtime_utc, ftime_utc, pop_06, pop_12,
  thunder_raw, ceiling_code, vis_code, temp_f, dewpoint_f, raw)
values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
on conflict (site_id, model, runtime_utc, ftime_utc) do update set
  pop_06=excluded.pop_06, pop_12=excluded.pop_12,
  thunder_raw=excluded.thunder_raw, ceiling_code=excluded.ceiling_code,
  vis_code=excluded.vis_code, temp_f=excluded.temp_f,
  dewpoint_f=excluded.dewpoint_f, raw=excluded.raw, ingested_at=now()
"""


def write_mos(conn, rows) -> int:
    return executemany(conn, UPSERT_MOS, [
        (r.site_id, r.model, r.runtime_utc, r.ftime_utc, r.pop_06, r.pop_12,
         r.thunder_raw, r.ceiling_code, r.vis_code, r.temp_f, r.dewpoint_f, r.raw)
        for r in rows
    ])


UPSERT_SPC = """
insert into baseline_spc (site_id, outlook_day, issue_utc, valid_local_date,
  category, category_rank, source_url)
values (%s,%s,%s,%s,%s,%s,%s)
on conflict (site_id, outlook_day, issue_utc) do update set
  valid_local_date=excluded.valid_local_date, category=excluded.category,
  category_rank=excluded.category_rank, source_url=excluded.source_url,
  ingested_at=now()
"""


def write_spc(conn, rows) -> int:
    return executemany(conn, UPSERT_SPC, [
        (r.site_id, r.day, r.issue_utc, r.valid_local_date, r.category,
         r.category_rank, r.url)
        for r in rows
    ])


# --------------------------------------------------------- bookkeeping -----

def start_job(conn, job: str, target_date: dt.date | None) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "insert into job_runs (job, target_date) values (%s,%s) returning id",
            (job, target_date),
        )
        return cur.fetchone()[0]


def finish_job(conn, job_id: str, ok: bool, rows: int = 0,
               detail: dict | None = None, error: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "update job_runs set finished_at=now(), ok=%s, rows_written=%s,"
            " detail=%s, error=%s where id=%s",
            (ok, rows, json.dumps(detail or {}), error, job_id),
        )
