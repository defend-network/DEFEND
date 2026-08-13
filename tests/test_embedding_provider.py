from __future__ import annotations

import pytest

from embedding_provider import EmbeddingSettings, build_embedding_client
from ollama_embedding_client import OllamaEmbeddingClient
from openai_embedding_client import OpenAIEmbeddingClient


def test_embedding_settings_default_to_explicit_ollama_compatibility():
    settings = EmbeddingSettings.from_env({})
    assert settings.provider == "ollama"
    assert settings.model == "qwen3-embedding:0.6b"
    assert settings.base_url == "http://127.0.0.1:11434"
    assert settings.vector_dim == 1024
    assert isinstance(build_embedding_client(settings), OllamaEmbeddingClient)


def test_embedding_settings_build_vllm_client_from_environment():
    settings = EmbeddingSettings.from_env(
        {
            "DEFEND_EMBEDDING_PROVIDER": "vllm",
            "DEFEND_EMBEDDING_MODEL": "Qwen/Qwen3-Embedding-0.6B",
            "DEFEND_EMBEDDING_BASE_URL": "http://127.0.0.1:8002/v1",
            "DEFEND_EMBEDDING_API_KEY": "test-key",
            "DEFEND_EMBEDDING_BATCH_SIZE": "16",
            "DEFEND_EMBEDDING_TIMEOUT_SECONDS": "90",
            "DEFEND_EMBEDDING_VECTOR_DIM": "1024",
        }
    )
    client = build_embedding_client(settings)
    assert isinstance(client, OpenAIEmbeddingClient)
    assert settings.provider_label == "vLLM - Qwen/Qwen3-Embedding-0.6B"
    assert settings.api_key == "test-key"


@pytest.mark.parametrize(
    "overrides,match",
    [
        ({"DEFEND_EMBEDDING_PROVIDER": "unknown"}, "provider"),
        (
            {
                "DEFEND_EMBEDDING_PROVIDER": "vllm",
                "DEFEND_EMBEDDING_BASE_URL": "http://example.com:8002",
                "DEFEND_EMBEDDING_API_KEY": "test-key",
            },
            "loopback",
        ),
        (
            {
                "DEFEND_EMBEDDING_PROVIDER": "vllm",
                "DEFEND_EMBEDDING_API_KEY": "",
            },
            "API key",
        ),
        ({"DEFEND_EMBEDDING_VECTOR_DIM": "768"}, "1024"),
        ({"DEFEND_EMBEDDING_BATCH_SIZE": "0"}, "batch"),
        ({"DEFEND_EMBEDDING_TIMEOUT_SECONDS": "nope"}, "timeout"),
    ],
)
def test_embedding_settings_reject_unsafe_or_incompatible_configuration(overrides, match):
    with pytest.raises(ValueError, match=match):
        EmbeddingSettings.from_env(overrides)


def test_embedding_settings_repr_never_contains_api_key():
    settings = EmbeddingSettings.from_env(
        {
            "DEFEND_EMBEDDING_PROVIDER": "vllm",
            "DEFEND_EMBEDDING_API_KEY": "synthetic-private-embedding-key",
        }
    )
    assert "synthetic-private-embedding-key" not in repr(settings)
