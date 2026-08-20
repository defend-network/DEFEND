ALTER TABLE coder_runs
    ADD COLUMN phase TEXT NOT NULL DEFAULT 'queued'
    CHECK (
        phase IN (
            'queued',
            'waiting_for_model',
            'model_generating',
            'executing_tool',
            'waiting_for_model_after_tool',
            'completed',
            'failed',
            'cancelled'
        )
    );