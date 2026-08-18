CREATE TABLE IF NOT EXISTS provider_feeds (
    feed_id TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('HEALTHY', 'DEGRADED', 'UNAVAILABLE', 'UNCONFIGURED')),
    last_attempt_at TIMESTAMPTZ,
    last_success_at TIMESTAMPTZ,
    last_error TEXT,
    latency_ms INTEGER,
    records_ingested INTEGER NOT NULL DEFAULT 0,
    last_record_at TIMESTAMPTZ,
    detail_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS market_feed_records (
    record_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    feed_id TEXT NOT NULL REFERENCES provider_feeds(feed_id),
    record_key TEXT NOT NULL,
    payload JSONB NOT NULL,
    observed_at TIMESTAMPTZ,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (feed_id, record_key)
);

CREATE INDEX IF NOT EXISTS idx_feed_records_feed_received
    ON market_feed_records(feed_id, received_at DESC);

CREATE TABLE IF NOT EXISTS tt_match_results (
    result_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_key TEXT UNIQUE NOT NULL,
    league_key TEXT NOT NULL,
    home_participant_key TEXT NOT NULL,
    away_participant_key TEXT NOT NULL,
    home_score INTEGER NOT NULL CHECK (home_score >= 0),
    away_score INTEGER NOT NULL CHECK (away_score >= 0),
    completed_at TIMESTAMPTZ NOT NULL,
    source_provider TEXT NOT NULL,
    raw_ref TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tt_match_results_completed
    ON tt_match_results(completed_at DESC);