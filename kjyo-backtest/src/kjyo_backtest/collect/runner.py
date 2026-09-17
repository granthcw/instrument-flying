"""Scheduled forecast pull: fetch, store raw, parse, write rows, detect drift.

Raw payloads are append-only. Each pull writes a gzipped body to object storage
(or to a local directory when RAW_STORAGE_DIR is set) and a forecast_pulls row
pointing at it. Nothing rewrites or deletes a raw body.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import pathlib

from .. import db
from ..config import Config
from . import twc

log = logging.getLogger(__name__)

SOURCE_TWC = "twc_api"

INSERT_PULL = """
insert into forecast_pulls (source, site_id, pulled_at, tool_name, tool_args,
  request_url, ok, http_status, error, raw_object_key, raw_sha256, schema_hash,
  latency_ms)
values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
on conflict (source, site_id, pulled_at, tool_name) do update set
  ok=excluded.ok, error=excluded.error
returning id
"""

INSERT_DAYPART = """
insert into forecast_dayparts (pull_id, source, site_id, pulled_at, local_date,
  daypart, period_start_utc, period_end_utc, lead_hours, lead_day, icon_code,
  wx_phrase, precip_chance, precip_type, qpf_in, thunder_category, thunder_index,
  cloud_cover, temperature_f, thunder_by_index, thunder_by_phrase, raw)
values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
on conflict (source, site_id, pulled_at, local_date, daypart) do nothing
"""

INSERT_HOURLY = """
insert into forecast_hourly (pull_id, source, site_id, pulled_at, valid_utc,
  lead_hours, icon_code, wx_phrase, precip_chance, precip_type, qpf_in,
  temperature_f, dewpoint_f, wind_dir, wind_kt, ceiling_ft, visibility_sm,
  flight_category, thunder_index, raw)
values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
on conflict (source, site_id, pulled_at, valid_utc) do nothing
"""

UPSERT_SCHEMA = """
insert into connector_tool_schemas (source, observed_at, tool_name, schema_hash,
  schema_json)
values (%s,%s,%s,%s,%s)
on conflict (source, tool_name, schema_hash) do nothing
returning id
"""


def _store_raw(result: twc.PullResult, site_id: str) -> str | None:
    """Write the gzipped body and return its key. Append-only by construction."""
    blob = result.gzipped()
    if blob is None:
        return None
    key = (f"{SOURCE_TWC}/{site_id}/{result.pulled_at:%Y/%m/%d}/"
           f"{result.pulled_at:%Y%m%dT%H%M%SZ}_{result.endpoint.strip('/').replace('/', '-')}.json.gz")
    root = os.environ.get("RAW_STORAGE_DIR")
    if root:
        path = pathlib.Path(root) / key
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            log.warning("raw object already exists, not overwriting: %s", key)
            return key
        path.write_bytes(blob)
        return key
    # Supabase Storage path -- the bucket is configured write-once.
    from .storage import put_object
    return put_object(key, blob)


def run(cfg: Config, dry_run: bool = False) -> int:
    api_key = os.environ.get("TWC_API_KEY")
    if not api_key:
        log.error("TWC_API_KEY is not set -- see docs/access-notes.md for signup")
        return 2

    site = cfg.focal_site
    endpoints = [cfg.raw["twc"]["daily_endpoint"], cfg.raw["twc"]["hourly_endpoint"]]
    max_calls = int(cfg.raw["collection"]["max_tool_calls_per_pull"])
    endpoints = endpoints[:max_calls]

    results = []
    for endpoint in endpoints:
        r = twc.pull(endpoint, site.lat, site.lon, api_key,
                     units=cfg.raw["twc"]["units"],
                     language=cfg.raw["twc"]["language"],
                     timeout=int(cfg.raw["collection"]["request_timeout_s"]))
        log.info("pull %s ok=%s %sms", endpoint, r.ok, r.latency_ms)
        results.append(r)

    if dry_run:
        for r in results:
            print(json.dumps({"endpoint": r.endpoint, "ok": r.ok,
                              "bytes": len(r.body or b""), "error": r.error}))
        return 0 if all(r.ok for r in results) else 1

    failures = 0
    with db.connection() as conn:
        db.sync_sites(conn, list(cfg.sites.values()))
        for r in results:
            payload = {}
            schema_hash = None
            if r.ok and r.body:
                try:
                    payload = json.loads(r.body)
                    schema_hash = twc.response_schema_hash(payload)
                except json.JSONDecodeError as exc:
                    r = twc.PullResult(r.pulled_at, r.endpoint, r.url, False,
                                       error=f"invalid JSON: {exc}", body=r.body)

            key = _store_raw(r, site.id) if r.ok else None
            with conn.cursor() as cur:
                cur.execute(INSERT_PULL, (
                    SOURCE_TWC, site.id, r.pulled_at, r.endpoint,
                    json.dumps({"geocode": f"{site.lat},{site.lon}"}), r.url,
                    r.ok, r.status, r.error, key, r.sha256, schema_hash, r.latency_ms,
                ))
                pull_id = cur.fetchone()[0]

            if not r.ok:
                failures += 1
                continue

            if schema_hash:
                with conn.cursor() as cur:
                    cur.execute(UPSERT_SCHEMA, (
                        SOURCE_TWC, r.pulled_at, r.endpoint, schema_hash,
                        json.dumps({"endpoint": r.endpoint}),
                    ))
                    if cur.fetchone():
                        log.warning("NEW SCHEMA HASH for %s: %s", r.endpoint, schema_hash[:12])

            if "daily" in r.endpoint:
                rows, diag = twc.parse_daily(payload, r.pulled_at, site.tz,
                                             cfg.day_start_hour, cfg.night_start_hour)
                _write_dayparts(conn, pull_id, site.id, r.pulled_at, rows)
                log.info("daily: %d rows, missing fields %s", len(rows), diag["missing_fields"])
            else:
                rows, diag = twc.parse_hourly(payload, r.pulled_at)
                _write_hourly(conn, pull_id, site.id, r.pulled_at, rows)
                log.info("hourly: %d rows, ceiling key %s", len(rows), diag["ceiling_key"])

    return 1 if failures else 0


def _write_dayparts(conn, pull_id, site_id, pulled_at, rows) -> None:
    db.executemany(conn, INSERT_DAYPART, [
        (pull_id, SOURCE_TWC, site_id, pulled_at, r.local_date, r.daypart,
         r.period_start_utc, r.period_end_utc, r.lead_hours, r.lead_day,
         r.icon_code, r.wx_phrase, r.precip_chance, r.precip_type, r.qpf_in,
         r.thunder_category, r.thunder_index, r.cloud_cover, r.temperature_f,
         r.thunder_by_index, r.thunder_by_phrase, r.raw)
        for r in rows
    ])


def _write_hourly(conn, pull_id, site_id, pulled_at, rows) -> None:
    from ..ingest.metar import flight_category
    db.executemany(conn, INSERT_HOURLY, [
        (pull_id, SOURCE_TWC, site_id, pulled_at, r.valid_utc, r.lead_hours,
         r.icon_code, r.wx_phrase, r.precip_chance, r.precip_type, r.qpf_in,
         r.temperature_f, r.dewpoint_f, r.wind_dir, r.wind_kt, r.ceiling_ft,
         r.visibility_sm,
         flight_category(r.ceiling_ft, r.visibility_sm), None, r.raw)
        for r in rows
    ])
