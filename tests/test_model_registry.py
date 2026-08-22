from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from defend_control.model_registry import (
    ADAPTER_REPO,
    ADAPTER_REVISION,
    DEFEND_MODEL_REGISTRY,
    EMBEDDING_MODEL,
    EMBEDDING_REPO,
    GGUF_REPO,
    ALTERNATE_ADAPTER_REPO,
    LOCAL_ALIAS,
    SERVING_ALIAS,
    DefendModelRef,
    DefendModelStatus,
    ModelRegistryError,
    adapter_revision_pin,
    resolve_defend_alias,
)


def test_registry_contains_only_known_defend_ai_aliases():
    assert sorted(DEFEND_MODEL_REGISTRY) == sorted(
        {SERVING_ALIAS, LOCAL_ALIAS, EMBEDDING_MODEL}
    )


def test_resolve_serving_alias_returns_identity_adapter_entry():
    ref = resolve_defend_alias(SERVING_ALIAS)
    assert ref.role == "identity-adapter"
    assert ref.backend == "openai_compatible"
    assert ref.repo_id == ADAPTER_REPO
    assert ref.revision == ADAPTER_REVISION
    assert ref.serving_alias == SERVING_ALIAS


def test_resolve_local_alias_returns_ollama_entry():
    ref = resolve_defend_alias(LOCAL_ALIAS)
    assert ref.role == "local"
    assert ref.backend == "ollama"
    assert ref.repo_id == LOCAL_ALIAS


def test_resolve_embedding_alias_returns_embedding_entry():
    ref = resolve_defend_alias(EMBEDDING_MODEL)
    assert ref.role == "embedding"
    assert ref.repo_id == EMBEDDING_MODEL


def test_existing_repo_ids_are_preserved_read_only():
    assert ADAPTER_REPO == "Defend-network/defend-qwen-32b-lora"
    assert ADAPTER_REVISION == "92c790d248012a5e6adac980b9759fb76bc7adda"
    assert ALTERNATE_ADAPTER_REPO == "Defend-network/defend-identity-lora-v002"
    assert ALTERNATE_ADAPTER_REPO != ADAPTER_REPO
    assert GGUF_REPO == "Defend-network/defend-qwen-32b-gguf"
    assert SERVING_ALIAS == "defend-ai"
    assert LOCAL_ALIAS == "defend-ai:latest"
    assert EMBEDDING_MODEL == "qwen3-embedding:0.6b"
    assert EMBEDDING_REPO == "Qwen/Qwen3-Embedding-0.6B"


def test_alternate_adapter_is_not_a_resolvable_production_entry():
    # The alternate adapter is not production: it must not resolve
    # through the serving alias, and no registry alias points at it.
    with pytest.raises(ModelRegistryError, match="unknown DEFEND AI model alias"):
        resolve_defend_alias(ALTERNATE_ADAPTER_REPO)
    assert all(ref.repo_id != ALTERNATE_ADAPTER_REPO for ref in DEFEND_MODEL_REGISTRY.values())


def test_unknown_alias_fails_loudly():
    with pytest.raises(ModelRegistryError, match="unknown DEFEND AI model alias"):
        resolve_defend_alias("generic-qwen3-32b")


def test_empty_alias_fails_loudly():
    with pytest.raises(ModelRegistryError, match="unknown DEFEND AI model alias"):
        resolve_defend_alias("")


def test_registry_entries_are_immutable():
    with pytest.raises(FrozenInstanceError):
        DEFEND_MODEL_REGISTRY[SERVING_ALIAS].revision = "a" * 40  # type: ignore[misc]


def test_adapter_revision_pin_absent_returns_production_pin(monkeypatch):
    monkeypatch.delenv("DEFEND_ADAPTER_REVISION", raising=False)
    assert adapter_revision_pin() == ADAPTER_REVISION


def test_adapter_revision_pin_accepts_exact_sha(monkeypatch):
    monkeypatch.setenv("DEFEND_ADAPTER_REVISION", "A" * 64)
    assert adapter_revision_pin() == "a" * 64


def test_adapter_revision_pin_rejects_short_value(monkeypatch):
    monkeypatch.setenv("DEFEND_ADAPTER_REVISION", "abc123")
    with pytest.raises(ModelRegistryError, match="immutable SHA"):
        adapter_revision_pin()


def test_adapter_revision_pin_rejects_non_hex_value(monkeypatch):
    monkeypatch.setenv("DEFEND_ADAPTER_REVISION", "z" * 40)
    with pytest.raises(ModelRegistryError, match="immutable SHA"):
        adapter_revision_pin()


def test_status_payload_never_exposes_secret_material():
    status = DefendModelStatus(
        state="ready",
        alias=SERVING_ALIAS,
        serving_alias=SERVING_ALIAS,
        backend="openai_compatible",
        adapter_repo=ADAPTER_REPO,
        adapter_revision="a" * 40,
        base_repo="Qwen/Qwen3-32B",
        base_revision="b" * 40,
        provider="vast",
    )
    payload = status.as_public_dict()
    assert payload["service"] == "DEFEND AI"
    assert payload["state"] == "ready"
    assert payload["adapter_repo"] == ADAPTER_REPO
    assert payload["adapter_revision"] == "a" * 40
    joined = " ".join(str(v) for v in payload.values()).lower()
    for secret_marker in ("token", "password", "api_key", "bearer"):
        assert secret_marker not in joined


def test_status_accepts_unpinned_runtime_resolution():
    status = DefendModelStatus(
        state="offline",
        alias=SERVING_ALIAS,
        serving_alias=SERVING_ALIAS,
        backend="openai_compatible",
        adapter_repo=ADAPTER_REPO,
        adapter_revision=None,
        base_repo=None,
        base_revision=None,
        provider="vast",
        message="runtime revision/main resolution",
    )
    payload = status.as_public_dict()
    assert payload["adapter_revision"] is None
    assert payload["state"] == "offline"


def test_resolution_failure_modes_never_fall_back_to_generic_model():
    # The registry must fail loudly for unknown aliases instead of returning a
    # generic Qwen entry — no silent fallback to a base model without adapter.
    for bad in ("qwen3-30b", "Qwen/Qwen3-32B", "defend-ai:main", " "):
        with pytest.raises(ModelRegistryError):
            resolve_defend_alias(bad)
