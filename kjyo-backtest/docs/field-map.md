# Field map — forecast fields to scoring needs

Two sources are mapped here: the TWC API (collected in v1) and the ForeFlight AI
Connector (not collected — see `access-notes.md`). Fields marked **unverified**
have not been confirmed against a live response; the parser tolerates their
absence and records which fields actually arrived on each pull.

## TWC API → scoring

### Daily, per daypart

| Scoring need | TWC field | Status | Notes |
|---|---|---|---|
| Thunder by index | `thunderIndex` | unverified | Signal is `>= 1`. Stored raw as well. |
| Thunder category | `thunderCategory` | unverified | Phrase form; stored, not used as the primary signal. |
| Thunder by phrase | derived from `wxPhraseLong` | **verified logic** | Regex on thunder/t-storm/strong storms. Excludes "Snow Storm". |
| Precip probability | `precipChance` | unverified | Percent. Scored for Brier/reliability. |
| Precip type | `precipType` | unverified | |
| QPF | `qpf` | unverified | inches (`units=e`) |
| Icon | `iconCode` | unverified | **Not hard-coded.** See below. |
| Cloud cover | `cloudCover` | unverified | |
| Temperature | `temperature` | unverified | |
| Day/night split | `dayOrNight` | unverified | `D`/`N`, alternating. |

**Daypart index 0 is null after ~3pm local.** The parser detects the null,
counts it in `n_null_dayparts`, and skips it. Target dates still advance every
two slots, so a nulled slot does not shift subsequent dates. Covered by
`test_parse_daily_skips_null_daypart` and `test_parse_daily_target_dates_advance`.

### Hourly

`iconCode`, `wxPhraseLong`, `precipChance`, `precipType`, `qpf`, `temperature`,
`temperatureDewPoint`, `windDirection`, `windSpeed`, `validTimeUtc`, `visibility`.

**No ceiling field.** TWC's consumer v3 hourly product does not carry cloud
ceiling. The parser scans each response for any key containing "ceiling" and
records what it finds in `diagnostics["ceiling_key"]`, so if the authorized tier
does expose one it is picked up automatically. Until then `forecast_hourly.ceiling_ft`
stays null and hourly flight-category scoring falls back to the NBM
ceiling/visibility baseline, which is already ingested.

## Icon codes are learned, not assumed

The brief is explicit: *"Confirm codes and phrases against docs or observed
values; don't hard-code from memory."* So no icon-code table is hard-coded
anywhere in this repo.

Instead:

1. The thunder signal is read from `thunderIndex` where present.
2. A second, independent signal is derived from the **phrase text**, which is
   self-describing and needs no lookup table.
3. Every `(iconCode, wxPhraseLong)` pair seen on a pull is recorded in the pull
   diagnostics. After a week of collection, that census *is* the icon map —
   built from observed data, and it goes in the table below.

| iconCode | Observed phrase | First seen | Thunder? |
|---|---|---|---|
| _(populated from collected data; empty until collection starts)_ | | | |

The two thunder signals are scored separately, as the brief requires, so a
disagreement between index and phrase shows up as two rows rather than being
silently reconciled.

## Baseline: IEM MOS → scoring

**Open item, flagged rather than guessed.** IEM exposes MOS thunder as
`t06_1`, `t06_2`, `t12_1`, `t12_2`. For the NBS (NBM station) model the mapping
from those columns to "thunderstorm probability" is not documented anywhere we
could verify, and IEM serves no raw-bulletin endpoint to check against.

Observed behaviour that rules out the obvious reading — a run from
2025-07-27 01Z at KIAD:

| ftime | `p06` | `t06_1` | `t06_2` |
|---|---:|---:|---:|
| 07-27 06:00 | — | 22.0 | — |
| 07-28 00:00 | 60.0 | — | 59.0 |
| 07-28 12:00 | 3.0 | — | 5.0 |

A thunderstorm probability of 5% against a 3% probability of precipitation is not
physically coherent, so `t06_2` is not simply "thunder probability".

**How this is handled:** `baseline_mos.thunder_raw` stores all four columns
verbatim as JSON, with no semantic claim. The scoring step picks the column
empirically, by correlating each candidate against the observed GLM thunder
label over the backfill, and the report prints which column was selected and how
well it did. If none of them behaves like a thunder probability, that is itself
a reportable result.

## ForeFlight AI Connector

Not mapped. The connector is not collected in v1 (`access-notes.md`). Published
descriptions list METARs, TAFs, MOS forecasts, winds aloft, ten-day forecasts and
Area Forecast Discussions across 19 tools, which suggests the fields needed for
scoring do exist — but the access and terms questions are settled before the
field question matters.
