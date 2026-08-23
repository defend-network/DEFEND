CREATE TABLE IF NOT EXISTS provider_discovery (
    discovery_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id UUID NOT NULL REFERENCES provider_sources(source_id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '[]'::jsonb,
    observed_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS provider_quota (
    quota_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id UUID NOT NULL REFERENCES provider_sources(source_id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    requests_remaining BIGINT,
    requests_used BIGINT,
    requests_last TEXT,
    status TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_provider_quota_source
    ON provider_quota(source_id, received_at DESC);