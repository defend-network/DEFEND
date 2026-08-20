-- P1/P2: completion-state model (partial_success, cancelled) and
-- per-call model telemetry.
--
-- Status: added 'partial_success' and 'cancelled'.
--   succeeded        - terminal response obtained (natural_completion or
--                      finalized)
--   partial_success  - incomplete work stopped by action/wall-clock
--                      limit (reason: action_limit or wall_clock_limit)
--   cancelled        - user cancellation (reason: user_cancel)
--   failed           - model/tool/internal failure (reasons:
--                      model_timeout, model_unavailable, model_error,
--                      tool_error, internal_error, invalid_prompt)
-- Reason: added 'action_limit' and 'tool_error' - 'step_limit' and
--         'succeeded_with_warnings' remain readable legacy values that
--         are no longer produced. Historical rows are NOT rewritten.

ALTER TABLE coder_runs
    DROP CONSTRAINT IF EXISTS coder_runs_status_check;

ALTER TABLE coder_runs
    ADD CONSTRAINT coder_runs_status_check CHECK (
        status IN (
            'queued',
            'running',
            'succeeded',
            'partial_success',
            'failed',
            'cancelled'
        )
    );

ALTER TABLE coder_runs
    DROP CONSTRAINT IF EXISTS coder_runs_reason_check;

ALTER TABLE coder_runs
    ADD CONSTRAINT coder_runs_reason_check CHECK (
        reason IN (
            'unknown',
            'natural_completion',
            'finalized',
            'action_limit',
            'step_limit',
            'wall_clock_limit',
            'model_timeout',
            'model_unavailable',
            'model_error',
            'tool_error',
            'user_cancel',
            'internal_error',
            'invalid_prompt'
        )
    );

-- P2A: per-model-call telemetry. input/output/total tokens are the
-- provider-reported usage counts when the serving API returns them
-- (NULL when not available). assistant_visible_tokens and context
-- token counts are estimates ONLY when the provider does not report
-- usage - they are stored in their own columns so they can never be
-- mistaken for provider truth. reasoning_content is NEVER persisted.
CREATE TABLE IF NOT EXISTS coder_model_calls (
    call_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id UUID NOT NULL
        REFERENCES coder_runs(run_id)
        ON DELETE CASCADE,
    step INTEGER NOT NULL CHECK (step >= 0),
    phase TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    finish_reason TEXT,
    max_tokens_requested INTEGER NOT NULL,
    tool_calls_requested INTEGER NOT NULL,
    assistant_visible_chars INTEGER NOT NULL,
    assistant_visible_tokens INTEGER,
    context_tokens INTEGER,
    remaining_action_budget INTEGER,
    request_roundtrip_seconds DOUBLE PRECISION NOT NULL,
    generation_seconds DOUBLE PRECISION,
    tokens_per_second DOUBLE PRECISION,
    error_class TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_coder_model_calls_run_step
    ON coder_model_calls(run_id, step);

CREATE INDEX IF NOT EXISTS idx_coder_model_calls_run
    ON coder_model_calls(run_id);

CREATE INDEX IF NOT EXISTS idx_coder_model_calls_created
    ON coder_model_calls(created_at);

-- P2B: per-run wall-clock decomposition persisted once at termination
-- (queue wait, request round-trips, tool execution, persistence,
-- finalization, unattributed, accounted percent). JSONB: diagnostic
-- metadata, never queried for integrity.
ALTER TABLE coder_runs
    ADD COLUMN IF NOT EXISTS accounting JSONB;