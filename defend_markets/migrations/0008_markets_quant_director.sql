-- Quant Director V1 foundation: research journal, model registry, admin chat,
-- and AI budget ledger. All tables are INSERT/upsert-oriented and idempotent.

CREATE TABLE IF NOT EXISTS quant_research_journal (
    entry_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    hypothesis TEXT NOT NULL,
    rationale TEXT,
    status TEXT NOT NULL DEFAULT 'PROPOSED'
        CHECK (status IN ('PROPOSED', 'QUEUED', 'RUNNING', 'COMPLETED', 'REJECTED', 'PROMOTED')),
    data_needed TEXT,
    experiment_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    result_summary TEXT,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    decision TEXT,
    model_version TEXT,
    ai_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS quant_model_registry (
    model_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'CHALLENGER'
        CHECK (role IN ('CHAMPION', 'CHALLENGER')),
    stage TEXT NOT NULL DEFAULT 'RESEARCH'
        CHECK (stage IN ('RESEARCH', 'BACKTEST', 'WALK_FORWARD', 'SHADOW', 'PAPER',
                         'REJECTED', 'ARCHIVED', 'CHAMPION')),
    artifact_path TEXT,
    artifact_sha256 TEXT,
    fit_n BIGINT,
    cutoff TEXT,
    feature_schema_version INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (model_id, model_version)
);

CREATE TABLE IF NOT EXISTS quant_chat_threads (
    thread_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    admin_account_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS quant_chat_messages (
    message_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    thread_id BIGINT NOT NULL REFERENCES quant_chat_threads(thread_id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS quant_ai_budget_ledger (
    entry_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    day TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    call_count BIGINT NOT NULL DEFAULT 0,
    cost_usd NUMERIC(12,6) NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (day, provider, model)
);
