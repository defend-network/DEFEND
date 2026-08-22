-- P10/P47: pin the server-owned identity profile version onto each run so
-- every run can be proven to have used one exact identity (reproducibility).
-- Additive and nullable-defaulted; existing runs are preserved.

ALTER TABLE coder_runs
    ADD COLUMN identity_profile_id TEXT;

ALTER TABLE coder_runs
    ADD COLUMN identity_version TEXT;

ALTER TABLE coder_runs
    ADD COLUMN identity_hash TEXT;
