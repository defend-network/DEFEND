-- M4.7.2 final production truth convergence. Additive only. Never modifies
-- deployed 0018/0019/0020.

-- Provider-wide shared operational capacity (P9/P10). A single atomic store of
-- total budget + protected RESULT/ODDS reserves, so low-priority classes
-- (ATTESTATION/HEALTH/RECONCILIATION) cannot consume protected capacity.
CREATE TABLE IF NOT EXISTS quant_provider_capacity (
    capacity_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider TEXT NOT NULL,
    period_start TIMESTAMPTZ NOT NULL,
    total_budget BIGINT NOT NULL DEFAULT 0,
    used BIGINT NOT NULL DEFAULT 0,
    reserved_result BIGINT NOT NULL DEFAULT 0,
    reserved_odds BIGINT NOT NULL DEFAULT 0,
    policy_version TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider, period_start)
);

-- Per-HTTP governance ledger (P5-P8): every external provider HTTP attempt is
-- reserved, classified and accounted independently. Distinguishes blocked
-- reservations (not consumed) from transmitted attempts (consumed).
CREATE TABLE IF NOT EXISTS quant_http_governance (
    governance_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider TEXT NOT NULL,
    request_class TEXT NOT NULL,
    operation TEXT NOT NULL,
    reserved_at TIMESTAMPTZ,
    attempted_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    blocked_before_send BOOLEAN NOT NULL DEFAULT FALSE,
    http_status INTEGER,
    outcome_class TEXT,
    consumed BOOLEAN NOT NULL DEFAULT FALSE,
    request_evidence_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_quant_http_governance_at
    ON quant_http_governance(attempted_at);

-- Arb conceptual series identity (P25): stable identity for the SAME cross-book
-- market condition, independent of changing odds/quote IDs/timestamps.
CREATE TABLE IF NOT EXISTS quant_arb_series (
    series_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    arb_series_key TEXT NOT NULL UNIQUE,
    canonical_event_id TEXT NOT NULL,
    market_family TEXT NOT NULL,
    period TEXT NOT NULL,
    line TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'CLOSED', 'EXPIRED')),
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_quant_arb_series_event
    ON quant_arb_series(canonical_event_id);

-- Arb series episodes (P28): disappearance then re-entry is NOT continuous
-- survival and each episode has its own first/last/invalidated/reopened timeline.
CREATE TABLE IF NOT EXISTS quant_arb_series_episode (
    episode_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    series_id BIGINT NOT NULL REFERENCES quant_arb_series(series_id) ON DELETE CASCADE,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    invalidated_at TIMESTAMPTZ,
    reopened_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'OPEN'
        CHECK (status IN ('OPEN', 'CLOSED', 'INVALIDATED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_quant_arb_episode_series
    ON quant_arb_series_episode(series_id);

-- Arb verification observations (P26/P27): append-only survival evidence with
-- stable series identity. Immutable detections remain in quant_arb_opportunities.
ALTER TABLE quant_arb_opportunity_verification
    ADD COLUMN IF NOT EXISTS arb_series_key TEXT;
ALTER TABLE quant_arb_opportunity_verification
    ADD COLUMN IF NOT EXISTS episode_id BIGINT;
ALTER TABLE quant_arb_opportunity_verification
    ADD COLUMN IF NOT EXISTS current_quote_ids JSONB;
ALTER TABLE quant_arb_opportunity_verification
    ADD COLUMN IF NOT EXISTS current_odds JSONB;
ALTER TABLE quant_arb_opportunity_verification
    ADD COLUMN IF NOT EXISTS margin NUMERIC(20,12);

-- Odds snapshot identity (P22): both sides of a frozen market reference must
-- originate from the SAME provider poll/batch.
CREATE TABLE IF NOT EXISTS quant_odds_snapshot (
    snapshot_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider TEXT NOT NULL,
    poll_id TEXT,
    ingestion_batch_id TEXT,
    request_id TEXT,
    observed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider, poll_id)
);

-- Market reference pair identity (P24): both sides frozen together.
ALTER TABLE quant_market_reference
    ADD COLUMN IF NOT EXISTS reference_pair_id TEXT;
ALTER TABLE quant_market_reference
    ADD COLUMN IF NOT EXISTS snapshot_id TEXT;

-- Result reconciliation (P16): recently-FINAL events remain eligible for a
-- finite correction window.
ALTER TABLE quant_result_acquisition
    ADD COLUMN IF NOT EXISTS last_reconciled_at TIMESTAMPTZ;
ALTER TABLE quant_result_acquisition
    ADD COLUMN IF NOT EXISTS next_reconcile_at TIMESTAMPTZ;
ALTER TABLE quant_result_acquisition
    ADD COLUMN IF NOT EXISTS reconciliation_attempt_count BIGINT NOT NULL DEFAULT 0;
ALTER TABLE quant_result_acquisition
    ADD COLUMN IF NOT EXISTS normalized_result_fingerprint TEXT;

-- Raw response hash semantics (P35): raw-response SHA256 vs canonical JSON SHA.
ALTER TABLE quant_result_request_evidence
    ADD COLUMN IF NOT EXISTS raw_response_sha256 TEXT;
ALTER TABLE quant_result_request_evidence
    ADD COLUMN IF NOT EXISTS canonical_response_sha256 TEXT;
