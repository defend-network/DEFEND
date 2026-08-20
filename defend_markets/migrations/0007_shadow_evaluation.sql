-- Phase D shadow settlement and evaluation increments. Evaluation rows are
-- keyed by (canonical_event_id, result_id, reference_class) so incremental
-- settlement is idempotent. Soak runs are append-only.

CREATE TABLE IF NOT EXISTS tt_shadow_evaluation (
    entry_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    canonical_event_id TEXT NOT NULL,
    result_id BIGINT NOT NULL,
    settled_at TIMESTAMPTZ NOT NULL,
    model_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    reference_class TEXT NOT NULL
        CHECK (reference_class IN ('OPEN', 'INTERMEDIATE', 'LAST_VALID_PREMATCH')),
    m5_p_a NUMERIC(10,6) NOT NULL,
    market_no_vig_p_a NUMERIC(10,6),
    m5_brier NUMERIC(10,8),
    market_brier NUMERIC(10,8),
    m5_log_loss NUMERIC(12,8),
    market_log_loss NUMERIC(12,8),
    m5_minus_market_brier NUMERIC(12,8),
    actual NUMERIC(3,1) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (canonical_event_id, result_id, reference_class)
);
CREATE INDEX IF NOT EXISTS idx_tt_shadow_evaluation_class
    ON tt_shadow_evaluation(reference_class, settled_at);

CREATE TABLE IF NOT EXISTS tt_shadow_soak_runs (
    run_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'RUNNING',
    cycle_count BIGINT NOT NULL DEFAULT 0,
    api_requests BIGINT NOT NULL DEFAULT 0,
    api_errors BIGINT NOT NULL DEFAULT 0,
    rate_limit_events BIGINT NOT NULL DEFAULT 0,
    cost_usd NUMERIC(12,6) NOT NULL DEFAULT 0,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb
);