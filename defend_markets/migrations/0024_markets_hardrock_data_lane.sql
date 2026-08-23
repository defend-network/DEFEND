-- M4.8 Hard Rock FL first-class data lane. Additive only. Never modifies 1-23.

-- Point-in-time Hard Rock price-ladder snapshots (P4/P5). Every odds
-- observation records WHICH snapshot decoded its rootIdx and a later ladder
-- change never silently rewrites historical odds.
CREATE TABLE IF NOT EXISTS hardrock_ladder_snapshot (
    ladder_snapshot_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    data_provider TEXT NOT NULL,
    sportsbook TEXT NOT NULL,
    state TEXT NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL,
    raw_response_sha256 TEXT,
    canonical_response_sha256 TEXT,
    entry_count BIGINT NOT NULL DEFAULT 0,
    ladder_identity TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_hardrock_ladder_retrieved
    ON hardrock_ladder_snapshot(retrieved_at);

-- Ladder entry rows (rootIdx -> authoritative American odds). Append-only.
CREATE TABLE IF NOT EXISTS hardrock_ladder_entry (
    ladder_entry_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ladder_snapshot_id BIGINT NOT NULL REFERENCES hardrock_ladder_snapshot(ladder_snapshot_id) ON DELETE CASCADE,
    root_idx BIGINT NOT NULL,
    american_odds BIGINT NOT NULL,
    UNIQUE (ladder_snapshot_id, root_idx)
);
CREATE INDEX IF NOT EXISTS idx_hardrock_ladder_entry_idx
    ON hardrock_ladder_entry(ladder_snapshot_id, root_idx);

-- Hard Rock canonical quote observations (P6/P7). data_provider (owls_insight)
-- and sportsbook (hardrock_bet) are distinct and rootIdx + ladder_snapshot
-- linkage are preserved so the quote is PIT-safe.
CREATE TABLE IF NOT EXISTS hardrock_quote_observation (
    observation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    canonical_event_id TEXT NOT NULL,
    data_provider TEXT NOT NULL,
    sportsbook TEXT NOT NULL,
    state TEXT NOT NULL,
    provider_event_id TEXT NOT NULL,
    market_family TEXT NOT NULL,
    period TEXT NOT NULL,
    line TEXT,
    selection TEXT NOT NULL,
    selection_side TEXT NOT NULL,
    root_idx BIGINT NOT NULL,
    ladder_snapshot_id BIGINT NOT NULL REFERENCES hardrock_ladder_snapshot(ladder_snapshot_id),
    american_odds BIGINT NOT NULL,
    decimal_odds NUMERIC(12,6) NOT NULL,
    implied_probability NUMERIC(12,8),
    observed_at TIMESTAMPTZ NOT NULL,
    acquired_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_payload_hash TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider_event_id, market_family, period, line, selection_side, observed_at)
);
CREATE INDEX IF NOT EXISTS idx_hardrock_quote_canonical
    ON hardrock_quote_observation(canonical_event_id, market_family, period, observed_at);

-- Cross-provider canonical event matching evidence (P8). Never silent merge.
CREATE TABLE IF NOT EXISTS provider_event_mapping (
    mapping_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider TEXT NOT NULL,
    native_event_id TEXT NOT NULL,
    canonical_event_id TEXT,
    identity_mode TEXT NOT NULL
        CHECK (identity_mode IN ('KEY_EXACT', 'NAME_TIME_EXACT', 'AMBIGUOUS', 'CONFLICT', 'UNMATCHED')),
    confidence TEXT NOT NULL DEFAULT 'UNKNOWN',
    normalized_participants TEXT,
    competition TEXT,
    scheduled_time TIMESTAMPTZ,
    matched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider, native_event_id)
);
CREATE INDEX IF NOT EXISTS idx_provider_event_mapping_canonical
    ON provider_event_mapping(canonical_event_id);

-- Resumable historical backfill checkpoints (P16).
CREATE TABLE IF NOT EXISTS historical_backfill_checkpoint (
    checkpoint_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider TEXT NOT NULL,
    task TEXT NOT NULL,
    cursor_value TEXT,
    state TEXT NOT NULL DEFAULT 'RUNNING',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider, task)
);
