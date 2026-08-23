-- M4.5 commercial-grade truth: windowed bookmaker coverage evidence plus
-- additive integrity constraints. Nothing is dropped.

CREATE TABLE IF NOT EXISTS quant_bookmaker_coverage (
    coverage_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bookmaker_id TEXT NOT NULL,
    sport_slug TEXT NOT NULL,
    attestation_state TEXT NOT NULL
        CHECK (attestation_state IN ('AVAILABLE','PARTIAL_CURRENT_COVERAGE','ZERO_CURRENT_COVERAGE',
                                     'UNKNOWN','NOT_SELECTED','PROVIDER_ERROR')),
    selected BOOLEAN NOT NULL DEFAULT FALSE,
    filtered_events BIGINT NOT NULL DEFAULT 0,
    pending_events BIGINT NOT NULL DEFAULT 0,
    live_events BIGINT NOT NULL DEFAULT 0,
    priced_events BIGINT NOT NULL DEFAULT 0,
    observations BIGINT NOT NULL DEFAULT 0,
    competitions JSONB NOT NULL DEFAULT '{}'::jsonb,
    market_types JSONB NOT NULL DEFAULT '[]'::jsonb,
    coverage_window_start TIMESTAMPTZ NOT NULL,
    coverage_window_end TIMESTAMPTZ NOT NULL,
    first_observation_at TIMESTAMPTZ,
    last_observation_at TIMESTAMPTZ,
    last_attested_at TIMESTAMPTZ NOT NULL,
    error_state TEXT,
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_quant_bookmaker_coverage_book
    ON quant_bookmaker_coverage(bookmaker_id, last_attested_at DESC);

ALTER TABLE tt_market_observations
    DROP CONSTRAINT IF EXISTS tt_market_observations_price_positive;
ALTER TABLE tt_market_observations
    ADD CONSTRAINT tt_market_observations_price_positive CHECK (price > 1);

ALTER TABLE quant_paper_tickets
    DROP CONSTRAINT IF EXISTS quant_paper_tickets_identity_not_null;
ALTER TABLE quant_paper_tickets
    ADD CONSTRAINT quant_paper_tickets_identity_not_null
    CHECK (canonical_event_id IS NOT NULL AND strategy IS NOT NULL AND model_id IS NOT NULL);
