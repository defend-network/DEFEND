CREATE TABLE IF NOT EXISTS coder_runs (
    run_id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL
        REFERENCES coder_workspaces(workspace_id)
        ON DELETE CASCADE,
    owner_account_id UUID NOT NULL
        REFERENCES coder_accounts(account_id)
        ON DELETE CASCADE,
    prompt TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS coder_run_messages (
    message_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id UUID NOT NULL
        REFERENCES coder_runs(run_id)
        ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT,
    tool_call_id TEXT,
    tool_name TEXT,
    tool_arguments JSONB,
    tool_result TEXT,
    kind TEXT,
    ok BOOLEAN,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_coder_runs_workspace_time
    ON coder_runs(workspace_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_coder_run_messages_run
    ON coder_run_messages(run_id, seq);