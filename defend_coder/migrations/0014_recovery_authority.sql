-- Owner workstation V1.1: recovery authority + execution exclusivity.
-- Additive. Does not rewrite migrations 0001-0013.

-- 1. One active run per workspace, enforced by the database. A run holds the
--    workspace's execution authority while it is queued or running; the
--    partial unique index atomically rejects a second active run (new or
--    resumed) in the same workspace.
CREATE UNIQUE INDEX IF NOT EXISTS coder_runs_one_active_per_workspace
    ON coder_runs(workspace_id)
    WHERE status IN ('queued', 'running');

-- 2. Immutable task identity. The server derives a canonical prompt hash at
--    preparation; reconstruction proves the persisted run prompt still
--    matches the envelope (caller/browser cannot control the trusted hash).
ALTER TABLE coder_run_execution_envelopes
    ADD COLUMN IF NOT EXISTS prompt_sha256 TEXT;

-- 3. Durable, additive recovery resolution. Historical tool-execution identity
--    is never rewritten; each owner resolution is a new immutable row.
CREATE TABLE IF NOT EXISTS coder_run_recovery (
    recovery_id UUID PRIMARY KEY,
    run_id UUID NOT NULL
        REFERENCES coder_runs(run_id) ON DELETE CASCADE,
    execution_id UUID NOT NULL,
    tool_call_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    prior_state TEXT NOT NULL,
    mutation_class TEXT NOT NULL,
    owner_account_id UUID NOT NULL,
    resolution TEXT NOT NULL,
    note TEXT,
    resulting_state TEXT NOT NULL,
    resolved_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_coder_run_recovery_run
    ON coder_run_recovery(run_id, resolved_at);
