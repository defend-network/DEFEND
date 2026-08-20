CREATE TABLE IF NOT EXISTS backfill_checkpoints (
    checkpoint_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider TEXT NOT NULL,
    sport TEXT NOT NULL,
    league TEXT NOT NULL DEFAULT '',
    window_from TIMESTAMPTZ NOT NULL,
    window_to TIMESTAMPTZ NOT NULL,
    cursor_value TEXT NOT NULL DEFAULT '',
    events_seen BIGINT NOT NULL DEFAULT 0,
    events_persisted BIGINT NOT NULL DEFAULT 0,
    odds_persisted BIGINT NOT NULL DEFAULT 0,
    results_persisted BIGINT NOT NULL DEFAULT 0,
    requests_used BIGINT NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'RUNNING',
    error_detail TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider, sport, league, window_from, window_to)
);
CREATE INDEX IF NOT EXISTS idx_backfill_checkpoints_provider
    ON backfill_checkpoints(provider, status, updated_at DESC);