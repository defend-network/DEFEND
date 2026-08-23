-- M4.4 active improvement engine + paper model correction.
-- New tables are additive. Existing quant_paper_ledger (first-decision-stands)
-- is preserved as LEGACY_DECISION_EVENT provenance and nothing is dropped.

CREATE TABLE IF NOT EXISTS quant_weaknesses (
    weakness_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    weakness_type TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'DETECTED'
        CHECK (status IN ('DETECTED','VALIDATING','ACTIONABLE','RESEARCHING','EXPERIMENTING',
                          'PATCHING','MONITORING','RESOLVED','REJECTED','BLOCKED','REOPENED')),
    severity TEXT NOT NULL DEFAULT 'LOW'
        CHECK (severity IN ('LOW','MEDIUM','HIGH','CRITICAL')),
    confidence TEXT NOT NULL DEFAULT 'EARLY_SIGNAL'
        CHECK (confidence IN ('EARLY_SIGNAL','SUPPORTED','STRONG')),
    progress_impact TEXT,
    first_detected_at TIMESTAMPTZ NOT NULL,
    last_observed_at TIMESTAMPTZ NOT NULL,
    evidence_count BIGINT NOT NULL DEFAULT 0,
    sample_size BIGINT NOT NULL DEFAULT 0,
    affected_scope TEXT,
    affected_competition TEXT,
    affected_players TEXT,
    affected_market TEXT,
    affected_model TEXT,
    blocking_capability TEXT,
    root_cause_state TEXT,
    recommended_action_type TEXT,
    auto_action_allowed BOOLEAN NOT NULL DEFAULT FALSE,
    priority_score NUMERIC(10,4),
    state_hash TEXT NOT NULL,
    prior_resolution TEXT,
    reopened_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (weakness_type, state_hash)
);

CREATE TABLE IF NOT EXISTS quant_weakness_evidence (
    evidence_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    weakness_id BIGINT NOT NULL REFERENCES quant_weaknesses(weakness_id) ON DELETE CASCADE,
    evidence_type TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value NUMERIC(18,8),
    sample_size BIGINT,
    comparison_value NUMERIC(18,8),
    time_window TEXT,
    competition TEXT,
    model TEXT,
    market TEXT,
    source_ref TEXT,
    observed_at TIMESTAMPTZ NOT NULL,
    payload_hash TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS quant_improvement_actions (
    action_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    weakness_id BIGINT NOT NULL REFERENCES quant_weaknesses(weakness_id) ON DELETE CASCADE,
    action_type TEXT NOT NULL,
    description TEXT,
    expected_effect TEXT,
    status TEXT NOT NULL DEFAULT 'PROPOSED'
        CHECK (status IN ('PROPOSED','STARTED','COMPLETED','FAILED','REJECTED','MONITORING')),
    risk TEXT,
    estimated_cost TEXT,
    requires_owner BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    verification_metric TEXT,
    baseline_value NUMERIC(18,8),
    result_value NUMERIC(18,8),
    outcome TEXT
);

CREATE TABLE IF NOT EXISTS quant_knowledge_findings (
    finding_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    research_task_id TEXT,
    weakness_id BIGINT,
    claim TEXT NOT NULL,
    source TEXT,
    source_type TEXT,
    retrieved_at TIMESTAMPTZ NOT NULL,
    confidence TEXT NOT NULL DEFAULT 'EARLY_SIGNAL',
    scope TEXT,
    valid_from TEXT,
    valid_until TEXT,
    point_in_time_safe BOOLEAN NOT NULL DEFAULT FALSE,
    approved_for_feature_use BOOLEAN NOT NULL DEFAULT FALSE,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS quant_repair_packets (
    packet_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    weakness_id BIGINT,
    symptom TEXT NOT NULL,
    reproduction TEXT,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    suspected_boundary TEXT,
    failing_invariant TEXT,
    expected_behavior TEXT,
    suggested_test TEXT,
    likely_files JSONB NOT NULL DEFAULT '[]'::jsonb,
    risk TEXT,
    acceptance_criteria TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING','IN_REVIEW','PATCH_READY_FOR_REVIEW','REJECTED','RESOLVED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Corrected paper model: immutable decision evaluations (append-only) and
-- immutable committed paper tickets, separated by model/strategy.
CREATE TABLE IF NOT EXISTS quant_decision_evaluations (
    evaluation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    canonical_event_id TEXT NOT NULL,
    provider_event_id TEXT,
    model_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    strategy TEXT NOT NULL,
    decision TEXT NOT NULL
        CHECK (decision IN ('PAPER_DECISION','PASS')),
    reason TEXT NOT NULL,
    decision_ts TIMESTAMPTZ NOT NULL,
    model_p_a NUMERIC(10,6),
    market_p_a NUMERIC(10,6),
    bookmaker TEXT,
    price NUMERIC(12,6),
    observation_id BIGINT,
    feature_snapshot_id TEXT,
    legacy_ledger_entry_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_quant_decision_evaluations_event
    ON quant_decision_evaluations(canonical_event_id, model_id, decision_ts);

CREATE TABLE IF NOT EXISTS quant_paper_tickets (
    ticket_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    canonical_event_id TEXT NOT NULL,
    provider_event_id TEXT,
    strategy TEXT NOT NULL,
    model_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    side TEXT NOT NULL,
    selection TEXT,
    price NUMERIC(12,6) NOT NULL,
    stake NUMERIC(12,6),
    model_p_a NUMERIC(10,6),
    market_p_a NUMERIC(10,6),
    market_observation_id BIGINT,
    feature_snapshot_id TEXT,
    decision_ts TIMESTAMPTZ NOT NULL,
    committed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    result_actual NUMERIC(3,1),
    paper_pnl NUMERIC(12,6),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (canonical_event_id, strategy, model_id, decision_ts)
);
