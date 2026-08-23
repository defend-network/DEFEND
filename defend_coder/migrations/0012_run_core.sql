-- Durable run-core tables (additive). Immutable snapshots for restart
-- reconstruction. No secrets; no raw hidden reasoning.

CREATE TABLE IF NOT EXISTS coder_run_execution_envelopes (
    run_id UUID PRIMARY KEY
        REFERENCES coder_runs(run_id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL,
    owner_account_id UUID NOT NULL,
    requested_mode TEXT NOT NULL,
    selected_tier TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    identity_profile_id TEXT NOT NULL,
    identity_version TEXT NOT NULL,
    identity_hash TEXT NOT NULL,
    prompt_core_id TEXT NOT NULL,
    prompt_core_version TEXT NOT NULL,
    prompt_core_hash TEXT NOT NULL,
    technical_profile_id TEXT NOT NULL,
    technical_profile_version TEXT NOT NULL,
    technical_profile_hash TEXT NOT NULL,
    initial_checkpoint_revision INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS coder_run_route_history (
    run_id UUID NOT NULL
        REFERENCES coder_runs(run_id) ON DELETE CASCADE,
    revision INTEGER NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    technical_profile_id TEXT NOT NULL,
    technical_profile_version TEXT NOT NULL,
    technical_profile_hash TEXT NOT NULL,
    requested_mode TEXT NOT NULL,
    reason TEXT,
    approval_id TEXT,
    approved_by TEXT,
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, revision)
);

CREATE TABLE IF NOT EXISTS coder_run_checkpoints (
    checkpoint_id UUID PRIMARY KEY,
    run_id UUID NOT NULL
        REFERENCES coder_runs(run_id) ON DELETE CASCADE,
    revision INTEGER NOT NULL,
    objective TEXT NOT NULL,
    current_task TEXT,
    completed_work JSONB NOT NULL DEFAULT '[]'::jsonb,
    current_failure TEXT,
    relevant_files JSONB NOT NULL DEFAULT '[]'::jsonb,
    latest_tests JSONB NOT NULL DEFAULT '[]'::jsonb,
    constraints JSONB NOT NULL DEFAULT '[]'::jsonb,
    next_action TEXT,
    branch TEXT,
    head TEXT,
    dirty_files JSONB NOT NULL DEFAULT '[]'::jsonb,
    identity_profile_id TEXT NOT NULL,
    identity_version TEXT NOT NULL,
    identity_hash TEXT NOT NULL,
    prompt_core_id TEXT NOT NULL,
    prompt_core_version TEXT NOT NULL,
    prompt_core_hash TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    technical_profile_id TEXT NOT NULL,
    technical_profile_version TEXT NOT NULL,
    technical_profile_hash TEXT NOT NULL,
    pending_approvals JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, revision)
);

CREATE TABLE IF NOT EXISTS coder_run_attempts (
    attempt_id UUID PRIMARY KEY,
    run_id UUID NOT NULL
        REFERENCES coder_runs(run_id) ON DELETE CASCADE,
    checkpoint_revision INTEGER,
    summary TEXT NOT NULL,
    failure_class TEXT,
    relevant_files JSONB NOT NULL DEFAULT '[]'::jsonb,
    test_summary TEXT,
    tool_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    state TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS coder_tool_executions (
    tool_call_id TEXT PRIMARY KEY,
    run_id UUID NOT NULL
        REFERENCES coder_runs(run_id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    argument_hash TEXT NOT NULL,
    mutation_class TEXT NOT NULL,
    state TEXT NOT NULL,
    result_ref TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_coder_run_route_history_run
    ON coder_run_route_history(run_id, revision);

CREATE INDEX IF NOT EXISTS idx_coder_run_checkpoints_run
    ON coder_run_checkpoints(run_id, revision DESC);

CREATE INDEX IF NOT EXISTS idx_coder_tool_executions_run
    ON coder_tool_executions(run_id);
