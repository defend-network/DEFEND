-- P4/P5: deterministic active-version invariants.
-- (a) explicit per-provider active technical pointer (never LIMIT 1);
-- (b) at most ONE active identity and ONE active prompt core (partial
--     unique indexes). Additive; migrations 0001-0010 are never modified.

CREATE TABLE IF NOT EXISTS coder_provider_technical_active (
    provider TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    version TEXT NOT NULL,
    profile_hash TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (profile_id, version)
        REFERENCES coder_provider_technical_profiles (profile_id, version)
);

CREATE UNIQUE INDEX IF NOT EXISTS coder_identity_active_singleton
    ON coder_identity_profiles ((active))
    WHERE active;

CREATE UNIQUE INDEX IF NOT EXISTS coder_prompt_core_active_singleton
    ON coder_prompt_core_bundles ((active))
    WHERE active;
