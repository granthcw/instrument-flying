# Decisions needed from Chris

The brief lists three. The Phase 0 outcome changes what two of them mean, and
adds one.

## 1. Run the TWC collector in parallel from day 1, or only on gate failure?

**Moot — the gate failed, so TWC is the only forecast source.** There is nothing
to run in parallel with. The question becomes *when* the TWC key arrives; every
day without it is a collection day lost, and the convective season is the
scarce resource.

**Needed:** the API Hub signup (see `access-notes.md`).

## 2. Hosting: Supabase + GitHub Actions, or an alternative?

**Recommendation: Supabase Postgres + GitHub Actions, with one change to the brief.**

The brief proposes a Supabase Edge Function plus `pg_cron` for the collector.
With the connector path closed, the collector is a plain HTTPS call to TWC — no
MCP client, no OAuth refresh, no token in Vault. That removes the main reason to
put it in an Edge Function. Running it as a GitHub Actions cron alongside the
other jobs means one runtime, one language, one place to look when something
breaks.

Keep Supabase for Postgres and for append-only raw storage. Use `pg_cron` only if
you want a second, independent trigger as insurance against Actions being
disabled.

**Two things to confirm before committing** (the brief flags both):

- **Free-tier project pausing.** Supabase pauses free projects after inactivity,
  which would stop `pg_cron` and fail writes. Daily writes may be enough to keep
  it awake, but this is not worth guessing on a season you cannot re-collect.
  A paid tier removes the question.
- **Storage growth.** Two TWC endpoints every 3 h is 16 raw payloads a day.
  Gzipped they are small — on the order of tens of MB a year — so storage is not
  a constraint. The database is smaller still.

## 3. Alert channel: email, SMS, or push?

**Recommendation: email**, which is the only channel wired today
(`alerts.send_email`, SMTP via environment variables). The heartbeat stays silent
unless something is wrong, so volume is low and email is sufficient.

`config.yaml` has `alerts.channel`. Setting it to `sms` or `push` raises a clear
error rather than silently sending nothing — if you want one of those, say which
provider and it gets wired.

## 4. New — repository visibility

**This needs a decision, and the brief already anticipated the risk.**

The work is on branch `claude/kjyo-forecast-backtest-v1-by4z0l` in
`granthcw/instrument-flying`, which is a **public** repo (it serves the IFR study
site via GitHub Pages). The brief specifies a **private** repo for the batch jobs,
for a reason it states plainly: *scheduled workflows in public repos are
auto-disabled after 60 days of inactivity.* A quiet winter is exactly how this
project would lose its collector without noticing.

What is and is not affected:

- **No secrets or data are committed.** Only code, config and docs. The `.env` is
  gitignored and the API key is redacted before any URL is logged or stored.
- **The ForeFlight redistribution concern is moot** — no ForeFlight data is
  collected.
- **The 60-day auto-disable is live and real.** It is the deciding factor.

**Recommendation:** move the pipeline to a private repo before enabling the
schedules. Everything here is self-contained under `kjyo-backtest/` and copies
across as-is. If you would rather keep it here, the mitigation is a monthly
no-op commit or an external trigger, and that is a thing to remember forever
rather than a fix.
