CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS org (
  id     TEXT PRIMARY KEY,               -- 'desc', 'gpc'
  name   TEXT NOT NULL,
  kind   TEXT NOT NULL DEFAULT 'utility', -- utility | vendor
  color  TEXT
);

CREATE TABLE IF NOT EXISTS source_doc (
  id          SERIAL PRIMARY KEY,
  org_id      TEXT REFERENCES org(id),
  title       TEXT,
  url         TEXT,
  local_path  TEXT,
  kind        TEXT,                      -- filing | organizer | news | weather
  fetched_at  TIMESTAMPTZ DEFAULT now(),
  ceii_flag   BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS job (
  id             TEXT PRIMARY KEY,
  org_id         TEXT NOT NULL REFERENCES org(id),
  name           TEXT NOT NULL,
  ref            TEXT,                   -- utility's own project id
  description    TEXT,
  horizon        TEXT NOT NULL,          -- long | near | emergency
  job_type       TEXT NOT NULL,          -- new_line | line_upgrade | substation | phase | restoration
  voltage_kv     INT,
  endpoints      TEXT[],
  geom           GEOGRAPHY NOT NULL,
  geom_quality   TEXT NOT NULL,          -- exact | existing_path | straight_line | point | manual | geocoded_news
  work_window    TSTZRANGE NOT NULL,
  window_basis   TEXT NOT NULL,          -- filed | spend_years | default_duration
  in_service     DATE,
  cost_usd       NUMERIC,
  resources      TEXT[],
  parent_job_id  TEXT REFERENCES job(id) ON DELETE CASCADE,
  phase          TEXT,                   -- set on derived near-term phases
  source_doc_id  INT REFERENCES source_doc(id),
  source_page    INT,
  extraction     TEXT,                   -- parser | llm | manual | feed
  confidence     REAL,
  located_via    JSONB,                  -- how each endpoint was found: organizer, osm id, gemini pick, town
  simulated      BOOLEAN DEFAULT FALSE,
  created_at     TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS job_geom_idx ON job USING GIST (geom);
CREATE INDEX IF NOT EXISTS job_window_idx ON job USING GIST (work_window);

CREATE TABLE IF NOT EXISTS tract (
  geoid          TEXT PRIMARY KEY,
  state          TEXT,
  geom           GEOMETRY(MultiPolygon, 4326),
  risk           REAL,                   -- FEMA NRI hurricane risk score / 100
  vulnerability  REAL                    -- CDC SVI overall percentile
);
CREATE INDEX IF NOT EXISTS tract_geom_idx ON tract USING GIST (geom);

CREATE TABLE IF NOT EXISTS asset (
  id      TEXT PRIMARY KEY,               -- osm id
  org_id  TEXT NOT NULL,
  name    TEXT,
  geom    GEOGRAPHY(Point, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS asset_geom_idx ON asset USING GIST (geom);

CREATE TABLE IF NOT EXISTS grid_line (
  id       TEXT PRIMARY KEY,               -- osm way id
  voltage  INT,                            -- highest circuit voltage in kV
  operator TEXT,
  geom     GEOMETRY(LineString, 4326)
);
CREATE INDEX IF NOT EXISTS grid_line_geom_idx ON grid_line USING GIST (geom);

CREATE TABLE IF NOT EXISTS job_review (
  id             SERIAL PRIMARY KEY,
  org_id         TEXT REFERENCES org(id),
  raw            JSONB NOT NULL,
  reason         TEXT NOT NULL,
  source_doc_id  INT REFERENCES source_doc(id),
  source_page    INT,
  created_at     TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS job_version (
  job_id         TEXT REFERENCES job(id) ON DELETE CASCADE,
  observed_at    TIMESTAMPTZ NOT NULL,
  work_window    TSTZRANGE,
  source_doc_id  INT REFERENCES source_doc(id)
);
SELECT create_hypertable('job_version', by_range('observed_at'), if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS storm_event (
  id             BIGSERIAL,
  ts             TIMESTAMPTZ NOT NULL,
  kind           TEXT,                   -- nhc_track | nws_alert | spc_report | news_incident | outage
  geom           GEOGRAPHY,
  payload        JSONB,
  confidence     REAL,
  verified       BOOLEAN,
  simulated      BOOLEAN DEFAULT FALSE,
  source_doc_id  INT REFERENCES source_doc(id)
);
SELECT create_hypertable('storm_event', by_range('ts'), if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS opportunity (
  id                 SERIAL PRIMARY KEY,
  job_a              TEXT NOT NULL REFERENCES job(id) ON DELETE CASCADE,
  job_b              TEXT NOT NULL REFERENCES job(id) ON DELETE CASCADE,
  horizon            TEXT NOT NULL,
  distance_m         REAL NOT NULL,      -- closest points
  center_distance_m  REAL NOT NULL,      -- organizer rule: midpoint to midpoint
  overlap_m          REAL NOT NULL DEFAULT 0,
  drive_min          REAL,               -- road minutes between the closest points (osrm)
  drive_km           REAL,
  meet_lon           REAL,               -- halfway point by road, a real spot both crews reach equally fast
  meet_lat           REAL,
  meet_road          TEXT,
  meet_min           REAL,
  tier               TEXT NOT NULL,      -- crossing | land | site | crew
  time_overlap       REAL NOT NULL,
  time_gap_days      INT,
  risk               REAL DEFAULT 0,
  vulnerability      REAL DEFAULT 0,
  score              REAL NOT NULL,
  flags              TEXT[] DEFAULT '{}',
  savings_low        NUMERIC,
  savings_high       NUMERIC,
  link               GEOGRAPHY,          -- closest-points segment
  status             TEXT NOT NULL DEFAULT 'not_contacted',
  UNIQUE (job_a, job_b),
  CHECK (job_a < job_b)
);

CREATE TABLE IF NOT EXISTS contact (
  id          SERIAL PRIMARY KEY,
  org_id      TEXT REFERENCES org(id),
  role        TEXT,
  email       TEXT,
  phone       TEXT,
  source_url  TEXT,
  is_demo     BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS outreach (
  id              SERIAL PRIMARY KEY,
  opportunity_id  INT REFERENCES opportunity(id) ON DELETE CASCADE,
  contact_id      INT REFERENCES contact(id),
  kind            TEXT,                  -- utility_intro | vendor_quote
  subject         TEXT,
  body            TEXT,
  state           TEXT DEFAULT 'draft',  -- draft | approved | sent | replied
  approved_by     TEXT,
  sent_at         TIMESTAMPTZ,
  reply_summary   TEXT
);

CREATE TABLE IF NOT EXISTS incident (
  id                  BIGSERIAL,
  ts                  TIMESTAMPTZ NOT NULL,
  mode                TEXT NOT NULL DEFAULT 'replay',  -- replay | live
  kind                TEXT NOT NULL,                   -- downed_line | substation_damage | outage | tree_on_line | flooding | wind_damage | tornado
  geom                GEOGRAPHY(Point, 4326),
  footprint           GEOGRAPHY(MultiPoint, 4326),     -- every merged source location
  where_text          TEXT,
  precision           TEXT,                            -- exact | road | town | county | state
  utility_mentioned   TEXT,
  customers_affected  INT,
  confidence          REAL,
  verified            BOOLEAN,
  needs_confirmation  BOOLEAN,
  sources             JSONB,                           -- [{type, name, url, title, quote_evidence, ts}]
  nearest             JSONB                            -- {org: {asset, km}}
);
SELECT create_hypertable('incident', by_range('ts'), if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS phase_risk (
  job_id      TEXT,
  site        TEXT,
  day         DATE,
  gust_mph    REAL,
  work        TEXT,
  alert       TEXT,
  fetched_at  TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE job ADD COLUMN IF NOT EXISTS located_via JSONB;  -- databases built before the column existed

ALTER TABLE opportunity ADD COLUMN IF NOT EXISTS meet_lon REAL;
ALTER TABLE opportunity ADD COLUMN IF NOT EXISTS meet_lat REAL;
ALTER TABLE opportunity ADD COLUMN IF NOT EXISTS meet_road TEXT;
ALTER TABLE opportunity ADD COLUMN IF NOT EXISTS meet_min REAL;

CREATE TABLE IF NOT EXISTS outlook (
  id          BIGSERIAL,
  mode        TEXT NOT NULL,              -- live | replay
  product     TEXT NOT NULL,              -- spc | spc48 | wpc_ero | nhc_gtwo | nhc_wsp
  day         INT,                        -- outlook day, 1 = the day it was issued
  issued      TIMESTAMPTZ NOT NULL,
  valid_from  TIMESTAMPTZ NOT NULL,
  valid_to    TIMESTAMPTZ NOT NULL,
  level       TEXT,                       -- SLGT, Moderate, 40%, ...
  rank        INT,                        -- 1 low to 5 high, for color and sorting
  label       TEXT,
  props       JSONB,
  source_url  TEXT,
  geom        GEOGRAPHY
);
SELECT create_hypertable('outlook', by_range('valid_from'), if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS job_hazard (
  job_id           TEXT PRIMARY KEY,      -- long-range job id, survives job reloads
  in_floodplain    BOOLEAN,
  flood_zones      TEXT[],
  hurricanes_50mi  INT,
  storms_50mi      INT,
  peak_month       INT,
  since_year       INT,
  checked_at       TIMESTAMPTZ DEFAULT now()
);

-- national expansion: one utility per state, keeping every field the planners publish
ALTER TABLE org ADD COLUMN IF NOT EXISTS state TEXT;  -- home state, two letters
ALTER TABLE org ADD COLUMN IF NOT EXISTS planner TEXT;  -- who publishes its plan: PJM, MISO, SPP, ERCOT, filing...
ALTER TABLE org ADD COLUMN IF NOT EXISTS short TEXT;
ALTER TABLE org ADD COLUMN IF NOT EXISTS login TEXT UNIQUE;  -- crewly username
ALTER TABLE source_doc ADD COLUMN IF NOT EXISTS planner TEXT;
ALTER TABLE source_doc ADD COLUMN IF NOT EXISTS edition TEXT;  -- e.g. MTEP24, RTEP 2025
ALTER TABLE source_doc ADD COLUMN IF NOT EXISTS sha256 TEXT;  -- proves which file the rows came from
ALTER TABLE job ADD COLUMN IF NOT EXISTS state TEXT;
ALTER TABLE job ADD COLUMN IF NOT EXISTS planner TEXT;
ALTER TABLE job ADD COLUMN IF NOT EXISTS source_project_id TEXT;  -- the planner's own id, e.g. PJM b3800
ALTER TABLE job ADD COLUMN IF NOT EXISTS status TEXT;  -- planned, under construction, engineering...
ALTER TABLE job ADD COLUMN IF NOT EXISTS need TEXT;  -- why it is built: reliability, load growth, economic, policy
ALTER TABLE job ADD COLUMN IF NOT EXISTS length_mi REAL;
ALTER TABLE job ADD COLUMN IF NOT EXISTS counties TEXT[];
ALTER TABLE job ADD COLUMN IF NOT EXISTS raw JSONB;  -- the whole source row, nothing thrown away
CREATE INDEX IF NOT EXISTS job_org_state_idx ON job (org_id, state);
UPDATE org SET state = CASE id WHEN 'desc' THEN 'SC' WHEN 'gpc' THEN 'GA' END, planner = 'filing',
               short = CASE id WHEN 'desc' THEN 'Dominion SC' WHEN 'gpc' THEN 'Georgia Power' END,
               login = CASE id WHEN 'desc' THEN 'dominion' WHEN 'gpc' THEN 'georgia' END
WHERE id IN ('desc', 'gpc') AND state IS NULL;
UPDATE job j SET state = o.state, planner = o.planner FROM org o WHERE o.id = j.org_id AND j.state IS NULL;

-- hazards that affect the work: live and outlook layers, ten years of storm history by county and month, fema risk scores
CREATE TABLE IF NOT EXISTS hazard_layer (
  id           BIGSERIAL PRIMARY KEY,
  layer        TEXT NOT NULL,              -- alerts | outlooks | fires | quakes
  hazard       TEXT NOT NULL,              -- wind, storms, tornado, winter, heat, flood, tropical, wildfire, earthquake, hail
  product      TEXT NOT NULL,              -- nws_alert, spc, spc48, spc_fire, wpc_ero, nhc_gtwo, wfigs_*, usgs, cpc_*
  label        TEXT,
  rank         INT,                        -- 1 low to 3 high
  period_start TIMESTAMPTZ NOT NULL,
  period_end   TIMESTAMPTZ NOT NULL,
  props        JSONB,
  source       TEXT,
  fetched_at   TIMESTAMPTZ NOT NULL,
  geom         GEOGRAPHY NOT NULL
);
CREATE INDEX IF NOT EXISTS hazard_layer_geom_idx ON hazard_layer USING GIST (geom);
CREATE INDEX IF NOT EXISTS hazard_layer_period_idx ON hazard_layer (hazard, period_start, period_end);
CREATE TABLE IF NOT EXISTS hazard_fetch (
  product     TEXT PRIMARY KEY,
  fetched_at  TIMESTAMPTZ NOT NULL,
  rows        INT
);
CREATE TABLE IF NOT EXISTS hazard_climate (
  county_fips TEXT NOT NULL,
  state       TEXT,
  month       INT NOT NULL,
  hazard      TEXT NOT NULL,
  event_days  INT NOT NULL,                -- distinct days with an event over all the years
  years       INT NOT NULL,
  damage_usd  NUMERIC,
  PRIMARY KEY (county_fips, month, hazard)
);
CREATE TABLE IF NOT EXISTS hazard_nri (
  county_fips TEXT PRIMARY KEY,
  state       TEXT,
  county      TEXT,
  risk_score  REAL,
  scores      JSONB                        -- hazard -> fema risk score 0-100
);
