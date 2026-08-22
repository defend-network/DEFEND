-- M2.1: durable run phase for "awaiting owner escalation approval".

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
            'cancelled',
            'awaiting_escalation_approval',
            'resuming'
        )
    );
