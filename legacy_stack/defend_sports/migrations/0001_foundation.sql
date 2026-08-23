CREATE TABLE IF NOT EXISTS sports_schema_migrations (
    version INTEGER PRIMARY KEY CHECK (version > 0),
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sports_users (
    user_id UUID PRIMARY KEY,
    external_subject TEXT UNIQUE NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('OWNER', 'ADMIN', 'ANALYST', 'MEMBER')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sports_user_risk (
    user_id UUID PRIMARY KEY REFERENCES sports_users(user_id) ON DELETE CASCADE,
    bankroll NUMERIC(18,4) NOT NULL CHECK (bankroll >= 0),
    user_max_stake_pct NUMERIC(8,6) NOT NULL CHECK (
        user_max_stake_pct >= 0 AND user_max_stake_pct <= 1
    ),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS provider_sources (
    source_id UUID PRIMARY KEY,
    provider_name TEXT NOT NULL,
    source_key TEXT NOT NULL,
    display_name TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider_name, source_key)
);

CREATE TABLE IF NOT EXISTS sportsbooks (
    sportsbook_id UUID PRIMARY KEY,
    sportsbook_key TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
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

CREATE TABLE IF NOT EXISTS participants (
    participant_id UUID PRIMARY KEY,
    sport_id UUID NOT NULL REFERENCES sports(sport_id),
    participant_key TEXT NOT NULL,
    display_name TEXT NOT NULL,
    participant_type TEXT NOT NULL CHECK (participant_type IN ('PLAYER', 'TEAM')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (sport_id, participant_key)
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

CREATE TABLE IF NOT EXISTS audit_events (
    audit_event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_subject TEXT,
    event_type TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT,
    detail_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sport_events_league_scheduled
    ON sport_events(league_id, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_live_observations_event_observed
    ON live_observations(event_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_odds_snapshots_selection_observed
    ON odds_snapshots(selection_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_provider_health_source_observed
    ON provider_health(source_id, observed_at DESC);
