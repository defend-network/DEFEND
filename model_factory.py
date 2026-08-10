"""Build the active ModelClient from environment."""

from __future__ import annotations

import os

from model_client import ModelClient


def build_model_client() -> ModelClient:
    backend = (os.getenv("DEFEND_MODEL_BACKEND") or "ollama").strip().lower()
    model = os.getenv("DEFEND_MODEL", "defend-ai:latest")
    timeout = float(os.getenv("DEFEND_MODEL_TIMEOUT", "600"))

    if backend in {"openai", "vllm", "openai_compatible", "compatible"}:
        from openai_compatible_client import OpenAICompatibleModelClient

        base = os.getenv("DEFEND_MODEL_BASE_URL", "http://127.0.0.1:8001/v1")
        key = os.getenv("DEFEND_MODEL_API_KEY", "EMPTY")
        return OpenAICompatibleModelClient(
            model=model,
            base_url=base,
            api_key=key,
            timeout_seconds=timeout,
        )

    if backend == "ollama":
        from ollama_client import OllamaClient

        host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
        return OllamaClient(model=model, base_url=host, timeout_seconds=timeout)

    raise ValueError(
        f"Unsupported DEFEND_MODEL_BACKEND={backend!r}. "
        "Use one of: ollama, vllm, openai, openai_compatible, compatible"
    )
