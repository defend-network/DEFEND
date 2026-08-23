-- M4.7.1 result/settlement truth certification + arb observation lifecycle.
-- Additive only. Never modifies deployed 0018/0019.

-- First-class immutable result request evidence (P2). A per-event state may
-- only become PROVIDER_RESULT_REQUESTED_EMPTY when a request with this evidence
-- genuinely succeeded, the schema was understood, and the request scope
-- actually included that event.
CREATE TABLE IF NOT EXISTS quant_result_request_evidence (
    request_evidence_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    request_kind TEXT NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL,
    window_start TEXT,
    window_end TEXT,
    target_event_count BIGINT NOT NULL DEFAULT 0,
    http_status INTEGER,
    provider_request_status TEXT,
    response_schema_status TEXT NOT NULL DEFAULT 'UNKNOWN'
        CHECK (response_schema_status IN ('UNDERSTOOD', 'UNKNOWN', 'INVALID')),
    events_returned BIGINT NOT NULL DEFAULT 0,
    events_matched BIGINT NOT NULL DEFAULT 0,
    raw_payload_hash TEXT,
    error_class TEXT,
    successful_search_scope TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (request_id)
);
CREATE INDEX IF NOT EXISTS idx_quant_result_request_evidence_at
    ON quant_result_request_evidence(requested_at);

-- Market reference immutability (P18): a frozen official reference is never
-- overwritten by a later quote.
ALTER TABLE quant_market_reference
    ADD COLUMN IF NOT EXISTS frozen BOOLEAN NOT NULL DEFAULT TRUE;

-- Arb opportunity verification observations (P30): append-only survival
-- evidence, never destructively updates the original quote snapshot.
CREATE TABLE IF NOT EXISTS quant_arb_opportunity_verification (
    verification_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    opportunity_id TEXT NOT NULL,
    verified_at TIMESTAMPTZ NOT NULL,
    still_valid BOOLEAN NOT NULL,
    quote_age_seconds JSONB NOT NULL DEFAULT '{}'::jsonb,
    cross_book_delta_seconds NUMERIC(12,3),
    classification TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_quant_arb_verification_opp
    ON quant_arb_opportunity_verification(opportunity_id, verified_at);

-- Settlement revision provenance: preserve exact provider result identity and
-- observed timestamps so a revision never silently overwrites history (P11/P12).
ALTER TABLE quant_settlements
    ADD COLUMN IF NOT EXISTS provider_result_id TEXT;

-- Circuit breaker HALF_OPEN single-probe lease (P22): exactly one caller may
-- hold the probe lease at a time.
ALTER TABLE quant_provider_circuit_breaker
    ADD COLUMN IF NOT EXISTS probe_lease_until TIMESTAMPTZ;
