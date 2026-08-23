-- 0025 Markets-owned live sports/odds pipeline tables (M4.8.2D).
--
-- Markets owns its live collection pipeline end-to-end. These tables mirror the
-- provider provenance + append-only observation shapes the legacy Sports schema
-- used, but live in the MARKETS database and are written only by Markets-owned
-- code. The legacy Sports schema is never written from Markets.

CREATE TABLE IF NOT EXISTS provider_sources (
    source_id UUID PRIMARY KEY,
    provider_name TEXT NOT NULL,
    source_key TEXT NOT NULL,
    display_name TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider_name, source_key)
);

CREATE TABLE IF NOT EXISTS sports (
    sport_id UUID PRIMARY KEY,
    sport_key TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS leagues (
    league_id UUID PRIMARY KEY,
    sport_id UUID NOT NULL REFERENCES sports(sport_id),
    league_key TEXT NOT NULL,
    display_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (sport_id, league_key)
);

CREATE TABLE IF NOT EXISTS sport_events (
    event_id UUID PRIMARY KEY,
    sport_id UUID NOT NULL REFERENCES sports(sport_id),
    league_id UUID REFERENCES leagues(league_id),
    event_key TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    scheduled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS raw_provider_events (
    raw_event_id UUID PRIMARY KEY,
    source_id UUID NOT NULL REFERENCES provider_sources(source_id),
    provider_event_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_id, provider_event_id)
);

CREATE TABLE IF NOT EXISTS live_observations (
    live_observation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id UUID NOT NULL REFERENCES provider_sources(source_id),
    event_id UUID NOT NULL REFERENCES sport_events(event_id),
    state_json JSONB NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_event_id UUID NOT NULL REFERENCES raw_provider_events(raw_event_id)
);

CREATE TABLE IF NOT EXISTS markets (
    market_id UUID PRIMARY KEY,
    event_id UUID NOT NULL REFERENCES sport_events(event_id),
    market_key TEXT NOT NULL,
    display_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (event_id, market_key)
);

CREATE TABLE IF NOT EXISTS selections (
    selection_id UUID PRIMARY KEY,
    market_id UUID NOT NULL REFERENCES markets(market_id),
    selection_key TEXT NOT NULL,
    display_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (market_id, selection_key)
);

CREATE TABLE IF NOT EXISTS odds_snapshots (
    odds_snapshot_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id UUID NOT NULL REFERENCES provider_sources(source_id),
    market_id UUID NOT NULL REFERENCES markets(market_id),
    selection_id UUID NOT NULL REFERENCES selections(selection_id),
    decimal_odds NUMERIC(18,6) NOT NULL CHECK (decimal_odds > 1),
    observed_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_event_id UUID NOT NULL REFERENCES raw_provider_events(raw_event_id)
);

CREATE TABLE IF NOT EXISTS provider_health (
    provider_health_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id UUID NOT NULL REFERENCES provider_sources(source_id),
    status TEXT NOT NULL CHECK (status IN ('HEALTHY', 'DEGRADED', 'UNAVAILABLE')),
    detail_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    observed_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS provider_discovery (
    discovery_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id UUID NOT NULL REFERENCES provider_sources(source_id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '[]'::jsonb,
    observed_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS provider_quota (
    quota_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id UUID NOT NULL REFERENCES provider_sources(source_id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    requests_remaining BIGINT,
    requests_used BIGINT,
    requests_last TEXT,
    status TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sport_events_league_scheduled
    ON sport_events(league_id, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_live_observations_event_observed
    ON live_observations(event_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_odds_snapshots_selection_observed
    ON odds_snapshots(selection_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_provider_health_source_observed
    ON provider_health(source_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_provider_quota_source
    ON provider_quota(source_id, received_at DESC);
