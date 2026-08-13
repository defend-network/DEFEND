from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import ipaddress
from urllib.parse import urlsplit

from embedding_client import EmbeddingClient
from ollama_embedding_client import OllamaEmbeddingClient
from openai_embedding_client import OpenAIEmbeddingClient


_VECTOR_DIM = 1024


def _positive_int(raw: str, name: str) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"embedding {name} must be a positive integer") from None
    if value <= 0:
        raise ValueError(f"embedding {name} must be a positive integer")
    return value


def _positive_float(raw: str, name: str) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"embedding {name} must be positive") from None
    if value <= 0:
        raise ValueError(f"embedding {name} must be positive")
    return value


def _loopback_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        raise ValueError("embedding base URL must be a valid loopback URL") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not host
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/", "/v1", "/v1/"}
    ):
        raise ValueError("embedding base URL must be a valid loopback URL")
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host.casefold() == "localhost"
    if not loopback:
        raise ValueError("embedding base URL must use a loopback host")
    return value.rstrip("/")


@dataclass(frozen=True)
class EmbeddingSettings:
    provider: str
    model: str
    base_url: str
    vector_dim: int = _VECTOR_DIM
    batch_size: int = 32
    timeout: float = 120.0
    api_key: str = field(default="", repr=False)

    @property
    def provider_label(self) -> str:
        name = "vLLM" if self.provider == "vllm" else "Ollama"
        return f"{name} - {self.model}"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "EmbeddingSettings":
        provider = str(env.get("DEFEND_EMBEDDING_PROVIDER", "ollama")).strip().lower()
        if provider not in {"ollama", "vllm"}:
            raise ValueError("embedding provider must be ollama or vllm")

        default_model = (
            "Qwen/Qwen3-Embedding-0.6B"
            if provider == "vllm"
            else "qwen3-embedding:0.6b"
        )
        default_url = (
            "http://127.0.0.1:8002"
            if provider == "vllm"
            else "http://127.0.0.1:11434"
        )
        model = str(env.get("DEFEND_EMBEDDING_MODEL", default_model)).strip()
        if not model:
            raise ValueError("embedding model must not be empty")
        base_url = _loopback_url(
            str(env.get("DEFEND_EMBEDDING_BASE_URL", default_url)).strip()
        )
        vector_dim = _positive_int(
            str(env.get("DEFEND_EMBEDDING_VECTOR_DIM", _VECTOR_DIM)),
            "vector dimension",
        )
        if vector_dim != _VECTOR_DIM:
            raise ValueError("embedding vector dimension must be exactly 1024")
        batch_size = _positive_int(
            str(env.get("DEFEND_EMBEDDING_BATCH_SIZE", 32)), "batch size"
        )
        timeout = _positive_float(
            str(env.get("DEFEND_EMBEDDING_TIMEOUT_SECONDS", 120)), "timeout"
        )
        api_key = str(env.get("DEFEND_EMBEDDING_API_KEY", ""))
        if provider == "vllm" and not api_key:
            raise ValueError("embedding API key is required for vLLM")
        return cls(
            provider=provider,
            model=model,
            base_url=base_url,
            vector_dim=vector_dim,
            batch_size=batch_size,
            timeout=timeout,
            api_key=api_key,
        )


def build_embedding_client(settings: EmbeddingSettings) -> EmbeddingClient:
    if not isinstance(settings, EmbeddingSettings):
        raise TypeError("settings must be EmbeddingSettings")
    if settings.provider == "vllm":
        return OpenAIEmbeddingClient(
            model=settings.model,
            base_url=settings.base_url,
            api_key=settings.api_key,
            timeout=settings.timeout,
            batch_size=settings.batch_size,
            vector_dim=settings.vector_dim,
        )
    return OllamaEmbeddingClient(
        model=settings.model,
        base_url=settings.base_url,
        timeout=settings.timeout,
        batch_size=settings.batch_size,
    )
