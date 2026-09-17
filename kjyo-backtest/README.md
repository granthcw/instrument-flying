# KJYO Forecast Backtest — v1

Measures how well a daily/hourly forecast predicts what actually happens at
**Leesburg Executive (KJYO)**: thunder vs. no thunder by day/night period and
lead time, convective vs. stratiform precipitation, precipitation-probability
calibration, and flight category.

---

## Read this first — two findings that change the plan

### 1. The ForeFlight connector path is closed. The forecast under test is the TWC API.

Phase 0 is complete and the gate decision is **fallback**. This is not "we could
not find a way in" — the ForeFlight AI Connector EULA prohibits the collection
pattern this project is built on:

> "You may not… systematically access, scrape, crawl, harvest, cache, store, or
> bulk-export ForeFlight Data" beyond individual, interactive use.

A 3-hourly collector writing raw responses to append-only storage is exactly
that. Separately, ForeFlight authorizes **ChatGPT only** (Claude support is
announced as intent, not availability), publishes no MCP server URL, and is not
in Claude's connector directory. Any of those three alone would block it.

**Recommendation: do not wait out the 7-day deadline.** The blocker is
contractual, not technical, so waiting only costs collection days in a season you
cannot re-collect. Full evidence in [`docs/access-notes.md`](docs/access-notes.md).

The schema keeps `source` on every forecast row (`twc_api` | `ff_connector`), so
if ForeFlight later ships Claude support *and* terms permitting scheduled
collection, that path drops in beside this one without a migration.

### 2. KJYO's AWOS reports thunder — but far too rarely to be truth.

The brief's first Phase 2 task, answered against the live archive. Across both
2024 and 2025 convective seasons (12,367 METARs):

| Measure | Count | Share |
|---|---:|---:|
| `TS` in body | 37 | 0.30% |
| `VCTS` in body | 41 | 0.33% |
| **Any TS/VCTS** | **78** | **0.63%** |
| `LTG` remark | 587 | 4.75% |

78 thunder observations over two seasons — about one per nine days of season —
split across lead days and dayparts would leave single-digit cells.
**GLM lightning is the thunder truth; METAR thunder is kept as a cross-check.**
Detail and the GLM validation in [`docs/thunder-reporting.md`](docs/thunder-reporting.md).

---

## Status against the brief's phases

| Phase | State |
|---|---|
| 0 — Access path and tool discovery | **Complete.** Findings recorded, gate decision made and evidenced. Awaiting Chris's approval. |
| 1 — Collector live | **Built and tested; blocked on one credential.** Schema, migrations, collector, parser, alerts and schedules are in place. Needs `TWC_API_KEY`. |
| 2 — Observations and baselines | **Built and validated end to end** on real data. Backfill is a manual matrix job; see the cost note below. |
| 3 — Scoring and report | **Complete.** 84 unit tests; `make report` renders from a clean clone with only `DATABASE_URL`. |
| 4 — Fidelity check | **Not started** — needs Chris and an iPad. Now *more* important than originally scoped; see below. |

## What Chris needs to do

1. **Approve the Phase 0 gate decision** (fallback to TWC).
2. **Sign up for the TWC API Hub** at <https://developer.weather.com> — account,
   terms and payment are human steps. Then set `TWC_API_KEY` and run
   `make collect-dry-run`. Every day without this is a collection day lost.
3. **Decide repository visibility** — see decision 4 in
   [`docs/decisions.md`](docs/decisions.md). This repo is public, and GitHub
   auto-disables scheduled workflows in public repos after 60 days of inactivity.
   A quiet winter is exactly how this loses its collector unnoticed.
4. **Run the fidelity check** (Phase 4). With the connector gone, this is what
   establishes whether the TWC API matches what ForeFlight actually shows — i.e.
   whether this backtest measures Chris's forecast or a different one. Nothing
   else in the project can answer it.

Remaining decisions are laid out with recommendations in
[`docs/decisions.md`](docs/decisions.md).

---

## Quick start

```bash
cd kjyo-backtest
make install                      # virtualenv + dependencies
cp .env.example .env              # fill in DATABASE_URL (and TWC_API_KEY when you have it)
set -a && . ./.env && set +a
make migrate                      # apply db/migrations/*.sql
make test                         # 84 unit tests, no network or database needed

make thunder-check                # the AWOS thunder census, no database needed
make ingest-day DATE=2025-07-27   # one UTC day of observations and baselines
make report                       # -> reports/kjyo_backtest.html
```

`make help` lists every target.

## Layout

```
config/config.yaml        sites, schedule, radii, thresholds, seasons, allowlists
db/migrations/            Postgres schema (12 tables), idempotent
src/kjyo_backtest/
  collect/                forecast collection: twc, runner, append-only storage
  ingest/                 metar, glm, mrms, mos, spc
  scoring/                metrics, observed labels, the scoring pipeline
  report/                 HTML renderer and inline SVG charts
  geo.py periods.py       distances; dayparts and lead times (DST-correct)
  db.py cli.py alerts.py
tests/                    84 tests against hand-computed answers
docs/                     access-notes, thunder-reporting, field-map,
                          fidelity-check, decisions
../.github/workflows/     kjyo-*.yml: daily obs, collect, backfill, tests, heartbeat
```

## Data sources — all verified reachable

| Purpose | Source | Verified |
|---|---|---|
| Ceiling, visibility, flight category, thunder cross-check | IEM ASOS/AWOS | ✅ KJYO + KIAD |
| Thunder truth | GOES GLM L2 LCFA on AWS | ✅ GOES-19 and GOES-16 |
| Convective vs. stratiform | MRMS `PrecipFlag` (2-min) | ✅ archive from 2020-10-14 |
| Precip amount | MRMS `MultiSensor_QPE_01H_Pass2` | ✅ RadarOnly fallback wired |
| NBM station guidance | IEM MOS archive | ✅ **KJYO is a station** (NBS) |
| SPC outlooks | SPC's own GeoJSON archive | ✅ IEM's endpoint has moved; SPC used instead |
| Forecast under test | TWC API | ⛔ needs a key |

### End-to-end validation

Ingested 2025-07-27 (five TS/VCTS METARs at KJYO) and cross-checked every layer:

| Hour | KJYO METAR | GLM ≤5nm | ≤10nm | ≤20nm | MRMS QPE | convective px |
|---|---|---:|---:|---:|---:|---:|
| 04Z | `+TSRA 1SM OVC008` `P0113` | 156 | 655 | 795 | 0.937 in | 251 |
| 16Z | `7SM RA` `LTG DSNT ALQDS` | 0 | 106 | 675 | 0.016 in | 0 |
| 20Z | `-VCTSRA` `P0020` | 55 | 316 | 528 | 0.177 in | 141 |
| 21Z | `CLR` `LTG DSNT SW` | 0 | 0 | 5 | 0.000 in | 0 |

Overhead convection, stratiform rain with distant lightning, a second convective
round, and distant-only flashes — each layer agrees with the others and with the
METARs. All 24 hours complete. A mid-winter control returned zero flashes at
every radius.

## Definitions

Configurable in `config/config.yaml`; the defaults match the brief.

- **Daypart** — day 07:00–19:00 local, night 19:00–07:00 local, America/New_York.
  Stored UTC, derived at query time. DST transitions produce genuine 11- and
  13-hour periods rather than being forced to 12 (tested).
- **Thunder observed** — ≥1 GLM flash within 10 nm during the period; 5 and 20 nm
  as sensitivity checks.
- **Precip occurred** — MRMS 1-hour QPE ≥ 0.01 in during at least one hour.
- **Convective** — precip occurred and a convective/hail/tropical-convective
  `PrecipFlag` appeared within 5 km. **Stratiform** — precip, no convective flag,
  no lightning within 10 nm.
- **Flight category** — FAA table, worse of ceiling and visibility. Boundary
  values take the *less* restrictive category (3 sm is MVFR; 1,000 ft is MVFR).

### Unknown is not the same as no

A period whose GLM hours were only partly ingested cannot be labelled "no
thunder" — absence of data is not absence of lightning. Those periods return
`None`, are dropped from scoring, and are counted in the report's completeness
section. The same applies to missing QPE and to precipitation that is neither
clearly convective nor clearly stratiform.

## Open questions, flagged rather than guessed

1. **Is TWC actually ForeFlight's source?** Widely assumed, not verified, and
   ForeFlight does not publish its vendor. The Phase 4 fidelity check settles it.
   Until then the report names the source as `twc_api` and claims nothing about
   ForeFlight.
2. **TWC v3 hourly carries no cloud ceiling.** Hourly flight-category scoring
   would be incomplete from TWC alone. The parser scans each response for a
   ceiling key and picks one up automatically if the authorized tier exposes it;
   otherwise scoring falls back to the NBM ceiling/visibility baseline, which is
   already ingested. Confirm the authorized endpoints at signup.
3. **Which IEM MOS column is the NBS thunder probability?** Not documented
   upstream, and observed values rule out the obvious reading — a run showing
   `t06_2 = 5.0` against `p06 = 3.0` is not a coherent thunder probability. All
   four candidate columns are stored verbatim and the scoring step selects one
   empirically against observed GLM thunder. See
   [`docs/field-map.md`](docs/field-map.md).
4. **TWC field names are unverified** without a key. The parser tolerates missing
   fields and records which ones actually arrived, so the first real pull reports
   the truth instead of throwing.
5. **Icon codes are not hard-coded anywhere.** The thunder signal comes from
   `thunderIndex` and, independently, from phrase text; every
   `(iconCode, phrase)` pair seen is recorded so the map is built from observed
   data. The two signals are scored separately.

## Operational notes

- **GLM backfill is the expensive job.** A site-day is 4,320 granules and takes
  ~4.25 minutes measured. A full May–September season is ~22 hours, so backfill
  is a manual, chunked matrix workflow rather than part of the daily run. All
  writers are idempotent upserts, so any date is safe to re-run.
- **MRMS decodes via the eccodes element API**, not xarray. MRMS is a 7000×3500
  CONUS grid; materialising 24.5 M points to read ~200 of them costs 11.5 s per
  file against 0.6 s batched — about 150 hours versus 8 over a season backfill.
- **Raw payloads are append-only.** Supabase Storage is written with
  `x-upsert: false`, so a repeated key is rejected by the server rather than
  silently overwritten. Enforced at the storage layer, not by convention.
- **Secrets never land in the repo.** `.env` is gitignored, and the API key is
  redacted from every URL before it is logged or stored (tested).
- **The heartbeat stays silent unless something is wrong** — failed or missing
  pulls, a changed response schema, failed ingest jobs, incomplete GLM hours, or
  no METARs in 24 h.
