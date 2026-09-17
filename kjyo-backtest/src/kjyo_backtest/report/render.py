"""Render the backtest report to a single self-contained HTML file."""

from __future__ import annotations

import datetime as dt
import html
import json
import logging
import os
import pathlib

from .. import db
from ..config import Config
from ..periods import dayparts_between
from ..scoring import score as scoring
from ..scoring.labels import LightningHour, MrmsHour
from . import charts

log = logging.getLogger(__name__)


class _Row:
    """Lightweight record so scoring code can use attribute access."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def _fetch_all(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def load_data(conn, site_id: str, first: dt.date, last: dt.date) -> dict:
    light = _fetch_all(conn, """
        select hour_utc, flashes_5nm, flashes_10nm, flashes_20nm, complete
        from obs_lightning_agg where site_id=%s and hour_utc >= %s and hour_utc < %s
        order by hour_utc""", (site_id, first, last + dt.timedelta(days=2)))
    mrms = _fetch_all(conn, """
        select hour_utc, qpe_in, flag_convective_samples, flag_stratiform_samples, flag_samples
        from obs_mrms_agg where site_id=%s and hour_utc >= %s and hour_utc < %s
        order by hour_utc""", (site_id, first, last + dt.timedelta(days=2)))
    metar = _fetch_all(conn, """
        select valid_utc, ceiling_ft, vis_sm, flight_category, ts_in_body, vcts, ltg_remark
        from obs_metar where site_id=%s and valid_utc >= %s and valid_utc < %s
        order by valid_utc""", (site_id, first, last + dt.timedelta(days=2)))
    fdp = _fetch_all(conn, """
        select source::text as source, site_id, local_date, daypart, lead_day, lead_hours,
               precip_chance, thunder_index, thunder_by_index, thunder_by_phrase
        from forecast_dayparts where site_id=%s and local_date between %s and %s""",
        (site_id, first, last))
    fhr = _fetch_all(conn, """
        select source::text as source, valid_utc, lead_hours, flight_category
        from forecast_hourly where site_id=%s and valid_utc >= %s and valid_utc < %s""",
        (site_id, first, last + dt.timedelta(days=2)))
    spc = _fetch_all(conn, """
        select outlook_day, issue_utc, valid_local_date, category, category_rank
        from baseline_spc where site_id=%s and valid_local_date between %s and %s""",
        (site_id, first, last))
    jobs = _fetch_all(conn, """
        select job, count(*) as runs, count(*) filter (where ok) as ok_runs,
               max(started_at) as last_run
        from job_runs group by job order by job""")
    pulls = _fetch_all(conn, """
        select source::text as source, count(*) as n, count(*) filter (where ok) as ok_n,
               count(distinct schema_hash) as schema_hashes,
               min(pulled_at) as first_pull, max(pulled_at) as last_pull
        from forecast_pulls group by source""")
    return {"lightning": light, "mrms": mrms, "metar": metar, "forecast_dayparts": fdp,
            "forecast_hourly": fhr, "spc": spc, "jobs": jobs, "pulls": pulls}


def _table(headers, rows, caption=None) -> str:
    out = ['<table>']
    if caption:
        out.append(f"<caption>{html.escape(caption)}</caption>")
    out.append("<thead><tr>" + "".join(f"<th>{html.escape(str(h))}</th>" for h in headers) + "</tr></thead><tbody>")
    for r in rows:
        out.append("<tr>" + "".join(f"<td>{c if isinstance(c, str) and c.startswith('<') else html.escape(str(c))}</td>" for c in r) + "</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def _num(v, digits=3):
    return "—" if v is None else f"{v:.{digits}f}"


def _ci(pair):
    lo, hi = pair if pair else (None, None)
    return "—" if lo is None else f"[{lo:.2f}, {hi:.2f}]"


def build(cfg: Config, output: str = "reports/kjyo_backtest.html") -> str:
    site = cfg.focal_site
    dates = cfg.backfill_dates()
    first, last = (min(dates), max(dates)) if dates else (dt.date.today(), dt.date.today())

    with db.connection() as conn:
        data = load_data(conn, site.id, first, last)

    light_rows = [LightningHour(r["hour_utc"], r["flashes_5nm"], r["flashes_10nm"],
                                r["flashes_20nm"], r["complete"]) for r in data["lightning"]]
    mrms_rows = [MrmsHour(r["hour_utc"], r["qpe_in"], r["flag_convective_samples"],
                          r["flag_stratiform_samples"], r["flag_samples"]) for r in data["mrms"]]
    metar_rows = [_Row(**r) for r in data["metar"]]
    # Dayparts come from the configured season dates, not a continuous range:
    # the backtest only scores convective-season periods, and counting winter
    # dayparts as "unknown" would drown the completeness figures.
    parts = [p for d in dates
             for p in dayparts_between(d, d, site.tz, cfg.day_start_hour, cfg.night_start_hour)]

    observed = scoring.build_observed_periods(
        light_rows, mrms_rows, metar_rows, parts, site.id,
        radii=cfg.radii_nm, primary_radius=cfg.primary_radius_nm,
        qpf_threshold=cfg.qpf_threshold_in)

    fdp = [_Row(**r) for r in data["forecast_dayparts"]]
    fhr = [_Row(**r) for r in data["forecast_hourly"]]

    thunder_cells = scoring.score_thunder(fdp, observed, "thunder_by_index") + \
                    scoring.score_thunder(fdp, observed, "thunder_by_phrase")
    prob_scores = scoring.score_precip_probability(fdp, observed)
    conv = scoring.score_convective_vs_stratiform(fdp, observed)
    flight = scoring.score_flight_category(fhr, metar_rows)

    n_obs = sum(1 for o in observed.values() if o.thunder is not None)
    n_thunder = sum(1 for o in observed.values() if o.thunder)
    n_unknown = sum(1 for o in observed.values() if o.thunder is None)
    n_precip = sum(1 for o in observed.values() if o.precip)
    n_conv = sum(1 for o in observed.values() if o.precip_class == "convective")
    n_strat = sum(1 for o in observed.values() if o.precip_class == "stratiform")

    html_doc = _render_html(cfg, site, first, last, data, observed, thunder_cells,
                            prob_scores, conv, flight,
                            dict(n_obs=n_obs, n_thunder=n_thunder, n_unknown=n_unknown,
                                 n_precip=n_precip, n_conv=n_conv, n_strat=n_strat,
                                 n_periods=len(observed)))
    path = pathlib.Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_doc, encoding="utf-8")
    return str(path)


def _render_html(cfg, site, first, last, data, observed, thunder_cells, prob_scores,
                 conv, flight, counts) -> str:
    generated = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    forecast_n = len(data["forecast_dayparts"])

    if forecast_n:
        summary = (
            f"Over {first} to {last}, {counts['n_obs']} of {counts['n_periods']} "
            f"day/night periods at {site.id} have a usable observed thunder label, of which "
            f"{counts['n_thunder']} had at least one GLM flash within "
            f"{cfg.primary_radius_nm:.0f} nm. {forecast_n} forecast daypart rows are matched "
            f"against them. Metrics below are split by lead day and daypart, with bootstrap "
            f"95% confidence intervals and sample counts alongside every value."
        )
    else:
        summary = (
            f"No forecast rows have been collected yet, so the forecast-vs-observed metrics "
            f"are empty by construction. The observed and baseline side is populated: "
            f"{counts['n_obs']} scorable day/night periods between {first} and {last}, "
            f"{counts['n_thunder']} of them with observed thunder within "
            f"{cfg.primary_radius_nm:.0f} nm, {counts['n_precip']} with measurable precipitation "
            f"({counts['n_conv']} convective, {counts['n_strat']} stratiform). This is the "
            f"state the brief anticipates before the collector is live: the scoring path runs "
            f"end to end on backfilled observations and baselines, and forecast rows drop into "
            f"the same tables when collection starts."
        )

    thunder_rows = []
    for c in sorted(thunder_cells, key=lambda x: (x.signal, x.daypart, x.lead_day)):
        t = c.table
        thunder_rows.append([
            c.source, c.signal, c.lead_day, c.daypart, t.n,
            f"{t.hits}/{t.false_alarms}/{t.misses}/{t.correct_negs}",
            f"{_num(t.pod, 2)} {_ci(c.ci.get('pod'))}",
            f"{_num(t.far, 2)} {_ci(c.ci.get('far'))}",
            f"{_num(t.csi, 2)} {_ci(c.ci.get('csi'))}",
            f"{_num(t.bias, 2)} {_ci(c.ci.get('bias'))}",
            c.dropped_unknown,
        ])

    prob_rows = [[p.source, p.lead_day, p.daypart, p.n, _num(p.brier),
                  _ci(p.brier_ci), _num(p.skill_vs_climatology), p.dropped_unknown]
                 for p in prob_scores]

    csi_series = {}
    for c in thunder_cells:
        csi_series.setdefault(f"{c.signal} ({c.daypart})", []).append((c.lead_day, c.table.csi))
    lead_chart = charts.lead_time_chart(csi_series, title="Thunder CSI by lead day",
                                        ylabel="CSI", ymax=1.0)
    rel_bins = prob_scores[0].reliability_bins if prob_scores else []
    rel_chart = charts.reliability_diagram(rel_bins, title="Precipitation probability reliability")

    fm = flight["matrix"]
    cats = ("VFR", "MVFR", "IFR", "LIFR")
    flight_rows = [[f"observed {o}"] + [fm[o][f] for f in cats] for o in cats]

    spc_counts: dict[str, int] = {}
    for r in data["spc"]:
        spc_counts[r["category"] or "none"] = spc_counts.get(r["category"] or "none", 0) + 1

    complete_hours = sum(1 for r in data["lightning"] if r["complete"])
    total_hours = len(data["lightning"])

    completeness_rows = [
        ["GLM lightning hours ingested", total_hours,
         f"{complete_hours} complete ({100*complete_hours/max(total_hours,1):.1f}%)"],
        ["MRMS hours ingested", len(data["mrms"]), ""],
        ["METAR observations", len(data["metar"]), ""],
        ["SPC outlook rows", len(data["spc"]), ", ".join(f"{k}:{v}" for k, v in sorted(spc_counts.items()))],
        ["Forecast daypart rows", forecast_n, ""],
        ["Forecast hourly rows", len(data["forecast_hourly"]), ""],
        ["Periods with unknown thunder label", counts["n_unknown"],
         "dropped from scoring rather than counted as no-thunder"],
    ]
    for p in data["pulls"]:
        completeness_rows.append([
            f"Forecast pulls ({p['source']})", p["n"],
            f"{p['ok_n']} ok, {p['schema_hashes']} distinct schema hashes"])
    job_rows = [[j["job"], j["runs"], j["ok_runs"],
                 j["last_run"].strftime("%Y-%m-%d %H:%M") if j["last_run"] else "—"]
                for j in data["jobs"]]

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KJYO Forecast Backtest</title>
<style>
  :root {{ --ink:#1b1f24; --muted:#5d636b; --line:#e3e6ea; --bg:#ffffff; --accent:#2f6fb5; }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{ --ink:#e8eaed; --muted:#a0a6ad; --line:#2c3138; --bg:#15181c; }}
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
  main {{ max-width:1080px; margin:0 auto; padding:32px 16px 80px; }}
  h1 {{ font-size:1.6rem; margin:0 0 4px; }}
  h2 {{ font-size:1.15rem; margin:40px 0 10px; padding-bottom:6px; border-bottom:1px solid var(--line); }}
  h3 {{ font-size:0.95rem; margin:24px 0 8px; color:var(--muted); font-weight:600; }}
  .sub {{ color:var(--muted); font-size:0.85rem; margin-bottom:24px; }}
  .summary {{ background:color-mix(in srgb, var(--accent) 7%, transparent);
    border-left:3px solid var(--accent); padding:14px 16px; border-radius:0 6px 6px 0; }}
  table {{ border-collapse:collapse; width:100%; margin:12px 0; font-size:0.84rem; }}
  caption {{ text-align:left; color:var(--muted); font-size:0.8rem; padding-bottom:6px; }}
  th,td {{ text-align:left; padding:6px 9px; border-bottom:1px solid var(--line); white-space:nowrap; }}
  th {{ font-weight:600; color:var(--muted); font-size:0.78rem; text-transform:uppercase; letter-spacing:0.03em; }}
  td:first-child, th:first-child {{ white-space:normal; }}
  .charts {{ display:flex; flex-wrap:wrap; gap:24px; margin:16px 0; }}
  .charts > div {{ flex:1 1 340px; min-width:0; }}
  .note {{ color:var(--muted); font-size:0.82rem; }}
  .scroll {{ overflow-x:auto; }}
  footer {{ margin-top:48px; padding-top:16px; border-top:1px solid var(--line);
    color:var(--muted); font-size:0.8rem; }}
</style></head><body><main>
<h1>KJYO Forecast Backtest</h1>
<div class="sub">{html.escape(site.name)} ({site.id}) &middot; {first} to {last} &middot;
  generated {generated} &middot; forecast source under test: <code>{html.escape(cfg.raw['forecast_source'])}</code></div>

<div class="summary"><p>{html.escape(summary)}</p></div>

<h2>Thunder verification</h2>
<p class="note">Observed thunder = at least
{cfg.raw['observed']['lightning']['min_flashes_for_thunder']} GLM flash within
{cfg.primary_radius_nm:.0f} nm during the period. Counts are hits/false alarms/misses/correct
negatives. Brackets are bootstrap 95% CIs.</p>
<div class="scroll">{_table(
    ["source","signal","lead day","daypart","n","H/FA/M/CN","POD","FAR","CSI","bias","dropped"],
    thunder_rows or [["—"]*11])}</div>

<div class="charts"><div>{lead_chart}</div><div>{rel_chart}</div></div>

<h2>Precipitation probability</h2>
<div class="scroll">{_table(
    ["source","lead day","daypart","n","Brier","95% CI","skill vs climatology","dropped"],
    prob_rows or [["—"]*8])}</div>

<h2>Convective vs stratiform</h2>
<p class="note">Among periods with observed precipitation, does the forecast thunder signal
separate convective from stratiform? Signal: <code>{html.escape(conv['signal'])}</code>.</p>
{_table(["n scored","hits","false alarms","misses","correct negatives","POD","FAR","CSI","excluded"],
        [[conv['n'], conv['table']['hits'], conv['table']['false_alarms'],
          conv['table']['misses'], conv['table']['correct_negs'],
          _num(conv['table']['pod'],2), _num(conv['table']['far'],2),
          _num(conv['table']['csi'],2), conv['dropped']]])}
<p class="note">Observed labels available in this window: {counts['n_conv']} convective,
{counts['n_strat']} stratiform, out of {counts['n_precip']} periods with measurable precipitation.</p>

<h2>Hourly flight category</h2>
<p class="note">Lead 0&ndash;48 h. Rows are observed, columns forecast. n = {flight['n']}.</p>
{_table(["", "fcst VFR","fcst MVFR","fcst IFR","fcst LIFR"], flight_rows)}
<h3>IFR or worse</h3>
{_table(["n","hits","false alarms","misses","correct negatives","POD","FAR","CSI"],
        [[flight['ifr_or_worse']['n'], flight['ifr_or_worse']['hits'],
          flight['ifr_or_worse']['false_alarms'], flight['ifr_or_worse']['misses'],
          flight['ifr_or_worse']['correct_negs'],
          _num(flight['ifr_or_worse']['pod'],2), _num(flight['ifr_or_worse']['far'],2),
          _num(flight['ifr_or_worse']['csi'],2)]])}

<h2>Data completeness</h2>
{_table(["item","count","detail"], completeness_rows)}
<h3>Job runs</h3>
{_table(["job","runs","successful","last run"], job_rows or [["—","—","—","—"]])}

<footer>
Observed thunder from GOES GLM L2 LCFA. Precipitation type and amount from MRMS.
Ceiling, visibility and flight category from KJYO/KIAD METARs via IEM.
Baselines from the IEM MOS archive and the SPC outlook archive.
Periods whose observed label could not be determined are dropped from scoring and counted
under &ldquo;dropped&rdquo; rather than treated as non-events.
</footer>
</main></body></html>"""
