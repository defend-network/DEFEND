CREATE TABLE IF NOT EXISTS market_schema_migrations (
    version INTEGER PRIMARY KEY CHECK (version > 0),
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS market_instruments (
    instrument_id UUID PRIMARY KEY,
    instrument_key TEXT UNIQUE NOT NULL,
    instrument_type TEXT NOT NULL CHECK (instrument_type IN (
        'SPORTS_MARKET', 'EQUITY', 'ETF', 'INDEX', 'MACRO_SERIES',
        'PREDICTION_CONTRACT', 'FUTURES', 'OPTIONS',
        'CRYPTO_SPOT', 'CRYPTO_DERIVATIVE'
    )),
    display_name TEXT NOT NULL,
    venue_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'SUSPENDED', 'RETIRED')),
    taxonomy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS market_instrument_links (
    link_id UUID PRIMARY KEY,
    instrument_id UUID NOT NULL REFERENCES market_instruments(instrument_id) ON DELETE CASCADE,
    source_desk TEXT NOT NULL,
    source_table TEXT NOT NULL,
    source_id UUID NOT NULL,
    link_type TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (instrument_id, source_desk, source_table, source_id)
);

CREATE TABLE IF NOT EXISTS market_events (
    event_id UUID PRIMARY KEY,
    event_key TEXT UNIQUE NOT NULL,
    event_type TEXT NOT NULL,
    title TEXT NOT NULL,
    event_time TIMESTAMPTZ,
    announced_at TIMESTAMPTZ,
    retrieved_at TIMESTAMPTZ,
    source_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'RESOLVED', 'EXPIRED', 'CANCELLED')),
    detail_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS market_event_entities (
    entity_id UUID PRIMARY KEY,
    entity_key TEXT UNIQUE NOT NULL,
    entity_type TEXT NOT NULL CHECK (entity_type IN (
        'PLAYER', 'TEAM', 'PERSON', 'ORGANIZATION', 'SECTOR',
        'INSTRUMENT', 'COMMODITY', 'CURRENCY', 'GEOGRAPHY', 'INDEX'
    )),
    display_name TEXT NOT NULL,
    taxonomy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS market_event_entity_links (
    link_id UUID PRIMARY KEY,
    event_id UUID NOT NULL REFERENCES market_events(event_id) ON DELETE CASCADE,
    entity_id UUID NOT NULL REFERENCES market_event_entities(entity_id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (event_id, entity_id, role)
);

CREATE TABLE IF NOT EXISTS market_event_impacts (
    impact_id UUID PRIMARY KEY,
    event_id UUID NOT NULL REFERENCES market_events(event_id) ON DELETE CASCADE,
    instrument_id UUID NOT NULL REFERENCES market_instruments(instrument_id) ON DELETE CASCADE,
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('POSITIVE', 'NEGATIVE', 'NEUTRAL', 'UNKNOWN')),
    strength NUMERIC(6,4) NOT NULL CHECK (strength >= -1 AND strength <= 1),
    evidence_ref TEXT,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (window_end > window_start)
);

CREATE TABLE IF NOT EXISTS market_strategies (
    strategy_id UUID PRIMARY KEY,
    strategy_key TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    display_name TEXT NOT NULL,
    hypothesis TEXT NOT NULL,
    lifecycle TEXT NOT NULL CHECK (lifecycle IN (
        'PLANNED', 'EXPERIMENTAL', 'PAPER', 'VALIDATED', 'RETIRED'
    )),
    params_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_ref TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (strategy_key, version)
);

CREATE TABLE IF NOT EXISTS market_strategy_runs (
    run_id UUID PRIMARY KEY,
    strategy_id UUID NOT NULL REFERENCES market_strategies(strategy_id),
    inputs_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    model_version TEXT,
    status TEXT NOT NULL DEFAULT 'RUNNING' CHECK (status IN ('RUNNING', 'SUCCEEDED', 'FAILED')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS market_strategy_results (
    result_id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES market_strategy_runs(run_id),
    metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    out_of_sample BOOLEAN NOT NULL DEFAULT FALSE,
    approved BOOLEAN,
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS market_risk_policies (
    policy_id UUID PRIMARY KEY,
    policy_key TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    tier TEXT NOT NULL CHECK (tier IN ('CONSERVATIVE', 'CORE', 'AGGRESSIVE')),
    params_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (policy_key, version)
);

CREATE TABLE IF NOT EXISTS market_outcomes (
    outcome_id UUID PRIMARY KEY,
    decision_id UUID NOT NULL UNIQUE,
    resolved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    result TEXT NOT NULL CHECK (result IN ('WON', 'LOST', 'VOID', 'PUSH', 'UNREALIZED')),
    pnl NUMERIC(18,8),
    clv NUMERIC(18,8),
    calibration_bucket TEXT,
    detail_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS market_opportunities (
    opportunity_id UUID PRIMARY KEY,
    instrument_id UUID NOT NULL REFERENCES market_instruments(instrument_id),
    strategy_id UUID NOT NULL REFERENCES market_strategies(strategy_id),
    policy_id UUID NOT NULL REFERENCES market_risk_policies(policy_id),
    direction TEXT NOT NULL,
    horizon TEXT NOT NULL,
    thesis TEXT NOT NULL,
    counter_thesis TEXT,
    evidence_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    historical_analogs_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    gross_edge NUMERIC(18,8),
    net_edge NUMERIC(18,8),
    vig NUMERIC(18,8),
    spread NUMERIC(18,8),
    slippage NUMERIC(18,8),
    fees NUMERIC(18,8),
    other_costs NUMERIC(18,8),
    cost_estimate NUMERIC(18,8),
    confidence NUMERIC(8,6) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    expected_value NUMERIC(18,8),
    max_loss NUMERIC(18,8),
    data_quality NUMERIC(8,6) NOT NULL CHECK (data_quality >= 0 AND data_quality <= 1),
    data_quality_note TEXT,
    risk_tier TEXT NOT NULL CHECK (risk_tier IN ('CONSERVATIVE', 'CORE', 'AGGRESSIVE')),
    model_version TEXT,
    invalidation TEXT NOT NULL,
    provenance_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS market_decisions (
    decision_id UUID PRIMARY KEY,
    opportunity_id UUID REFERENCES market_opportunities(opportunity_id),
    strategy_id UUID NOT NULL REFERENCES market_strategies(strategy_id),
    policy_id UUID NOT NULL REFERENCES market_risk_policies(policy_id),
    decision_type TEXT NOT NULL CHECK (decision_type IN ('OPPORTUNITY', 'NO_ACTION')),
    reason_codes TEXT[] NOT NULL DEFAULT '{}'::text[],
    thesis TEXT NOT NULL,
    counter_thesis TEXT,
    confidence NUMERIC(8,6) CHECK (confidence >= 0 AND confidence <= 1),
    estimated_edge NUMERIC(18,8),
    cost_estimate NUMERIC(18,8),
    data_cutoff_timestamp TIMESTAMPTZ NOT NULL,
    invalidation TEXT,
    model_version TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    amendment_of UUID REFERENCES market_decisions(decision_id),
    outcome_id UUID REFERENCES market_outcomes(outcome_id),
    note TEXT
);

ALTER TABLE market_outcomes
    ADD CONSTRAINT market_outcomes_decision_fk
    FOREIGN KEY (decision_id) REFERENCES market_decisions(decision_id);

CREATE TABLE IF NOT EXISTS market_data_quality (
    quality_id UUID PRIMARY KEY,
    instrument_id UUID NOT NULL REFERENCES market_instruments(instrument_id),
    venue_key TEXT NOT NULL,
    score NUMERIC(8,6) NOT NULL CHECK (score >= 0 AND score <= 1),
    freshness_ok BOOLEAN NOT NULL,
    availability TEXT NOT NULL CHECK (availability IN ('AVAILABLE', 'STALE', 'UNAVAILABLE')),
    checks_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    as_of TIMESTAMPTZ NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_market_instrument_links_source
    ON market_instrument_links(source_desk, source_table, source_id);
CREATE INDEX IF NOT EXISTS idx_market_events_type_time
    ON market_events(event_type, event_time);
CREATE INDEX IF NOT EXISTS idx_market_impacts_instrument_window
    ON market_event_impacts(instrument_id, window_start, window_end);
CREATE INDEX IF NOT EXISTS idx_market_decisions_created
    ON market_decisions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_market_decisions_opportunity
    ON market_decisions(opportunity_id);
CREATE INDEX IF NOT EXISTS idx_market_quality_instrument_asof
    ON market_data_quality(instrument_id, as_of DESC);