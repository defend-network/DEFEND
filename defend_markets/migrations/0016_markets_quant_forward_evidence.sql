-- M4.6 forward evidence engine: official frozen forward predictions, immutable
-- settlements with revisioning, and immutable forward scores. Additive only.

CREATE TABLE IF NOT EXISTS quant_official_forward_predictions (
    official_prediction_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    canonical_event_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    model_hash TEXT,
    prediction_id TEXT NOT NULL,
    prediction_role TEXT NOT NULL
        CHECK (prediction_role IN ('M5_FORWARD', 'SHADOW_FORWARD')),
    generated_at TIMESTAMPTZ NOT NULL,
    commence_at TIMESTAMPTZ NOT NULL,
    probability_a NUMERIC(10,6) NOT NULL,
    feature_snapshot_id TEXT,
    frozen_forward BOOLEAN NOT NULL DEFAULT TRUE,
    policy_version INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (canonical_event_id, model_id)
);

CREATE TABLE IF NOT EXISTS quant_settlements (
    settlement_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    canonical_event_id TEXT NOT NULL,
    provider_event_id TEXT,
    competition TEXT,
    participant_a TEXT,
    participant_b TEXT,
    status TEXT NOT NULL
        CHECK (status IN ('PENDING','PROVISIONAL','FINAL','VOID','CANCELLED','POSTPONED',
                          'ABANDONED','REVIEW_REQUIRED','SUPERSEDED')),
    actual_a NUMERIC(3,1),
    actual_b NUMERIC(3,1),
    winner_side TEXT,
    source_result_id TEXT,
    source_provider TEXT,
    observed_at TIMESTAMPTZ,
    raw_payload_hash TEXT,
    orientation_verified BOOLEAN NOT NULL DEFAULT FALSE,
    revision BIGINT NOT NULL DEFAULT 1,
    supersedes_revision_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (canonical_event_id, source_result_id)
);

CREATE TABLE IF NOT EXISTS quant_forward_scores (
    score_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    canonical_event_id TEXT NOT NULL,
    official_prediction_id BIGINT NOT NULL REFERENCES quant_official_forward_predictions(official_prediction_id) ON DELETE CASCADE,
    model_id TEXT NOT NULL,
    settlement_id BIGINT NOT NULL REFERENCES quant_settlements(settlement_id),
    probability_a NUMERIC(10,6) NOT NULL,
    actual_outcome NUMERIC(3,1) NOT NULL,
    brier NUMERIC(12,8) NOT NULL,
    logloss NUMERIC(12,8) NOT NULL,
    logloss_eps_policy TEXT NOT NULL DEFAULT 'LOGLOSS_EPSILON_POLICY_V1',
    effective_clipped_p NUMERIC(10,6),
    scoring_policy_version INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (canonical_event_id, model_id, settlement_id)
);
