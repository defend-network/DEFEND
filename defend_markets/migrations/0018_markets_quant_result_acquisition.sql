-- M4.7 result acquisition truth, market reference policy, provider circuit
-- breaker and request quota governor. Additive only. Do not modify historical
-- M4.4-M4.6 evidence tables.

-- Per-event result acquisition ledger: separates LOCAL_RESULT_MISSING from a
-- genuine EXTERNAL_PROVIDER_EMPTY classification. A row moves through precise
-- acquisition states as evidence is gathered from the provider.
CREATE TABLE IF NOT EXISTS quant_result_acquisition (
    acquisition_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    canonical_event_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_event_id TEXT,
    commence_at TIMESTAMPTZ,
    acquisition_state TEXT NOT NULL CHECK (acquisition_state IN (
        'LOCAL_RESULT_PRESENT',
        'LOCAL_RESULT_MISSING_NOT_REQUESTED',
        'PROVIDER_RESULT_REQUESTED_EMPTY',
        'PROVIDER_RESULT_AVAILABLE',
        'PROVIDER_RESULT_ERROR',
        'PROVIDER_RESULT_SCHEMA_UNKNOWN',
        'PROVIDER_EVENT_NOT_FOUND',
        'PROVIDER_EVENT_IDENTITY_MISMATCH',
        'RESULT_RECONCILIATION_REQUIRED'
    )),
    result_status TEXT,
    actual_a NUMERIC(6,1),
    actual_b NUMERIC(6,1),
    winner_side TEXT,
    orientation TEXT CHECK (orientation IN ('CANONICAL', 'REVERSED', 'CONFLICT', NULL)),
    raw_provenance_hash TEXT,
    evidence_ref TEXT,
    request_count BIGINT NOT NULL DEFAULT 0,
    last_requested_at TIMESTAMPTZ,
    next_poll_at TIMESTAMPTZ,
    last_error TEXT,
    settled BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (canonical_event_id)
);

CREATE TABLE IF NOT EXISTS quant_result_request_ledger (
    ledger_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider TEXT NOT NULL,
    request_kind TEXT NOT NULL,
    events_requested BIGINT NOT NULL DEFAULT 0,
    events_returned BIGINT NOT NULL DEFAULT 0,
    status_code INTEGER,
    ok BOOLEAN NOT NULL,
    error TEXT,
    cost_estimate NUMERIC(14,6),
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_quant_result_request_ledger_at
    ON quant_result_request_ledger(observed_at);

-- MARKET_REFERENCE_POLICY_V1: deterministic point-in-time bookmaker price
-- reference for a canonical event selected before a versioned pre-match cutoff.
CREATE TABLE IF NOT EXISTS quant_market_reference (
    reference_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    canonical_event_id TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    market TEXT NOT NULL,
    side TEXT NOT NULL,
    bookmaker TEXT NOT NULL,
    price NUMERIC(12,6) NOT NULL,
    observation_id BIGINT,
    referenced_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (canonical_event_id, policy_version, market, side)
);
CREATE INDEX IF NOT EXISTS idx_quant_market_reference_event
    ON quant_market_reference(canonical_event_id, policy_version);

-- Provider circuit breaker state, versioned per provider/function.
CREATE TABLE IF NOT EXISTS quant_provider_circuit_breaker (
    circuit_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider TEXT NOT NULL,
    function_name TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('CLOSED', 'OPEN', 'HALF_OPEN', 'OPEN_CONFIGURATION')),
    consecutive_failures BIGINT NOT NULL DEFAULT 0,
    opened_at TIMESTAMPTZ,
    cooldown_until TIMESTAMPTZ,
    last_error TEXT,
    policy_version TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider, function_name)
);

-- Request quota governor: explicit budget accounting per request class.
CREATE TABLE IF NOT EXISTS quant_request_quota (
    quota_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    period_start TIMESTAMPTZ NOT NULL,
    request_class TEXT NOT NULL CHECK (request_class IN (
        'EVENT_DISCOVERY', 'ODDS', 'ATTESTATION', 'RESULT', 'HEALTH', 'RECONCILIATION'
    )),
    reserved BIGINT NOT NULL DEFAULT 0,
    used BIGINT NOT NULL DEFAULT 0,
    budget BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (period_start, request_class)
);
