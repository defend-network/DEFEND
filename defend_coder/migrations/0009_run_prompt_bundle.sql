-- P2.4/P3.1: pin the exact prompt bundle onto each run (reproducibility).
-- Additive and nullable-defaulted; existing runs are preserved.

ALTER TABLE coder_runs
    ADD COLUMN prompt_bundle_id TEXT;

ALTER TABLE coder_runs
    ADD COLUMN prompt_bundle_version TEXT;

ALTER TABLE coder_runs
    ADD COLUMN prompt_bundle_hash TEXT;
