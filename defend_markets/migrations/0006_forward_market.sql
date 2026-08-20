-- Phase D forward TT market collection: discovery, observations, M5 live
-- inference and market-ruler rows. INSERT-only / idempotent upserts.
-- Observations carry a UNIQUE (provider_event_id, bookmaker, market, side,
-- observed_at) so restarting a soak never duplicates rows.

CREATE TABLE IF NOT EXISTS tt_forward_events (
    forward_event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider TEXT NOT NULL,
    provider_event_id TEXT NOT NULL,
    canonical_event_id TEXT,
    competition TEXT NOT NULL,
    player_a_key TEXT NOT NULL,
    player_b_key TEXT NOT NULL,
    player_a_name TEXT,
    player_b_name TEXT,
    scheduled_commence TIMESTAMPTZ NOT NULL,
    match_level TEXT NOT NULL DEFAULT 'UNMATCHED'
        CHECK (match_level IN ('EXACT_ID', 'NORMALIZED', 'IDENTITY_MAP',
                               'PARTICIPANT_ID', 'AMBIGUOUS', 'UNMATCHED')),
    state TEXT NOT NULL DEFAULT 'UPCOMING'
        CHECK (state IN ('UPCOMING', 'LIVE', 'SETTLED', 'UNMATCHED', 'AMBIGUOUS',
                         'CANCELLED')),
    discovered_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    last_odds_poll_at TIMESTAMPTZ,
    commence_crossed_at TIMESTAMPTZ,
    settled_at TIMESTAMPTZ,
    UNIQUE (provider, provider_event_id)
);
CREATE INDEX IF NOT EXISTS idx_tt_forward_events_commence
    ON tt_forward_events(scheduled_commence);
CREATE INDEX IF NOT EXISTS idx_tt_forward_events_canonical
    ON tt_forward_events(canonical_event_id);

CREATE TABLE IF NOT EXISTS tt_market_observations (
    observation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    forward_event_id BIGINT NOT NULL REFERENCES tt_forward_events(forward_event_id)
        ON DELETE CASCADE,
    canonical_event_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_event_id TEXT NOT NULL,
    bookmaker TEXT NOT NULL,
    market TEXT NOT NULL,
    provider_market_id TEXT,
    side TEXT NOT NULL,
    participant_key TEXT,
    price NUMERIC(10,4) NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    scheduled_commence TIMESTAMPTZ NOT NULL,
    seconds_to_commence NUMERIC(12,2) NOT NULL,
    raw_provenance TEXT NOT NULL,
    raw_evidence_ref TEXT,
    observation_class TEXT NOT NULL
        CHECK (observation_class IN ('OPEN', 'INTERMEDIATE', 'LAST_VALID_PREMATCH',
                                     'POST_COMMENCE')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider_event_id, bookmaker, market, side, observed_at)
);
CREATE INDEX IF NOT EXISTS idx_tt_market_observations_canonical
    ON tt_market_observations(canonical_event_id, observed_at);
CREATE INDEX IF NOT EXISTS idx_tt_market_observations_class
    ON tt_market_observations(canonical_event_id, observation_class);

CREATE TABLE IF NOT EXISTS tt_m5_live_predictions (
    prediction_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    canonical_event_id TEXT NOT NULL UNIQUE,
    player_a_key TEXT NOT NULL,
    player_b_key TEXT NOT NULL,
    model_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    feature_snapshot_id TEXT NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL,
    p_a NUMERIC(8,6) NOT NULL,
    p_b NUMERIC(8,6) NOT NULL,
    availability TEXT NOT NULL
        CHECK (availability IN ('AVAILABLE', 'INSUFFICIENT_HISTORY')),
    feature_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tt_market_ruler_rows (
    ruler_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    observation_id BIGINT NOT NULL UNIQUE
        REFERENCES tt_market_observations(observation_id) ON DELETE CASCADE,
    canonical_event_id TEXT NOT NULL,
    observation_class TEXT NOT NULL,
    side_a_price NUMERIC(10,4),
    side_b_price NUMERIC(10,4),
    raw_implied_p_a NUMERIC(10,6),
    raw_implied_p_b NUMERIC(10,6),
    overround NUMERIC(10,6),
    no_vig_p_a NUMERIC(10,6),
    no_vig_p_b NUMERIC(10,6),
    m5_p_a NUMERIC(10,6),
    model_market_disagreement NUMERIC(12,8),
    observation_age_seconds NUMERIC(12,2),
    seconds_to_commence NUMERIC(12,2),
    actual NUMERIC(3,1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tt_market_ruler_rows_event
    ON tt_market_ruler_rows(canonical_event_id, observation_class);

-- Immutable raw provider evidence: INSERT-only, keyed by content sha256.
-- Normalized observations always carry the sha256 as raw_evidence_ref and
-- raw payloads are never overwritten.
CREATE TABLE IF NOT EXISTS tt_raw_evidence (
    evidence_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    evidence_sha256 TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    status_code INTEGER,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);