CREATE TABLE region (
    id       TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    timezone TEXT NOT NULL
);

CREATE TABLE theater (
    id              TEXT PRIMARY KEY,
    region_id       TEXT NOT NULL REFERENCES region(id),
    name            TEXT NOT NULL,
    website_url     TEXT NOT NULL,
    timezone        TEXT NOT NULL,
    adapter         TEXT NOT NULL,
    adapter_config  TEXT NOT NULL DEFAULT '{}',
    tmdb_enrichment INTEGER NOT NULL DEFAULT 1,
    enabled         INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE film (
    id                    INTEGER PRIMARY KEY,
    title                 TEXT NOT NULL,
    normalized_title      TEXT NOT NULL UNIQUE,
    scraped_description   TEXT,
    scraped_poster_url    TEXT,
    runtime_minutes       INTEGER,
    tmdb_id               INTEGER,
    tmdb_description      TEXT,
    tmdb_poster_path      TEXT,
    tmdb_match_confidence REAL,
    enrichment_status     TEXT NOT NULL DEFAULT 'pending'
);

CREATE TABLE scrape_run (
    id                   INTEGER PRIMARY KEY,
    theater_id           TEXT NOT NULL REFERENCES theater(id),
    started_at           TEXT NOT NULL,
    finished_at          TEXT,
    outcome              TEXT,
    screenings_found     INTEGER NOT NULL DEFAULT 0,
    screenings_new       INTEGER NOT NULL DEFAULT 0,
    screenings_updated   INTEGER NOT NULL DEFAULT 0,
    screenings_cancelled INTEGER NOT NULL DEFAULT 0,
    error_detail         TEXT,
    alerted              INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE screening (
    id                INTEGER PRIMARY KEY,
    theater_id        TEXT NOT NULL REFERENCES theater(id),
    film_id           INTEGER NOT NULL REFERENCES film(id),
    starts_at         TEXT NOT NULL,
    starts_at_local   TEXT NOT NULL,
    ticket_url        TEXT,
    format            TEXT,
    event_note        TEXT,
    status            TEXT NOT NULL DEFAULT 'scheduled',
    first_seen_run_id INTEGER REFERENCES scrape_run(id),
    last_seen_run_id  INTEGER REFERENCES scrape_run(id),
    UNIQUE (theater_id, film_id, starts_at)
);

CREATE INDEX idx_screening_theater_time ON screening (theater_id, starts_at);
CREATE INDEX idx_scrape_run_theater ON scrape_run (theater_id, started_at);
