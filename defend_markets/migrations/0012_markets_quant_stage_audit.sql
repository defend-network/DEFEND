-- Promotion/stage audit trail: every model-stage transition records
-- provenance (gates, deltas, actor, reason, code commit).

CREATE TABLE IF NOT EXISTS quant_stage_audit (
    audit_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    model_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    from_stage TEXT,
    to_stage TEXT NOT NULL,
    experiment_id TEXT,
    gate_version INTEGER,
    gate_results JSONB NOT NULL DEFAULT '{}'::jsonb,
    metric_deltas JSONB NOT NULL DEFAULT '{}'::jsonb,
    actor TEXT NOT NULL,
    reason TEXT,
    code_commit TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
