# Does KJYO's AWOS report thunder?

**Answer: yes, but far too rarely to serve as truth. Use GLM.**

This is the brief's first Phase 2 task, run against the live IEM ASOS archive.

## Method

All KJYO (`JYO`) routine METARs from the IEM ASOS/AWOS download service across
both convective seasons, 2024-05-01 to 2025-10-01. Thunder was counted three
ways, matching on the METAR **body only** (the `RMK` section is split off first
so that remark-only lightning is counted separately):

- `TS` as a present-weather group, with optional intensity and precipitation
  type (`TS`, `+TSRA`, `-TSRA`, …)
- `VCTS` — thunderstorm in the vicinity
- `LTG` anywhere in the report, which at an AO2 site is the automated lightning
  remark (`LTG DSNT NW`, `LTG DSNT ALQDS`)

Reproduce with `make thunder-check`.

## Result

| Measure | Count | Share of all METARs |
|---|---:|---:|
| Routine METARs in window | 12,367 | — |
| `TS` in body | 37 | 0.30% |
| `VCTS` in body | 41 | 0.33% |
| **Any TS or VCTS** | **78** | **0.63%** |
| `LTG` remark present | 587 | 4.75% |

## What this means

KJYO's AWOS does report thunder — it is not silent, as the brief allowed it might
be. But it reports it **7.5 times less often than it reports a lightning remark**.
Over two full convective seasons there are only 78 thunder observations, roughly
one per nine days of season. Building a 2×2 verification table on 78 events split
across lead days and dayparts would leave cells with single-digit counts.

The `LTG` remarks are more plentiful, but they are not a substitute: `LTG DSNT`
means lightning *more than 10 statute miles away*, which is a different event
from thunder at the field, and the remark carries a direction rather than a
distance.

## Decision

- **GLM is the thunder truth at KJYO.** `sites.thunder_truth` is `false` for
  KJYO in `config/config.yaml`.
- **METAR thunder is kept as a cross-check, not as truth.** `obs_metar` stores
  `ts_in_body`, `vcts` and `ltg_remark` separately, and the scoring code carries
  `metar_thunder` alongside the GLM label so agreement between them can be
  reported.
- **KIAD is the METAR cross-check station** (9.3 nm from KJYO, computed
  great-circle). It is a full ASOS with a human-augmented history and
  `thunder_truth: true`.

## Independent validation of the GLM label

GLM was checked against KJYO's own METARs on 2025-07-27, a day with five
TS/VCTS reports:

| Time | KJYO METAR | GLM flashes ≤5 nm | ≤10 nm | ≤20 nm |
|---|---|---:|---:|---:|
| 03:55Z | `TS` … `RMK LTG DSNT NW THRU NE` | 31 | 224 | 470 |
| 04:35Z | `+TSRA 1SM OVC008` … `P0113` | 156 | 655 | 795 |
| 21:55Z | `CLR` … `RMK LTG DSNT SW` | 0 | 0 | 5 |

The overhead thunderstorm hour shows heavy flash counts inside 5 nm. The hour
whose only thunder evidence is a *distant* lightning remark shows flashes at
20 nm and **none inside 10 nm** — exactly what "DSNT" means. A mid-winter control
(2025-01-15) returned zero flashes at every radius.

That is the label behaving correctly at both ends, and it is why the primary
radius is 10 nm with 5 nm and 20 nm carried as sensitivity checks.
