-- Router integration V1: per-run model routing + persisted escalation
-- proposals. Additive and nullable-defaulted so existing run records are
-- preserved. No secret material is stored in either table.

ALTER TABLE coder_runs
    ADD COLUMN requested_mode TEXT NOT NULL DEFAULT 'AUTO';

ALTER TABLE coder_runs
    ADD COLUMN selected_tier TEXT NOT NULL DEFAULT 'DEEPSEEK';

ALTER TABLE coder_runs
    ADD COLUMN selected_model TEXT NOT NULL DEFAULT 'deepseek';

ALTER TABLE coder_runs
    ADD COLUMN selected_provider TEXT;

ALTER TABLE coder_runs
    ADD COLUMN route_reason TEXT;

ALTER TABLE coder_runs
    ADD COLUMN escalated_from TEXT;

ALTER TABLE coder_runs
    ADD COLUMN escalation_approved_at TIMESTAMPTZ;

ALTER TABLE coder_runs
    ADD COLUMN escalation_approved_by TEXT;

CREATE TABLE IF NOT EXISTS coder_escalation_proposals (
    proposal_id TEXT PRIMARY KEY,
    run_id UUID NOT NULL
        REFERENCES coder_runs(run_id)
        ON DELETE CASCADE,
    from_model TEXT NOT NULL,
    to_model TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    human_summary TEXT NOT NULL,
    evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    tests_failed INTEGER NOT NULL DEFAULT 0,
    estimated_incremental_cost TEXT,
    target_runtime_state TEXT NOT NULL,
    requires_gpu_resume BOOLEAN NOT NULL DEFAULT FALSE,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    approved_at TIMESTAMPTZ,
    approved_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_coder_escalation_proposals_run
    ON coder_escalation_proposals(run_id, created_at DESC);
