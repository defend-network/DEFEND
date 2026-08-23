-- Quant research lab persistence: immutable dataset snapshots and experiment
-- results/folds. Additive and idempotent.

CREATE TABLE IF NOT EXISTS quant_dataset_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL,
    cutoff TEXT NOT NULL,
    target_definition TEXT NOT NULL,
    source_query_version INTEGER NOT NULL,
    feature_schema_version INTEGER NOT NULL,
    row_count BIGINT NOT NULL,
    event_count BIGINT NOT NULL,
    player_count BIGINT NOT NULL,
    date_min TEXT,
    date_max TEXT,
    content_hash TEXT NOT NULL,
    excluded_row_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    leakage_checks JSONB NOT NULL DEFAULT '{}'::jsonb,
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS quant_experiments (
    experiment_id TEXT PRIMARY KEY,
    hypothesis_id TEXT,
    dataset_snapshot_id TEXT NOT NULL REFERENCES quant_dataset_snapshots(snapshot_id),
    champion_version TEXT NOT NULL,
    challenger_name TEXT NOT NULL,
    feature_set JSONB NOT NULL DEFAULT '[]'::jsonb,
    algorithm TEXT NOT NULL,
    hyperparameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    seed INTEGER,
    training_window JSONB NOT NULL DEFAULT '{}'::jsonb,
    validation_windows JSONB NOT NULL DEFAULT '{}'::jsonb,
    calibration_method TEXT,
    metrics_requested JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by TEXT,
    code_commit TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    result JSONB NOT NULL DEFAULT '{}'::jsonb,
    decision TEXT
);

CREATE TABLE IF NOT EXISTS quant_experiment_folds (
    fold_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES quant_experiments(experiment_id) ON DELETE CASCADE,
    fold_index INTEGER NOT NULL,
    train_start TEXT,
    train_end TEXT,
    val_start TEXT,
    val_end TEXT,
    train_rows BIGINT,
    val_rows BIGINT,
    brier NUMERIC(10,6),
    log_loss NUMERIC(12,6),
    calibration_error NUMERIC(10,6),
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (experiment_id, fold_index)
);
