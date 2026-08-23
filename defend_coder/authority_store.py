"""Durable authority store + hydration (identity / prompt-core / technical).

Backs the registries with immutable storage so historical authority survives
process restart. Hydration is idempotent (same id/version + same hash) and
fails closed on a hash conflict (STARTUP_INTEGRITY_ERROR). Active markers are
used only while preparing NEW runs; historical resolution never consults
them. The postgres store is exercised against an isolated DB; the memory
store exists for tests/dev and exercises the SAME hydration logic.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Protocol

from psycopg.rows import dict_row

from .identity import DefendCoderIdentityProfile, default_identity_profile
from .registry import (
    DefendCoderPromptBundle,
    ProviderTechnicalProfile,
    build_prompt_core_bundle,
    build_provider_technical_profile,
)
from .technical import (
    deepseek_technical_instructions,
    openai_responses_technical_instructions,
    vllm_technical_instructions,
)


class StartupIntegrityError(RuntimeError):
    pass


class AuthorityStore(Protocol):
    def list_identities(self) -> list[dict[str, object]]: ...
    def save_identity(self, profile: DefendCoderIdentityProfile) -> None: ...
    def set_identity_active(self, profile_id: str, version: str) -> None: ...
    def active_identity_key(self) -> tuple[str, str] | None: ...

    def list_prompt_cores(self) -> list[dict[str, object]]: ...
    def save_prompt_core(self, bundle: DefendCoderPromptBundle) -> None: ...
    def set_prompt_core_active(self, bundle_id: str, version: str) -> None: ...
    def active_prompt_core_key(self) -> tuple[str, str] | None: ...

    def list_technicals(self) -> list[dict[str, object]]: ...
    def save_technical(self, profile: ProviderTechnicalProfile) -> None: ...
    def set_technical_active(self, provider: str, profile_id: str, version: str) -> None: ...
    def active_technical_for(self, provider: str) -> tuple[str, str] | None: ...


class MemoryAuthorityStore:
    def __init__(self) -> None:
        self._identities: dict[tuple[str, str], DefendCoderIdentityProfile] = {}
        self._prompt_cores: dict[tuple[str, str], DefendCoderPromptBundle] = {}
        self._technicals: dict[tuple[str, str], ProviderTechnicalProfile] = {}
        self._identity_active: tuple[str, str] | None = None
        self._prompt_active: tuple[str, str] | None = None
        self._technical_active: dict[str, tuple[str, str]] = {}

    def list_identities(self):
        return [
            {
                "profile_id": p.profile_id,
                "version": p.version,
                "identity_hash": p.hash,
                "system_policy": p.system_policy,
                "engineering_contract": p.engineering_contract,
                "communication_style": p.communication_style,
                "tool_behavior_rules": p.tool_behavior_rules,
            }
            for p in self._identities.values()
        ]

    def save_identity(self, profile):
        key = (profile.profile_id, profile.version)
        existing = self._identities.get(key)
        if existing is not None and existing.hash != profile.hash:
            raise StartupIntegrityError(
                f"identity {profile.profile_id}@{profile.version} hash conflict"
            )
        self._identities[key] = profile

    def set_identity_active(self, profile_id, version):
        self._identity_active = (profile_id, version)

    def active_identity_key(self):
        return self._identity_active

    def list_prompt_cores(self):
        return [
            {
                "bundle_id": b.bundle_id,
                "version": b.version,
                "bundle_hash": b.hash,
                "identity_profile_id": b.identity_profile_id,
                "identity_version": b.identity_version,
                "identity_hash": b.identity_hash,
                "owner_directive_hash": b.owner_directive_hash,
                "engineering_contract_hash": b.engineering_contract_hash,
                "communication_contract_hash": b.communication_contract_hash,
                "tool_policy_hash": b.tool_policy_hash,
                "core_system_authority": b.system_authority,
            }
            for b in self._prompt_cores.values()
        ]

    def save_prompt_core(self, bundle):
        key = (bundle.bundle_id, bundle.version)
        existing = self._prompt_cores.get(key)
        if existing is not None and existing.hash != bundle.hash:
            raise StartupIntegrityError(
                f"prompt core {bundle.bundle_id}@{bundle.version} hash conflict"
            )
        self._prompt_cores[key] = bundle

    def set_prompt_core_active(self, bundle_id, version):
        self._prompt_active = (bundle_id, version)

    def active_prompt_core_key(self):
        return self._prompt_active

    def list_technicals(self):
        return [
            {
                "profile_id": p.profile_id,
                "version": p.version,
                "profile_hash": p.hash,
                "provider": p.provider,
                "protocol": p.protocol,
                "technical_instructions": p.technical_instructions,
            }
            for p in self._technicals.values()
        ]

    def save_technical(self, profile):
        key = (profile.profile_id, profile.version)
        existing = self._technicals.get(key)
        if existing is not None and existing.hash != profile.hash:
            raise StartupIntegrityError(
                f"technical profile {profile.profile_id}@{profile.version} "
                "hash conflict"
            )
        self._technicals[key] = profile

    def active_technical_for(self, provider):
        return self._technical_active.get(provider)

    def set_technical_active(self, provider, profile_id, version):
        if (profile_id, version) not in self._technicals:
            raise StartupIntegrityError(
                f"cannot activate unknown technical profile "
                f"{profile_id}@{version}"
            )
        stored = self._technicals[(profile_id, version)]
        if stored.provider != provider:
            raise StartupIntegrityError(
                f"technical profile {profile_id}@{version} belongs to "
                f"provider {stored.provider!r}, not {provider!r}"
            )
        self._technical_active[provider] = (profile_id, version)

    def get_identity(self, profile_id, version):
        return self._identities.get((profile_id, version))

    def get_prompt_core(self, bundle_id, version):
        return self._prompt_cores.get((bundle_id, version))

    def get_technical(self, profile_id, version):
        return self._technicals.get((profile_id, version))


class PostgresAuthorityStore:
    """Durable authority store backed by CoderDatabase (psycopg).

    Immutable: save() refuses to overwrite a different hash for the same
    id/version. Used in production; exercised against an isolated test DB.
    """

    def __init__(self, db: object) -> None:
        self._db = db

    def _connect(self):
        return self._db.connect()

    def list_identities(self):
        with self._connect() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT profile_id, version, identity_hash, system_policy,
                           engineering_contract, communication_style,
                           tool_behavior_rules
                    FROM coder_identity_profiles
                    """
                )
                return [
                    {
                        "profile_id": row["profile_id"],
                        "version": row["version"],
                        "identity_hash": row["identity_hash"],
                        "system_policy": row["system_policy"],
                        "engineering_contract": row["engineering_contract"],
                        "communication_style": row["communication_style"],
                        "tool_behavior_rules": row["tool_behavior_rules"],
                    }
                    for row in cursor.fetchall()
                ]

    def save_identity(self, profile):
        with self._connect() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    INSERT INTO coder_identity_profiles(
                        profile_id, version, identity_hash, system_policy,
                        engineering_contract, communication_style,
                        tool_behavior_rules
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (profile_id, version) DO NOTHING
                    """,
                    (
                        profile.profile_id,
                        profile.version,
                        profile.hash,
                        profile.system_policy,
                        profile.engineering_contract,
                        profile.communication_style,
                        profile.tool_behavior_rules,
                    ),
                )
                cursor.execute(
                    """
                    SELECT identity_hash FROM coder_identity_profiles
                    WHERE profile_id = %s AND version = %s
                    """,
                    (profile.profile_id, profile.version),
                )
                row = cursor.fetchone()
        if row is not None and row["identity_hash"] != profile.hash:
            raise StartupIntegrityError(
                f"identity {profile.profile_id}@{profile.version} hash conflict"
            )

    def set_identity_active(self, profile_id, version):
        with self._connect() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    "UPDATE coder_identity_profiles SET active = FALSE"
                )
                cursor.execute(
                    """
                    UPDATE coder_identity_profiles SET active = TRUE
                    WHERE profile_id = %s AND version = %s
                    """,
                    (profile_id, version),
                )

    def active_identity_key(self):
        with self._connect() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT profile_id, version FROM coder_identity_profiles
                    WHERE active = TRUE LIMIT 1
                    """
                )
                row = cursor.fetchone()
        return (row["profile_id"], row["version"]) if row else None

    def list_prompt_cores(self):
        with self._connect() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT bundle_id, version, bundle_hash, identity_profile_id,
                           identity_version, identity_hash, owner_directive_hash,
                           engineering_contract_hash, communication_contract_hash,
                           tool_policy_hash, core_system_authority
                    FROM coder_prompt_core_bundles
                    """
                )
                return [
                    {
                        "bundle_id": row["bundle_id"],
                        "version": row["version"],
                        "bundle_hash": row["bundle_hash"],
                        "identity_profile_id": row["identity_profile_id"],
                        "identity_version": row["identity_version"],
                        "identity_hash": row["identity_hash"],
                        "owner_directive_hash": row["owner_directive_hash"],
                        "engineering_contract_hash": row["engineering_contract_hash"],
                        "communication_contract_hash": row["communication_contract_hash"],
                        "tool_policy_hash": row["tool_policy_hash"],
                        "core_system_authority": row["core_system_authority"],
                    }
                    for row in cursor.fetchall()
                ]

    def save_prompt_core(self, bundle):
        with self._connect() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    INSERT INTO coder_prompt_core_bundles(
                        bundle_id, version, bundle_hash, identity_profile_id,
                        identity_version, identity_hash, owner_directive_hash,
                        engineering_contract_hash, communication_contract_hash,
                        tool_policy_hash, core_system_authority
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (bundle_id, version) DO NOTHING
                    """,
                    (
                        bundle.bundle_id,
                        bundle.version,
                        bundle.hash,
                        bundle.identity_profile_id,
                        bundle.identity_version,
                        bundle.identity_hash,
                        bundle.owner_directive_hash,
                        bundle.engineering_contract_hash,
                        bundle.communication_contract_hash,
                        bundle.tool_policy_hash,
                        bundle.system_authority,
                    ),
                )
                cursor.execute(
                    """
                    SELECT bundle_hash FROM coder_prompt_core_bundles
                    WHERE bundle_id = %s AND version = %s
                    """,
                    (bundle.bundle_id, bundle.version),
                )
                row = cursor.fetchone()
        if row is not None and row["bundle_hash"] != bundle.hash:
            raise StartupIntegrityError(
                f"prompt core {bundle.bundle_id}@{bundle.version} hash conflict"
            )

    def set_prompt_core_active(self, bundle_id, version):
        with self._connect() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    "UPDATE coder_prompt_core_bundles SET active = FALSE"
                )
                cursor.execute(
                    """
                    UPDATE coder_prompt_core_bundles SET active = TRUE
                    WHERE bundle_id = %s AND version = %s
                    """,
                    (bundle_id, version),
                )

    def active_prompt_core_key(self):
        with self._connect() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT bundle_id, version FROM coder_prompt_core_bundles
                    WHERE active = TRUE LIMIT 1
                    """
                )
                row = cursor.fetchone()
        return (row["bundle_id"], row["version"]) if row else None

    def list_technicals(self):
        with self._connect() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT profile_id, version, profile_hash, provider,
                           protocol, technical_instructions
                    FROM coder_provider_technical_profiles
                    """
                )
                return [
                    {
                        "profile_id": row["profile_id"],
                        "version": row["version"],
                        "profile_hash": row["profile_hash"],
                        "provider": row["provider"],
                        "protocol": row["protocol"],
                        "technical_instructions": row["technical_instructions"],
                    }
                    for row in cursor.fetchall()
                ]

    def save_technical(self, profile):
        with self._connect() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    INSERT INTO coder_provider_technical_profiles(
                        profile_id, version, profile_hash, provider, protocol,
                        technical_instructions
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (profile_id, version) DO NOTHING
                    """,
                    (
                        profile.profile_id,
                        profile.version,
                        profile.hash,
                        profile.provider,
                        profile.protocol,
                        profile.technical_instructions,
                    ),
                )
                cursor.execute(
                    """
                    SELECT profile_hash FROM coder_provider_technical_profiles
                    WHERE profile_id = %s AND version = %s
                    """,
                    (profile.profile_id, profile.version),
                )
                row = cursor.fetchone()
        if row is not None and row["profile_hash"] != profile.hash:
            raise StartupIntegrityError(
                f"technical profile {profile.profile_id}@{profile.version} "
                "hash conflict"
            )

    def active_technical_for(self, provider):
        with self._connect() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT profile_id, version
                    FROM coder_provider_technical_active
                    WHERE provider = %s
                    """,
                    (provider,),
                )
                row = cursor.fetchone()
        return (row["profile_id"], row["version"]) if row else None

    def set_technical_active(self, provider, profile_id, version):
        with self._connect() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT profile_hash, provider AS profile_provider
                    FROM coder_provider_technical_profiles
                    WHERE profile_id = %s AND version = %s
                    """,
                    (profile_id, version),
                )
                row = cursor.fetchone()
                if row is None:
                    raise StartupIntegrityError(
                        f"cannot activate unknown technical profile "
                        f"{profile_id}@{version}"
                    )
                if row["profile_provider"] != provider:
                    raise StartupIntegrityError(
                        f"technical profile {profile_id}@{version} belongs to "
                        f"provider {row['profile_provider']!r}, not {provider!r}"
                    )
                cursor.execute(
                    """
                    INSERT INTO coder_provider_technical_active(
                        provider, profile_id, version, profile_hash
                    )
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (provider) DO UPDATE
                    SET profile_id = EXCLUDED.profile_id,
                        version = EXCLUDED.version,
                        profile_hash = EXCLUDED.profile_hash,
                        updated_at = now()
                    """,
                    (provider, profile_id, version, row["profile_hash"]),
                )


def _identity_from_record(record: dict[str, object]) -> DefendCoderIdentityProfile:
    profile = DefendCoderIdentityProfile(
        profile_id=str(record["profile_id"]),
        version=str(record["version"]),
        system_policy=str(record["system_policy"]),
        engineering_contract=str(record["engineering_contract"]),
        communication_style=str(record["communication_style"]),
        tool_behavior_rules=str(record["tool_behavior_rules"]),
    )
    if profile.hash != str(record["identity_hash"]):
        raise StartupIntegrityError(
            f"identity {profile.profile_id}@{profile.version} stored hash "
            "does not match recomputed hash"
        )
    return profile


def _bundle_from_record(record: dict[str, object]) -> DefendCoderPromptBundle:
    bundle = DefendCoderPromptBundle(
        bundle_id=str(record["bundle_id"]),
        version=str(record["version"]),
        identity_profile_id=str(record["identity_profile_id"]),
        identity_version=str(record["identity_version"]),
        identity_hash=str(record["identity_hash"]),
        owner_directive_hash=str(record["owner_directive_hash"]),
        engineering_contract_hash=str(record["engineering_contract_hash"]),
        communication_contract_hash=str(record["communication_contract_hash"]),
        tool_policy_hash=str(record["tool_policy_hash"]),
        system_authority=str(record["core_system_authority"]),
    )
    if bundle.hash != str(record["bundle_hash"]):
        raise StartupIntegrityError(
            f"prompt core {bundle.bundle_id}@{bundle.version} stored hash "
            "does not match recomputed hash"
        )
    return bundle


def _technical_from_record(record: dict[str, object]) -> ProviderTechnicalProfile:
    profile = ProviderTechnicalProfile(
        profile_id=str(record["profile_id"]),
        version=str(record["version"]),
        provider=str(record["provider"]),
        protocol=str(record["protocol"]),
        technical_instructions=str(record["technical_instructions"]),
    )
    if profile.hash != str(record["profile_hash"]):
        raise StartupIntegrityError(
            f"technical profile {profile.profile_id}@{profile.version} stored "
            "hash does not match recomputed hash"
        )
    return profile


@dataclass
class HydratedAuthority:
    identity_profiles: dict[tuple[str, str], DefendCoderIdentityProfile]
    prompt_cores: dict[tuple[str, str], DefendCoderPromptBundle]
    technical_profiles: dict[tuple[str, str], ProviderTechnicalProfile]
    active_identity: tuple[str, str] | None
    active_prompt_core: tuple[str, str] | None


def hydrate_authority(
    store: AuthorityStore,
    *,
    seed_if_empty: bool = True,
) -> HydratedAuthority:
    """Load durable authority; seed canonical versions on first startup.

    Idempotent for identical content; fails closed on any hash conflict.
    """
    identities = {
        (r["profile_id"], r["version"]): _identity_from_record(r)
        for r in store.list_identities()
    }
    prompt_cores = {
        (r["bundle_id"], r["version"]): _bundle_from_record(r)
        for r in store.list_prompt_cores()
    }
    technicals = {
        (r["profile_id"], r["version"]): _technical_from_record(r)
        for r in store.list_technicals()
    }

    if seed_if_empty and not identities:
        default = default_identity_profile()
        store.save_identity(default)
        store.set_identity_active(default.profile_id, default.version)
        identities[(default.profile_id, default.version)] = default

    active_identity = store.active_identity_key()
    if active_identity is None and identities:
        first = next(iter(identities.values()))
        store.set_identity_active(first.profile_id, first.version)
        active_identity = (first.profile_id, first.version)

    if seed_if_empty and not prompt_cores and identities:
        identity = identities[active_identity] if active_identity in identities else next(iter(identities.values()))
        core = build_prompt_core_bundle(identity)
        store.save_prompt_core(core)
        store.set_prompt_core_active(core.bundle_id, core.version)
        prompt_cores[(core.bundle_id, core.version)] = core

    active_prompt_core = store.active_prompt_core_key()
    if active_prompt_core is None and prompt_cores:
        first = next(iter(prompt_cores.values()))
        store.set_prompt_core_active(first.bundle_id, first.version)
        active_prompt_core = (first.bundle_id, first.version)

    if seed_if_empty and not technicals:
        for provider in ("deepseek", "self_hosted", "openai"):
            technical = build_provider_technical_profile(provider)
            store.save_technical(technical)
            technicals[(technical.profile_id, technical.version)] = technical
            store.set_technical_active(
                provider, technical.profile_id, technical.version
            )

    # Backfill any MISSING per-provider active pointer deterministically
    # (covers the schema-10 -> 11 upgrade where profiles exist but the new
    # active-pointer table is empty). Never overwrites an existing explicit
    # selection.
    for provider in ("deepseek", "self_hosted", "openai"):
        if store.active_technical_for(provider) is None:
            canonical = build_provider_technical_profile(provider)
            key = (canonical.profile_id, canonical.version)
            if key not in technicals:
                store.save_technical(canonical)
                technicals[key] = canonical
            store.set_technical_active(
                provider, canonical.profile_id, canonical.version
            )

    return HydratedAuthority(
        identity_profiles=identities,
        prompt_cores=prompt_cores,
        technical_profiles=technicals,
        active_identity=active_identity,
        active_prompt_core=active_prompt_core,
    )


AUTHORITY_STORE_MODE_ENV = "DEFENDCODER_AUTHORITY_STORE_MODE"


def build_authority_store(db: object, mode: str | None = None) -> AuthorityStore:
    """Select the authority store by explicit mode (never a catch-all fallback).

    POSTGRES (default) is the only production mode and fails closed on any
    store/hydration error. MEMORY_TEST is for tests/dev and must be chosen
    explicitly.
    """
    mode = (
        (mode or os.environ.get(AUTHORITY_STORE_MODE_ENV) or "postgres")
        .strip()
        .lower()
    )
    if mode == "postgres":
        return PostgresAuthorityStore(db)
    if mode == "memory_test":
        return MemoryAuthorityStore()
    raise StartupIntegrityError(f"unknown authority store mode {mode!r}")
