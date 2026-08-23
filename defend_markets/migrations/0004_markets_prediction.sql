CREATE TABLE IF NOT EXISTS tt_participants (
    participant_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE,
    identity_state TEXT NOT NULL DEFAULT 'NORMALIZED'
        CHECK (identity_state IN ('CONFIRMED', 'NORMALIZED', 'AMBIGUOUS', 'UNRESOLVED')),
    first_seen TIMESTAMPTZ NOT NULL,
    last_seen TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tt_participant_aliases (
    alias_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    participant_id BIGINT NOT NULL REFERENCES tt_participants(participant_id) ON DELETE CASCADE,
    alias_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    provider TEXT NOT NULL,
    raw_ref TEXT,
    first_seen TIMESTAMPTZ NOT NULL,
    last_seen TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (participant_id, normalized_name, provider)
);

CREATE TABLE IF NOT EXISTS tt_collector_state (
    collector_key TEXT PRIMARY KEY,
    last_cycle_at TIMESTAMPTZ,
    last_scores_poll_at TIMESTAMPTZ,
    last_odds_poll_at TIMESTAMPTZ,
    next_odds_poll_at TIMESTAMPTZ,
    odds_interval_seconds BIGINT,
    quota_status TEXT,
    last_quota_remaining BIGINT,
    last_quota_used BIGINT,
    last_quota_last TEXT,
    last_error TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tt_feature_snapshots (
    snapshot_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_key TEXT NOT NULL,
    prediction_ts TIMESTAMPTZ NOT NULL,
    feature_schema_version INTEGER NOT NULL,
    feature_code_version TEXT NOT NULL,
    source_observation_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tt_feature_snapshots_event
    ON tt_feature_snapshots(event_key, prediction_ts);

CREATE TABLE IF NOT EXISTS tt_predictions (
    prediction_id UUID PRIMARY KEY,
    created_ts TIMESTAMPTZ NOT NULL,
    event_key TEXT NOT NULL,
    provider_event_id TEXT,
    sport_key TEXT NOT NULL,
    player_a_id BIGINT REFERENCES tt_participants(participant_id),
    player_b_id BIGINT REFERENCES tt_participants(participant_id),
    player_a_name_at_prediction TEXT NOT NULL,
    player_b_name_at_prediction TEXT NOT NULL,
    feature_snapshot_id BIGINT REFERENCES tt_feature_snapshots(snapshot_id),
    market_method_version TEXT NOT NULL,
    market_p_a NUMERIC(18,10),
    market_p_b NUMERIC(18,10),
    best_price_a NUMERIC(18,6),
    best_price_b NUMERIC(18,6),
    consensus_p_a NUMERIC(18,10),
    consensus_p_b NUMERIC(18,10),
    overround NUMERIC(18,10),
    book_count INTEGER,
    model_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    model_p_a NUMERIC(18,10),
    model_p_b NUMERIC(18,10),
    model_uncertainty NUMERIC(18,10),
    edge_gross NUMERIC(18,10),
    edge_net NUMERIC(18,10),
    cost_model_version TEXT,
    data_age_seconds NUMERIC(18,6),
    provider_health TEXT,
    identity_state TEXT,
    strategy_id TEXT NOT NULL,
    strategy_version INTEGER NOT NULL,
    strategy_lifecycle TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('OPPORTUNITY', 'NO_ACTION')),
    reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    risk_policy_version INTEGER NOT NULL,
    journal_ref UUID REFERENCES market_decisions(decision_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tt_predictions_event
    ON tt_predictions(event_key, created_ts);
CREATE INDEX IF NOT EXISTS idx_tt_predictions_created
    ON tt_predictions(created_ts DESC);

CREATE TABLE IF NOT EXISTS tt_prediction_amendments (
    amendment_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    prediction_id UUID NOT NULL REFERENCES tt_predictions(prediction_id) ON DELETE CASCADE,
    amended_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    reason TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS tt_settlements (
    settlement_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    prediction_id UUID NOT NULL REFERENCES tt_predictions(prediction_id) ON DELETE CASCADE,
    source_raw_ref TEXT NOT NULL,
    settlement_ts TIMESTAMPTZ NOT NULL,
    winner_participant_key TEXT NOT NULL,
    correct BOOLEAN NOT NULL,
    residual NUMERIC(18,10),
    paper_stake NUMERIC(18,8),
    paper_pnl_gross NUMERIC(18,8),
    paper_costs NUMERIC(18,8),
    paper_pnl_net NUMERIC(18,8),
    closing_market_p NUMERIC(18,10),
    closing_best_price NUMERIC(18,6),
    clv NUMERIC(18,10),
    settled_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (prediction_id, source_raw_ref)
);
CREATE INDEX IF NOT EXISTS idx_tt_settlements_prediction
    ON tt_settlements(prediction_id);

CREATE TABLE IF NOT EXISTS tt_shadow_predictions (
    shadow_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    prediction_id UUID REFERENCES tt_predictions(prediction_id),
    event_key TEXT NOT NULL,
    created_ts TIMESTAMPTZ NOT NULL,
    market_p_a NUMERIC(18,10),
    market_p_b NUMERIC(18,10),
    elo_p_a NUMERIC(18,10),
    elo_p_b NUMERIC(18,10),
    naive_form_p_a NUMERIC(18,10),
    naive_form_p_b NUMERIC(18,10),
    model_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    strategy_version INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tt_shadow_event
    ON tt_shadow_predictions(event_key, created_ts);

CREATE TABLE IF NOT EXISTS tt_research_ledger (
    entry_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    hypothesis TEXT NOT NULL,
    change TEXT NOT NULL,
    expected_mechanism TEXT NOT NULL,
    model_id TEXT,
    model_version TEXT,
    strategy_id TEXT,
    strategy_version INTEGER,
    evaluation_period TEXT,
    results JSONB NOT NULL DEFAULT '{}'::jsonb,
    decision TEXT NOT NULL CHECK (decision IN ('KEEP', 'REJECT', 'RETEST')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);