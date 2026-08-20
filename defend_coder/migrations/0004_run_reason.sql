-- P1/P2/P3/P4: terminal reason column + finalizing phase.
-- Reasons: natural_completion, finalized, step_limit, wall_clock_limit,
--          model_timeout, model_unavailable, model_error, user_cancel,
--          internal_error, invalid_prompt, unknown.

ALTER TABLE coder_runs
    ADD COLUMN reason TEXT NOT NULL DEFAULT 'unknown';

ALTER TABLE coder_runs
    DROP CONSTRAINT IF EXISTS coder_runs_phase_check;

ALTER TABLE coder_runs
    ADD CONSTRAINT coder_runs_phase_check CHECK (
        phase IN (
            'queued',
            'waiting_for_model',
            'model_generating',
            'executing_tool',
            'waiting_for_model_after_tool',
            'finalizing',
            'completed',
            'failed',
            'cancelled'
        )
    );