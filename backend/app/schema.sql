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
  source_doc_id  INT REFERENCES source_doc(id),
  source_page    INT,
  extraction     TEXT,                   -- parser | llm | manual | feed
  confidence     REAL,
  simulated      BOOLEAN DEFAULT FALSE,
  created_at     TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS job_geom_idx ON job USING GIST (geom);
CREATE INDEX IF NOT EXISTS job_window_idx ON job USING GIST (work_window);

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
