# Phase 0 — Access path findings and gate decision

**Investigated:** 2026-09-17 · **Investigator:** Claude Code
**Gate outcome: fallback triggered. The forecast source under test in v1 is the TWC API, not the ForeFlight AI Connector.**

This is not a "we could not find a way in" finding. The ForeFlight AI Connector
EULA prohibits the collection pattern this project is built on, and ForeFlight
authorizes only one client. Both facts are independently disqualifying.

---

## 1. Is ForeFlight listed in Claude's connector directory?

**No.** A live query of the connector directory for this account returned no
ForeFlight entry. Searching the MCP registry for aviation-weather terms surfaced
Vaisala Xweather, AccuWeather and Airfield Directory — no ForeFlight.

Connectors currently installed on the account: Calendly, Gmail, Google Calendar,
Google Drive, PostHog, Stripe, Supabase, Vercel.

## 2. Do ForeFlight's own publications announce Claude support?

**Not yet — it is stated as intent, not availability.** ForeFlight's materials
describe the AI Connector as a remote MCP server of 19 tools, available to
individual Starter / Essential / Premium subscribers as a research/open preview,
and reached through **ChatGPT only**. ForeFlight says it "intends to expand this
feature to other popular AI applications such as Google's Gemini and Anthropic's
Claude." Intent is not an access path.

## 3. Does ForeFlight publish the MCP server URL?

**No.** No server URL appears in the blog post, the enhancements page, or the
EULA. Connection is established through the ChatGPT app directory, and there is
no documented dynamic client registration or ForeFlight-issued client for
third-party MCP clients.

## 4. The decisive finding — the EULA forbids the collection pattern

The AI Connector terms state that you may not:

> "…systematically access, scrape, crawl, harvest, cache, store, or bulk-export
> ForeFlight Data" beyond individual, interactive use.

A collector that pulls every 3 hours on a schedule and writes raw responses to
append-only storage is, precisely, systematic automated access that caches and
stores ForeFlight Data. That is the design this project needs. The same terms
also prohibit using the data to train or improve any model, restrict
redistribution, and exclude navigation, dispatch and safety-of-flight use.

The brief's own guardrails settle this: *"Use only access paths ForeFlight
offers"* and *"Agents don't accept terms of service."* Even if a technical path
to a non-ChatGPT MCP client opened tomorrow, the automated-collection clause
would still bar the v1 design.

### Gate evaluation against the brief's three options

| Path | Status | Why |
|---|---|---|
| 1. Direct MCP client | **Unavailable** | No published server URL; no documented OAuth path accepting a non-ChatGPT client. Reaching it anyway would require impersonating the ChatGPT client or probing private endpoints — both explicitly forbidden by the brief. |
| 2. Claude connector | **Unavailable** | ForeFlight does not support Claude today. Announced as intent only. |
| 3. TWC API fallback | **Selected** | Starts the season now rather than losing it. |

**Recommendation: do not wait out the 7-day deadline.** The deadline exists to
cap time spent looking for a path. There is no path to find, and the blocker is
contractual rather than technical, so waiting only costs collection days.

---

## What this changes, and what it does not

**Changed — the forecast under test.** v1 scores the TWC API forecast. The
`source` column already separates `twc_api` from `ff_connector` rows, so if
ForeFlight later ships a Claude connector *and* terms that permit scheduled
collection, that path drops in beside the existing one without a migration or a
break in the schedule.

**Changed — what the fidelity check means (Phase 4).** Chris comparing
ForeFlight screenshots against stored data is still worth doing, and remains
permitted: reading your own forecast in the app is ordinary interactive use. But
it now answers a different question — *how close is the TWC API to what
ForeFlight shows?* — rather than validating a connector feed. If the two diverge
systematically, the backtest measures TWC, not ForeFlight, and the report must
say so.

**Unchanged — everything observational.** METAR, GLM, MRMS, NBM/MOS and SPC are
public data and were never gated on this decision. That work proceeded and is
the bulk of what is now built.

---

## Open item: is TWC actually ForeFlight's source?

ForeFlight's non-aviation daily/hourly forecast is widely understood to come
from The Weather Company, which is why the brief nominates TWC as the fallback.
**We have not verified this**, and ForeFlight does not publish its vendor. If
they differ, the backtest measures TWC's forecast rather than ForeFlight's.

The Phase 4 fidelity check is what settles it, and it is now the single most
valuable thing Chris can do for the project's validity. Until it runs, every
report states the forecast source as `twc_api` and claims nothing about
ForeFlight.

## Next human step — TWC API Hub signup

The collector is built and tested; it needs one credential.

1. Go to <https://developer.weather.com> and start an API Hub trial.
2. **Chris does this personally** — account creation, terms acceptance and any
   payment details. Agents do not accept terms or enter payment.
3. Record in this file: the authorized endpoints, the longest authorized daily
   `{N}day` and hourly `{2day|15day}` variants, call limits, and trial length.
4. Put the key in `TWC_API_KEY` (GitHub Actions secret and/or Supabase Vault).
   Never commit it.
5. Run `make collect-dry-run` to confirm the pull works, then enable the schedule.

Known limitation to check at signup: TWC's consumer v3 hourly product carries no
cloud-ceiling field. If the trial tier has no aviation endpoint, hourly
flight-category scoring falls back to the NBM ceiling/visibility baseline, which
is already ingested. See the README's open-questions section.
