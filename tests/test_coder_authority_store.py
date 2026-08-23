"""Durable authority store + hydration tests (memory store, DB-independent)."""

from __future__ import annotations

import pytest

from defend_coder.authority_store import (
    MemoryAuthorityStore,
    PostgresAuthorityStore,
    StartupIntegrityError,
    build_authority_store,
    hydrate_authority,
)
from defend_coder.identity import default_identity_profile
from defend_coder.registry import build_prompt_core_bundle, build_provider_technical_profile


class TestStoreMode:
    def test_default_mode_is_postgres(self):
        store = build_authority_store(object())
        assert isinstance(store, PostgresAuthorityStore)

    def test_memory_test_mode_is_explicit(self):
        store = build_authority_store(object(), mode="memory_test")
        assert isinstance(store, MemoryAuthorityStore)

    def test_unknown_mode_fails_startup(self):
        with pytest.raises(StartupIntegrityError):
            build_authority_store(object(), mode="bogus")

    def test_hydration_propagates_integrity_error(self):
        # No catch-all fallback: a store that raises must propagate.
        class Boom:
            def list_identities(self):
                raise StartupIntegrityError("corrupt")

            list_prompt_cores = list_identities
            list_technicals = list_identities
            save_identity = lambda self, p: None
            set_identity_active = lambda self, a, b: None
            active_identity_key = lambda self: None
            save_prompt_core = lambda self, p: None
            set_prompt_core_active = lambda self, a, b: None
            active_prompt_core_key = lambda self: None
            save_technical = lambda self, p: None
            set_technical_active = lambda self, p, a, b: None
            active_technical_for = lambda self, p: None

        with pytest.raises(StartupIntegrityError):
            hydrate_authority(Boom())

    def test_technical_active_pointer_is_deterministic(self):
        store = MemoryAuthorityStore()
        hydrate_authority(store)
        v1 = build_provider_technical_profile("deepseek", version="1")
        v2 = build_provider_technical_profile("deepseek", version="2")
        store.save_technical(v2)
        store.set_technical_active("deepseek", v2.profile_id, "2")
        assert store.active_technical_for("deepseek") == (v2.profile_id, "2")
        assert store.get_technical(v1.profile_id, "1").hash == v1.hash


class TestHydrationAndSeed:
    def test_first_startup_seeds_canonical_versions(self):
        store = MemoryAuthorityStore()
        authority = hydrate_authority(store)
        assert authority.active_identity is not None
        assert authority.active_prompt_core is not None
        assert ("deepseek-v4-chat-v1", "1") in authority.technical_profiles
        assert ("qwen3-coder-vllm-v1", "1") in authority.technical_profiles
        assert ("openai-responses-v1", "1") in authority.technical_profiles

    def test_hydration_is_idempotent(self):
        store = MemoryAuthorityStore()
        first = hydrate_authority(store)
        second = hydrate_authority(store)
        assert first.active_identity == second.active_identity
        assert len(first.identity_profiles) == len(second.identity_profiles)
        assert len(first.prompt_cores) == len(second.prompt_cores)

    def test_hash_conflict_fails_startup(self):
        store = MemoryAuthorityStore()
        hydrate_authority(store)
        default = default_identity_profile()
        # Same id/version, DIFFERENT content -> must fail closed.
        changed = default.with_content(version="1", communication_style="New.")
        # Force the same (id, version) but different hash via direct save:
        tampered = default_identity_profile().with_content(
            version="1", communication_style="Tampered."
        )
        with pytest.raises(StartupIntegrityError):
            store.save_identity(
                default_identity_profile().with_content(
                    profile_id=default.profile_id,
                    version=default.version,
                    communication_style="Tampered.",
                )
            )

    def test_historical_identity_survives_new_active(self):
        store = MemoryAuthorityStore()
        hydrate_authority(store)
        v1 = default_identity_profile()
        v2 = v1.with_content(version="2", communication_style="Concise.")
        store.save_identity(v2)
        store.set_identity_active(v2.profile_id, "2")
        # Re-hydrate (simulates process restart): v1 still present.
        authority = hydrate_authority(store)
        assert authority.active_identity == (v2.profile_id, "2")
        assert (v1.profile_id, "1") in authority.identity_profiles
        assert authority.identity_profiles[(v1.profile_id, "1")].hash == v1.hash

    def test_stored_hash_mismatch_fails_hydration(self):
        store = MemoryAuthorityStore()
        hydrate_authority(store)
        v1 = default_identity_profile()
        # Corrupt the stored record hash directly.
        corrupted = {
            "profile_id": v1.profile_id,
            "version": v1.version,
            "identity_hash": "f" * 64,
            "system_policy": v1.system_policy,
            "engineering_contract": v1.engineering_contract,
            "communication_style": v1.communication_style,
            "tool_behavior_rules": v1.tool_behavior_rules,
        }
        store._identities = {}
        store._identities[(v1.profile_id, v1.version)] = None
        store.list_identities = lambda: [corrupted]
        with pytest.raises(StartupIntegrityError):
            hydrate_authority(store)


class TestTechnicalProfiles:
    def test_technical_profiles_hydrate_with_distinct_ids(self):
        store = MemoryAuthorityStore()
        authority = hydrate_authority(store)
        ids = {key[0] for key in authority.technical_profiles}
        assert "deepseek-v4-chat-v1" in ids
        assert "qwen3-coder-vllm-v1" in ids
        assert "openai-responses-v1" in ids
