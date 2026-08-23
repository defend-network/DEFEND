-- Durable immutable authority registries. Additive; never edit in place.
-- (profile_id/version), (bundle_id/version), (profile_id/version) are unique
-- and immutable. ``active`` is a single-row marker used only while preparing
-- NEW runs; historical resolution NEVER consults it.

CREATE TABLE IF NOT EXISTS coder_identity_profiles (
    profile_id TEXT NOT NULL,
    version TEXT NOT NULL,
    identity_hash TEXT NOT NULL,
    system_policy TEXT NOT NULL,
    engineering_contract TEXT NOT NULL,
    communication_style TEXT NOT NULL,
    tool_behavior_rules TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    active BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (profile_id, version)
);

CREATE TABLE IF NOT EXISTS coder_prompt_core_bundles (
    bundle_id TEXT NOT NULL,
    version TEXT NOT NULL,
    bundle_hash TEXT NOT NULL,
    identity_profile_id TEXT NOT NULL,
    identity_version TEXT NOT NULL,
    identity_hash TEXT NOT NULL,
    owner_directive_hash TEXT NOT NULL,
    engineering_contract_hash TEXT NOT NULL,
    communication_contract_hash TEXT NOT NULL,
    tool_policy_hash TEXT NOT NULL,
    core_system_authority TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    active BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (bundle_id, version)
);

CREATE TABLE IF NOT EXISTS coder_provider_technical_profiles (
    profile_id TEXT NOT NULL,
    version TEXT NOT NULL,
    profile_hash TEXT NOT NULL,
    provider TEXT NOT NULL,
    protocol TEXT NOT NULL,
    technical_instructions TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (profile_id, version)
);
