-- Tool-ledger durable identity fix (run-scoped call ids).
-- Provider call ids (fc_1 / call_1) are only unique within a run/protocol
-- scope; move the primary identity to a server-generated execution_id and
-- enforce UNIQUE(run_id, tool_call_id). Additive; migration 0012 is NOT
-- modified.

ALTER TABLE coder_tool_executions
    DROP CONSTRAINT IF EXISTS coder_tool_executions_pkey;

ALTER TABLE coder_tool_executions
    ADD COLUMN IF NOT EXISTS execution_id UUID;

UPDATE coder_tool_executions
    SET execution_id = gen_random_uuid()
    WHERE execution_id IS NULL;

ALTER TABLE coder_tool_executions
    ALTER COLUMN execution_id SET NOT NULL;

ALTER TABLE coder_tool_executions
    ADD CONSTRAINT coder_tool_executions_pkey PRIMARY KEY (execution_id);

CREATE UNIQUE INDEX IF NOT EXISTS coder_tool_executions_run_toolcall
    ON coder_tool_executions(run_id, tool_call_id);
