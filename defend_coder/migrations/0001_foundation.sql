CREATE TABLE IF NOT EXISTS coder_schema_migrations (
    version INTEGER PRIMARY KEY CHECK (version > 0),
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS coder_accounts (
    account_id UUID PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    email TEXT UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'consumer')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS coder_sessions (
    session_id UUID PRIMARY KEY,
    account_id UUID NOT NULL
        REFERENCES coder_accounts(account_id)
        ON DELETE CASCADE,
    token_hash CHAR(64) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS coder_workspaces (
    workspace_id UUID PRIMARY KEY,
    owner_account_id UUID NOT NULL
        REFERENCES coder_accounts(account_id)
        ON DELETE CASCADE,
    name TEXT NOT NULL,
    workspace_root TEXT NOT NULL,
    repository_url TEXT,
    default_branch TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (owner_account_id, name)
);

CREATE TABLE IF NOT EXISTS coder_audit_events (
    audit_event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_account_id UUID
        REFERENCES coder_accounts(account_id)
        ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT,
    detail_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_coder_sessions_account
    ON coder_sessions(account_id);

CREATE INDEX IF NOT EXISTS idx_coder_sessions_expires
    ON coder_sessions(expires_at);

CREATE INDEX IF NOT EXISTS idx_coder_workspaces_owner
    ON coder_workspaces(owner_account_id);

CREATE INDEX IF NOT EXISTS idx_coder_audit_actor_time
    ON coder_audit_events(actor_account_id, occurred_at DESC);
