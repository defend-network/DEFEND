CREATE TABLE IF NOT EXISTS tt_rating_history (
    history_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    participant_key TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    event_key TEXT NOT NULL,
    opponent_key TEXT NOT NULL,
    pre_rating NUMERIC(8,2) NOT NULL,
    expected NUMERIC(6,4) NOT NULL,
    actual NUMERIC(3,1) NOT NULL,
    post_rating NUMERIC(8,2) NOT NULL,
    result TEXT NOT NULL CHECK (result IN ('win', 'loss', 'draw')),
    model_version TEXT NOT NULL,
    source_provider TEXT NOT NULL,
    raw_ref TEXT,
    UNIQUE (participant_key, ts, event_key)
);
CREATE INDEX IF NOT EXISTS idx_tt_rating_history_participant_ts
    ON tt_rating_history(participant_key, ts);
CREATE INDEX IF NOT EXISTS idx_tt_rating_history_event
    ON tt_rating_history(event_key);