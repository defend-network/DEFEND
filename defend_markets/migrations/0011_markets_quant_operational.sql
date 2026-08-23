-- M4 operational quant supervisor: scheduler jobs + leases, trigger ledger,
-- evaluation/error/metrics, result corrections, AI call ledger, and the
-- source-labeled hypothesis registry. Additive and idempotent.

CREATE TABLE IF NOT EXISTS quant_scheduler_jobs (
    job_name TEXT PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    schedule_interval_seconds BIGINT NOT NULL,
    last_started_at TIMESTAMPTZ,
    last_completed_at TIMESTAMPTZ,
    next_run_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'IDLE'
        CHECK (status IN ('IDLE', 'RUNNING', 'COMPLETED', 'FAILED')),
    last_result_summary TEXT,
    last_error TEXT,
    last_state_hash TEXT,
    lease_owner TEXT,
    lease_expires_at TIMESTAMPTZ,
    attempt_count BIGINT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS quant_trigger_events (
    trigger_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trigger_type TEXT NOT NULL,
    severity TEXT NOT NULL
        CHECK (severity IN ('INFO', 'REVIEW', 'IMPORTANT', 'CRITICAL')),
    trigger_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    state_hash TEXT NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    last_invoked_at TIMESTAMPTZ,
    invocation_result TEXT,
    suppressed_count BIGINT NOT NULL DEFAULT 0,
    UNIQUE (trigger_type, state_hash)
);

CREATE TABLE IF NOT EXISTS quant_evaluations (
    evaluation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    prediction_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    prediction_ts TIMESTAMPTZ NOT NULL,
    predicted_probability NUMERIC(10,6) NOT NULL,
    actual NUMERIC(3,1) NOT NULL,
    outcome_version TEXT NOT NULL,
    brier_contribution NUMERIC(12,8),
    logloss_contribution NUMERIC(12,8),
    abs_probability_error NUMERIC(10,6),
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'SUPERSEDED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (prediction_id, event_id, model_id, model_version, prediction_ts, outcome_version)
);

CREATE TABLE IF NOT EXISTS quant_result_corrections (
    correction_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id TEXT NOT NULL,
    evaluation_id BIGINT NOT NULL REFERENCES quant_evaluations(evaluation_id),
    previous_actual NUMERIC(3,1) NOT NULL,
    new_actual NUMERIC(3,1) NOT NULL,
    source TEXT NOT NULL,
    corrected_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS quant_prediction_errors (
    error_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    evaluation_id BIGINT NOT NULL UNIQUE REFERENCES quant_evaluations(evaluation_id) ON DELETE CASCADE,
    event_id TEXT NOT NULL,
    prediction_id TEXT NOT NULL,
    prediction_ts TIMESTAMPTZ NOT NULL,
    model_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    predicted_probability NUMERIC(10,6) NOT NULL,
    predicted_side TEXT,
    actual NUMERIC(3,1) NOT NULL,
    abs_probability_error NUMERIC(10,6) NOT NULL,
    brier_contribution NUMERIC(12,8) NOT NULL,
    logloss_contribution NUMERIC(12,8) NOT NULL,
    confidence_band TEXT,
    feature_vector_ref TEXT,
    history_depth_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    league TEXT,
    market_data_available BOOLEAN,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS quant_metric_snapshots (
    snapshot_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    metric_calculation_version TEXT NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL,
    state_hash TEXT NOT NULL,
    brier NUMERIC(12,8),
    log_loss NUMERIC(12,8),
    ece NUMERIC(12,8),
    evaluation_rows BIGINT NOT NULL,
    drift_state TEXT NOT NULL,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS quant_ai_calls (
    call_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trigger_type TEXT,
    state_hash TEXT,
    profile_alias TEXT NOT NULL,
    actual_provider TEXT NOT NULL,
    actual_model TEXT NOT NULL,
    reason_for_route TEXT,
    input_tokens BIGINT,
    cached_input_tokens BIGINT,
    output_tokens BIGINT,
    estimated_cost_usd NUMERIC(12,8) NOT NULL DEFAULT 0,
    latency_ms BIGINT,
    retry_count BIGINT NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS quant_hypotheses (
    hypothesis_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source TEXT NOT NULL
        CHECK (source IN ('SEED', 'DATA_DERIVED', 'OWNER_PROPOSED', 'AI_PROPOSED')),
    title TEXT NOT NULL,
    supporting_observation TEXT,
    status TEXT NOT NULL DEFAULT 'PROPOSED'
        CHECK (status IN ('PROPOSED', 'ACTIVE', 'COMPLETED', 'REJECTED', 'BLOCKED')),
    rejection_reason TEXT,
    dependencies JSONB NOT NULL DEFAULT '[]'::jsonb,
    data_requirements TEXT,
    last_evaluated_at TIMESTAMPTZ,
    priority_score NUMERIC(10,4),
    priority_breakdown JSONB NOT NULL DEFAULT '{}'::jsonb,
    blocked_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (title, source)
);
