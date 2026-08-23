-- Quant Director intelligence layer: review runs (daily/weekly).

CREATE TABLE IF NOT EXISTS quant_review_runs (
    review_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('daily', 'weekly')),
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ran BOOLEAN NOT NULL,
    reason TEXT,
    report JSONB NOT NULL DEFAULT '{}'::jsonb
);
