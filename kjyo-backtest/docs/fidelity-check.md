# Phase 4 — Fidelity check

**Status: not started. Waiting on a TWC API key, then seven days of Chris's screenshots.**

## What changed, and why this now matters more

The brief designed this check to catch a ForeFlight connector serving cached or
reformatted data. The Phase 0 gate closed the connector path, so the check now
answers a more fundamental question:

> **Does the TWC API forecast match what ForeFlight actually shows for KJYO?**

If it does, the backtest measures something close to the forecast Chris flies
behind. If it does not, the backtest measures TWC, and every conclusion has to
be stated that way. Nothing else in the project can establish this — it needs a
human with the app open.

This is ordinary interactive use of ForeFlight and is unaffected by the
connector's automated-collection restrictions.

## Procedure

For seven consecutive days, within 15 minutes of a scheduled pull (pulls run at
:15 past 00/03/06/09/12/15/18/21 UTC):

1. Screenshot ForeFlight's **Daily** tab for KJYO.
2. Screenshot **one hourly detail** view for KJYO.
3. Note the local time of each screenshot to the minute.

Drop them in a folder named `YYYY-MM-DD/` and tell Claude Code the dates. The
comparison against the stored pull nearest each screenshot covers:

- icon and phrase
- precipitation chance
- temperatures
- ceiling and flight category
- thunder indication, where ForeFlight shows one

## Log

| Date | Local time | Pull compared | Icon/phrase | Precip % | Temps | Ceiling/category | Notes |
|---|---|---|---|---|---|---|---|
| _(empty until the check runs)_ | | | | | | | |

## Acceptance

Done when the match rate is written down here, per field.

**A systematic difference is a finding, not a failure** — but it must be flagged
before scoring relies on the data, and the report must name the forecast source
as what it actually is. A field that matches on fewer than, say, 6 of 7 days is
not a rounding artefact and needs explaining before it is scored.
