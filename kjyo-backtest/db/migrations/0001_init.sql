-- KJYO forecast backtest -- initial schema.
--
-- Conventions:
--   * every timestamp is timestamptz, stored UTC; local dayparts are derived
--     at query time from sites.tz
--   * every forecast row carries `source` so ff_connector and twc_api rows can
--     coexist and be scored separately
--   * every ingest table has a natural unique key so re-running a date is a
--     no-op upsert -- the brief's idempotency requirement

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------- sites ----

create table if not exists sites (
    id            text primary key,              -- ICAO, e.g. KJYO
    name          text not null,
    iem_id        text not null,                 -- 3-letter IEM/ASOS id
    lat           double precision not null,
    lon           double precision not null,
    elev_ft       integer not null,
    tz            text not null default 'America/New_York',
    role          text not null default 'future' -- focal | cross_check | future
                  check (role in ('focal','cross_check','future')),
    thunder_truth boolean not null default true, -- does its METAR report TS usefully?
    created_at    timestamptz not null default now()
);

comment on column sites.thunder_truth is
    'False for AWOS sites whose TS reporting is too sparse to serve as truth (KJYO).';

-- ------------------------------------------------------- forecast pulls ----

-- Source of a forecast row. ff_connector is retained although v1 collects
-- twc_api only: see docs/access-notes.md for the gate decision.
do $$ begin
    create type forecast_source as enum ('ff_connector', 'twc_api');
exception when duplicate_object then null;
end $$;

create table if not exists forecast_pulls (
    id             uuid primary key default gen_random_uuid(),
    source         forecast_source not null,
    site_id        text not null references sites(id),
    pulled_at      timestamptz not null,
    tool_name      text,                          -- connector tool, or TWC endpoint
    tool_args      jsonb,
    request_url    text,
    ok             boolean not null,
    http_status    integer,
    error          text,
    -- Pointer into Supabase Storage for the gzipped raw payload. Raw bodies are
    -- append-only and never rewritten.
    raw_object_key text,
    raw_sha256     text,
    -- Hash of the tool/endpoint schema seen on this pull, so silent upstream
    -- schema changes are detectable.
    schema_hash    text,
    latency_ms     integer,
    created_at     timestamptz not null default now(),
    unique (source, site_id, pulled_at, tool_name)
);

create index if not exists forecast_pulls_site_time on forecast_pulls (site_id, pulled_at desc);
create index if not exists forecast_pulls_failed on forecast_pulls (pulled_at desc) where not ok;

-- Daily tools/list snapshot, so a changed tool surface raises an alert instead
-- of silently changing what we parse.
create table if not exists connector_tool_schemas (
    id           uuid primary key default gen_random_uuid(),
    source       forecast_source not null,
    observed_at  timestamptz not null,
    tool_name    text not null,
    schema_hash  text not null,
    schema_json  jsonb not null,
    unique (source, tool_name, schema_hash)
);

-- --------------------------------------------------- parsed forecast rows ---

create table if not exists forecast_dayparts (
    id                uuid primary key default gen_random_uuid(),
    pull_id           uuid not null references forecast_pulls(id) on delete cascade,
    source            forecast_source not null,
    site_id           text not null references sites(id),
    pulled_at         timestamptz not null,
    -- Target period.
    local_date        date not null,
    daypart           text not null check (daypart in ('day','night')),
    period_start_utc  timestamptz not null,
    period_end_utc    timestamptz not null,
    lead_hours        double precision not null,
    lead_day          integer not null,
    -- Forecast signals.
    icon_code         integer,
    wx_phrase         text,
    precip_chance     double precision,
    precip_type       text,
    qpf_in            double precision,
    thunder_category  text,
    thunder_index     integer,
    cloud_cover       double precision,
    temperature_f     double precision,
    -- Derived thunder signals, scored separately (see docs/field-map.md).
    thunder_by_index  boolean,
    thunder_by_phrase boolean,
    raw               jsonb,
    created_at        timestamptz not null default now(),
    unique (source, site_id, pulled_at, local_date, daypart)
);

create index if not exists forecast_dayparts_target
    on forecast_dayparts (site_id, local_date, daypart, lead_day);
create index if not exists forecast_dayparts_source_lead
    on forecast_dayparts (source, lead_day);

create table if not exists forecast_hourly (
    id               uuid primary key default gen_random_uuid(),
    pull_id          uuid not null references forecast_pulls(id) on delete cascade,
    source           forecast_source not null,
    site_id          text not null references sites(id),
    pulled_at        timestamptz not null,
    valid_utc        timestamptz not null,
    lead_hours       double precision not null,
    icon_code        integer,
    wx_phrase        text,
    precip_chance    double precision,
    precip_type      text,
    qpf_in           double precision,
    temperature_f    double precision,
    dewpoint_f       double precision,
    wind_dir         integer,
    wind_kt          double precision,
    ceiling_ft       integer,
    visibility_sm    double precision,
    flight_category  text check (flight_category in ('VFR','MVFR','IFR','LIFR')),
    thunder_index    integer,
    raw              jsonb,
    created_at       timestamptz not null default now(),
    unique (source, site_id, pulled_at, valid_utc)
);

create index if not exists forecast_hourly_target on forecast_hourly (site_id, valid_utc, lead_hours);

-- ------------------------------------------------------- observations ------

create table if not exists obs_metar (
    site_id         text not null references sites(id),
    valid_utc       timestamptz not null,
    ceiling_ft      integer,
    vis_sm          double precision,
    flight_category text check (flight_category in ('VFR','MVFR','IFR','LIFR')),
    wxcodes         text,
    temp_f          double precision,
    dewpoint_f      double precision,
    wind_dir        integer,
    wind_kt         double precision,
    p01i_in         double precision,
    ts_in_body      boolean not null default false,
    vcts            boolean not null default false,
    ltg_remark      boolean not null default false,
    raw_metar       text,
    ingested_at     timestamptz not null default now(),
    primary key (site_id, valid_utc)
);

create index if not exists obs_metar_thunder on obs_metar (site_id, valid_utc)
    where ts_in_body or vcts;

create table if not exists obs_lightning_agg (
    site_id            text not null references sites(id),
    hour_utc           timestamptz not null,
    flashes_5nm        integer not null default 0,
    flashes_10nm       integer not null default 0,
    flashes_20nm       integer not null default 0,
    granules_expected  integer not null default 0,
    granules_read      integer not null default 0,
    granules_missing   integer not null default 0,
    granules_failed    integer not null default 0,
    -- False when the hour was only partly read: a zero count from an incomplete
    -- hour is not evidence of "no thunder" and scoring must be able to drop it.
    complete           boolean not null default false,
    satellite          text,
    ingested_at        timestamptz not null default now(),
    primary key (site_id, hour_utc)
);

create table if not exists obs_mrms_agg (
    site_id                 text not null references sites(id),
    hour_utc                timestamptz not null,
    qpe_in                  double precision,
    qpe_product             text,
    -- PrecipFlag rolled up over the hour's samples.
    flag_samples            integer not null default 0,
    flag_convective_samples integer not null default 0,
    flag_stratiform_samples integer not null default 0,
    flag_max_severity       integer,
    flag_at_site_modal      integer,
    ingested_at             timestamptz not null default now(),
    primary key (site_id, hour_utc)
);

-- ---------------------------------------------------------- baselines ------

create table if not exists baseline_mos (
    site_id       text not null references sites(id),
    model         text not null,                 -- NBS | NBE | MAV | MEX
    runtime_utc   timestamptz not null,
    ftime_utc     timestamptz not null,
    pop_06        double precision,
    pop_12        double precision,
    -- Stored verbatim: the column-to-meaning mapping for NBS thunder is not
    -- documented upstream and is resolved empirically. See docs/field-map.md.
    thunder_raw   jsonb,
    ceiling_code  integer,
    vis_code      integer,
    temp_f        double precision,
    dewpoint_f    double precision,
    raw           jsonb,
    ingested_at   timestamptz not null default now(),
    primary key (site_id, model, runtime_utc, ftime_utc)
);

-- Kept as a distinct table from baseline_mos so NBM-specific fields can be
-- added without disturbing the GFS MOS rows.
create table if not exists baseline_nbm (
    site_id        text not null references sites(id),
    model          text not null,
    runtime_utc    timestamptz not null,
    ftime_utc      timestamptz not null,
    pop            double precision,
    thunder_prob   double precision,
    ceiling_ft     integer,
    vis_sm         double precision,
    raw            jsonb,
    ingested_at    timestamptz not null default now(),
    primary key (site_id, model, runtime_utc, ftime_utc)
);

create table if not exists baseline_spc (
    site_id           text not null references sites(id),
    outlook_day       integer not null,
    issue_utc         timestamptz not null,
    valid_local_date  date not null,
    category          text,
    category_rank     integer not null default 0,
    source_url        text,
    ingested_at       timestamptz not null default now(),
    primary key (site_id, outlook_day, issue_utc)
);

-- ------------------------------------------------------ run bookkeeping ----

-- One row per ingest/collect job run, so the report's completeness section and
-- the daily heartbeat have something to read.
create table if not exists job_runs (
    id            uuid primary key default gen_random_uuid(),
    job           text not null,
    target_date   date,
    started_at    timestamptz not null default now(),
    finished_at   timestamptz,
    ok            boolean,
    rows_written  integer,
    detail        jsonb,
    error         text
);

create index if not exists job_runs_recent on job_runs (job, started_at desc);
