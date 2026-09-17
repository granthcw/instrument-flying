"""Daily heartbeat.

Sends one message when something is wrong and stays silent otherwise, because
the failure mode that matters here is a collector that quietly stops. Checks:

  * scheduled pulls that failed or never happened in the last 24 h
  * a forecast schema hash that changed
  * ingest jobs that failed
  * observation gaps (GLM hours never ingested, missing METAR days)

Channel is configurable; email via SMTP is implemented, and the others raise a
clear error rather than pretending to send.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import smtplib
from email.message import EmailMessage

from . import db
from .config import Config

log = logging.getLogger(__name__)

CHECKS_SQL = {
    "failed_pulls_24h": """
        select count(*) from forecast_pulls
        where pulled_at > now() - interval '24 hours' and not ok
    """,
    "successful_pulls_24h": """
        select count(*) from forecast_pulls
        where pulled_at > now() - interval '24 hours' and ok
    """,
    "schema_hashes_24h": """
        select count(distinct schema_hash) from forecast_pulls
        where pulled_at > now() - interval '24 hours' and schema_hash is not null
    """,
    "failed_jobs_24h": """
        select count(*) from job_runs
        where started_at > now() - interval '24 hours' and ok is false
    """,
    "incomplete_glm_hours_48h": """
        select count(*) from obs_lightning_agg
        where hour_utc > now() - interval '48 hours' and not complete
    """,
    "metar_rows_24h": """
        select count(*) from obs_metar where valid_utc > now() - interval '24 hours'
    """,
}


def collect_status(conn) -> dict:
    out: dict[str, int] = {}
    with conn.cursor() as cur:
        for name, sql in CHECKS_SQL.items():
            cur.execute(sql)
            out[name] = int(cur.fetchone()[0])
    return out


def evaluate(status: dict, expected_pulls_per_day: int) -> list[str]:
    """Return a list of problems. An empty list means stay silent."""
    problems = []
    got = status["successful_pulls_24h"]
    if got < expected_pulls_per_day:
        problems.append(
            f"only {got}/{expected_pulls_per_day} scheduled forecast pulls succeeded "
            "in the last 24 h"
        )
    if status["failed_pulls_24h"]:
        problems.append(f"{status['failed_pulls_24h']} forecast pulls failed")
    if status["schema_hashes_24h"] > 1:
        problems.append(
            f"forecast response schema changed: {status['schema_hashes_24h']} distinct "
            "hashes in 24 h -- check the parser before trusting new rows"
        )
    if status["failed_jobs_24h"]:
        problems.append(f"{status['failed_jobs_24h']} ingest jobs failed")
    if status["incomplete_glm_hours_48h"]:
        problems.append(
            f"{status['incomplete_glm_hours_48h']} GLM hours are incomplete "
            "(those hours cannot be scored as 'no thunder')"
        )
    if status["metar_rows_24h"] == 0:
        problems.append("no METAR rows ingested in 24 h")
    return problems


def send_email(subject: str, body: str) -> None:
    host = os.environ.get("SMTP_HOST")
    to = os.environ.get("ALERT_EMAIL_TO")
    if not host or not to:
        raise RuntimeError("SMTP_HOST and ALERT_EMAIL_TO must be set for email alerts")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ.get("ALERT_EMAIL_FROM", to)
    msg["To"] = to
    msg.set_content(body)
    port = int(os.environ.get("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=30) as s:
        s.starttls()
        if os.environ.get("SMTP_USER"):
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        s.send_message(msg)


def heartbeat(cfg: Config, dry_run: bool = False) -> int:
    cron = cfg.raw["collection"]["schedule_cron"]
    expected = len(cron.split()[1].split(","))
    with db.connection() as conn:
        status = collect_status(conn)
    problems = evaluate(status, expected)

    payload = {"status": status, "problems": problems,
               "checked_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    print(json.dumps(payload, indent=2))

    if not problems:
        log.info("heartbeat clean; staying silent")
        return 0
    if dry_run:
        return 1

    channel = cfg.raw["alerts"]["channel"]
    subject = f"[KJYO backtest] {len(problems)} problem(s)"
    body = "\n".join(f"- {p}" for p in problems) + "\n\n" + json.dumps(status, indent=2)
    if channel == "email":
        send_email(subject, body)
    else:
        raise NotImplementedError(
            f"alert channel {channel!r} is configured but not implemented; "
            "email is the only wired channel (see decision 3 in the README)"
        )
    return 1
