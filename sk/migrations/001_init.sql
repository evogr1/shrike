-- Search Kestrel schema v1 (design doc, Contracts C2).
-- Dates are TEXT 'YYYY-MM-DD' (Search Console dates, US Pacific).
-- Timestamps are TEXT ISO 8601 UTC.

CREATE TABLE schema_version (version INTEGER NOT NULL);
INSERT INTO schema_version (version) VALUES (0);

CREATE TABLE site_range (
    site            TEXT PRIMARY KEY,
    first_date      TEXT,           -- set once at first backfill, never moved
    last_final_date TEXT,           -- refreshed by every backfill and nightly run
    updated_at      TEXT
);

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE pulls (
    id          INTEGER PRIMARY KEY,
    site        TEXT NOT NULL,
    date        TEXT NOT NULL,
    dims        TEXT NOT NULL CHECK (dims IN ('site', 'page', 'page_query')),
    data_state  TEXT NOT NULL CHECK (data_state = 'final'),
    status      TEXT NOT NULL CHECK (status IN ('ok', 'error')),
    row_count   INTEGER NOT NULL DEFAULT 0,
    truncated   INTEGER NOT NULL DEFAULT 0 CHECK (truncated IN (0, 1)),
    error       TEXT,
    started_at  TEXT NOT NULL,
    finished_at TEXT
);
CREATE UNIQUE INDEX pulls_one_ok ON pulls (site, date, dims) WHERE status = 'ok';
CREATE INDEX pulls_finished ON pulls (finished_at);

CREATE TABLE gsc_site (
    site        TEXT NOT NULL,
    date        TEXT NOT NULL,
    clicks      INTEGER NOT NULL,
    impressions INTEGER NOT NULL,
    ctr         REAL NOT NULL,
    position    REAL NOT NULL,
    pull_id     INTEGER NOT NULL REFERENCES pulls (id),
    PRIMARY KEY (site, date)
);

CREATE TABLE gsc_page (
    site        TEXT NOT NULL,
    date        TEXT NOT NULL,
    page        TEXT NOT NULL,
    clicks      INTEGER NOT NULL,
    impressions INTEGER NOT NULL,
    ctr         REAL NOT NULL,
    position    REAL NOT NULL,
    pull_id     INTEGER NOT NULL REFERENCES pulls (id),
    PRIMARY KEY (site, date, page)
);
CREATE INDEX gsc_page_by_page ON gsc_page (site, page, date);

CREATE TABLE gsc_page_query (
    site        TEXT NOT NULL,
    date        TEXT NOT NULL,
    page        TEXT NOT NULL,
    query       TEXT NOT NULL,
    clicks      INTEGER NOT NULL,
    impressions INTEGER NOT NULL,
    ctr         REAL NOT NULL,
    position    REAL NOT NULL,
    pull_id     INTEGER NOT NULL REFERENCES pulls (id),
    PRIMARY KEY (site, date, page, query)
);
CREATE INDEX gsc_page_query_by_page ON gsc_page_query (site, page, date);

-- Application code can never change stored final rows.
CREATE TRIGGER gsc_site_no_update BEFORE UPDATE ON gsc_site
BEGIN SELECT RAISE(ABORT, 'gsc_site is append-only'); END;
CREATE TRIGGER gsc_site_no_delete BEFORE DELETE ON gsc_site
BEGIN SELECT RAISE(ABORT, 'gsc_site is append-only'); END;
CREATE TRIGGER gsc_page_no_update BEFORE UPDATE ON gsc_page
BEGIN SELECT RAISE(ABORT, 'gsc_page is append-only'); END;
CREATE TRIGGER gsc_page_no_delete BEFORE DELETE ON gsc_page
BEGIN SELECT RAISE(ABORT, 'gsc_page is append-only'); END;
CREATE TRIGGER gsc_page_query_no_update BEFORE UPDATE ON gsc_page_query
BEGIN SELECT RAISE(ABORT, 'gsc_page_query is append-only'); END;
CREATE TRIGGER gsc_page_query_no_delete BEFORE DELETE ON gsc_page_query
BEGIN SELECT RAISE(ABORT, 'gsc_page_query is append-only'); END;

CREATE TABLE baselines (
    site        TEXT NOT NULL,
    label       TEXT NOT NULL,
    start_date  TEXT NOT NULL,
    end_date    TEXT NOT NULL,
    clicks      INTEGER NOT NULL,
    impressions INTEGER NOT NULL,
    ctr         REAL NOT NULL,
    position    REAL NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (site, label)
);

-- Phase 1 tables are created now so Phase 1 needs no migration.
CREATE TABLE opportunities (
    id                TEXT PRIMARY KEY,
    site              TEXT NOT NULL,
    type              TEXT NOT NULL CHECK (type IN ('striking_distance', 'low_ctr', 'decaying')),
    page              TEXT NOT NULL,
    query             TEXT NOT NULL DEFAULT '',
    score             REAL NOT NULL,
    metrics           TEXT NOT NULL,
    status            TEXT NOT NULL CHECK (status IN ('new', 'sent', 'done', 'dismissed', 'expired')),
    status_changed_at TEXT NOT NULL,
    first_seen        TEXT NOT NULL,
    last_seen         TEXT NOT NULL,
    last_detected_run INTEGER,
    weeks_missing     INTEGER NOT NULL DEFAULT 0,
    card_id           TEXT
);
CREATE INDEX opportunities_status ON opportunities (status);

CREATE TABLE fixes (
    id                  INTEGER PRIMARY KEY,
    opportunity_id      TEXT NOT NULL UNIQUE REFERENCES opportunities (id),
    site                TEXT NOT NULL,
    page                TEXT NOT NULL,
    ship_date           TEXT NOT NULL,
    ship_date_source    TEXT NOT NULL CHECK (ship_date_source IN ('trello_move', 'card_line')),
    before_start        TEXT,
    before_end          TEXT,
    after_start         TEXT,
    after_end           TEXT,
    clicks_before       INTEGER,
    clicks_after        INTEGER,
    impr_before         INTEGER,
    impr_after          INTEGER,
    group_size          INTEGER,
    group_median_growth REAL,
    effect_clicks       REAL,
    included            INTEGER,
    exclusion_reason    TEXT,
    measured_at         TEXT
);

CREATE TABLE runs (
    id                 INTEGER PRIMARY KEY,
    job                TEXT NOT NULL,
    step               TEXT,
    parent_id          INTEGER REFERENCES runs (id),
    status             TEXT NOT NULL CHECK (status IN ('running', 'ok', 'error')),
    started_at         TEXT NOT NULL,
    finished_at        TEXT,
    error              TEXT,
    undelivered_alerts INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX runs_job_started ON runs (job, started_at);

CREATE TABLE events (
    id         INTEGER PRIMARY KEY,
    kind       TEXT NOT NULL,
    subject    TEXT NOT NULL,
    day        TEXT NOT NULL,           -- date in general.timezone, or 'once'
    message    TEXT NOT NULL,
    delivered  INTEGER NOT NULL,
    card_id    TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (kind, subject, day)
);

CREATE VIEW v_gsc_site AS
    SELECT site, date, clicks, impressions, ctr, position FROM gsc_site;
CREATE VIEW v_gsc_page AS
    SELECT site, date, page, clicks, impressions, ctr, position FROM gsc_page;
CREATE VIEW v_gsc_page_query AS
    SELECT site, date, page, query, clicks, impressions, ctr, position FROM gsc_page_query;

-- Every expected (site, date, dims) between first_date and last_final_date,
-- so a date that was never pulled shows as 'missing'.
CREATE VIEW v_coverage AS
WITH RECURSIVE cal (site, date, last) AS (
    SELECT site, first_date, last_final_date
    FROM site_range
    WHERE first_date IS NOT NULL AND last_final_date IS NOT NULL AND first_date <= last_final_date
    UNION ALL
    SELECT site, date(date, '+1 day'), last FROM cal WHERE date < last
),
dimset (dims) AS (VALUES ('site'), ('page'), ('page_query'))
SELECT cal.site AS site,
       cal.date AS date,
       dimset.dims AS dims,
       CASE WHEN p.id IS NULL THEN 'missing'
            WHEN p.truncated = 1 THEN 'truncated'
            ELSE 'final' END AS state,
       p.id AS pull_id
FROM cal
CROSS JOIN dimset
LEFT JOIN pulls p
       ON p.site = cal.site AND p.date = cal.date AND p.dims = dimset.dims AND p.status = 'ok';
