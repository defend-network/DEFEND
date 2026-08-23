-- M4.3: parallel shadow predictions and the paper/pass ledger.

CREATE TABLE IF NOT EXISTS quant_shadow_predictions (
    shadow_prediction_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    canonical_event_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    feature_snapshot_id TEXT NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL,
    p_a NUMERIC(10,6) NOT NULL,
    availability TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (canonical_event_id, model_id, model_version)
);

CREATE TABLE IF NOT EXISTS quant_paper_ledger (
    entry_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    canonical_event_id TEXT NOT NULL,
    provider_event_id TEXT,
    decision TEXT NOT NULL
        CHECK (decision IN ('PAPER_DECISION', 'PASS')),
    reason TEXT NOT NULL,
    model_p_a NUMERIC(10,6),
    market_p_a NUMERIC(10,6),
    bookmaker TEXT,
    price NUMERIC(12,6),
    observation_id BIGINT,
    model_id TEXT,
    model_version TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (canonical_event_id)
);
