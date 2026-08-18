from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlsplit

from .model_gateway import ProviderProfile

SCS_AI_MODEL_ALIAS_ENV = "SCS_AI_MODEL_ALIAS"
SCS_AI_MODEL_NAME_ENV = "SCS_AI_MODEL_NAME"
SCS_AI_MODEL_BASE_URL_ENV = "SCS_AI_MODEL_BASE_URL"
SCS_AI_MODEL_API_KEY_ENV = "SCS_AI_MODEL_API_KEY"
SCS_AI_MODEL_API_KEY_FILE_ENV = "SCS_AI_MODEL_API_KEY_FILE"

DEFAULT_MODEL_ALIAS = "scs-language"
DEFAULT_MODEL_NAME = "Qwen/Qwen3-30B-A3B-Instruct-2507"

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _loopback_only(base_url: str) -> bool:
    try:
        parts = urlsplit(base_url)
    except ValueError:
        return False
    if parts.scheme not in {"http", "https"}:
        return False
    host = parts.hostname or ""
    if parts.scheme == "http":
        return host.casefold() in _LOOPBACK_HOSTS
    # https is accepted only for loopback TLS endpoints (same rule as DEFEND embeddings)
    return host.casefold() in _LOOPBACK_HOSTS


@dataclass(frozen=True)
class ScsAiModelConfig:
    """SCS AI language model wiring read from the environment.

    The alias is the gateway key; the base model and optional LoRA/adapter are
    described by model_name. The API key is never included in repr/status and
    never reaches argv, prompts, or logs.
    """

    alias: str | None = None
    model_name: str | None = None
    base_url: str | None = None
    api_key: str | None = field(default=None, repr=False)
    requires_api_key: bool = False

    def __post_init__(self) -> None:
        if self.alias is not None and (
            not isinstance(self.alias, str) or not self.alias.strip()
        ):
            raise ValueError("model alias must not be empty")
        if self.base_url is not None:
            if not isinstance(self.base_url, str) or not self.base_url.strip():
                raise ValueError("model base_url must not be empty")
            if not _loopback_only(self.base_url):
                raise ValueError(
                    "SCS AI model base_url must be a loopback endpoint "
                    "(http://127.0.0.1, localhost, or ::1)"
                )
            object.__setattr__(self, "base_url", self.base_url.strip().rstrip("/"))
        if self.model_name is not None and (
            not isinstance(self.model_name, str) or not self.model_name.strip()
        ):
            raise ValueError("model_name must not be empty")
        if self.requires_api_key and not self.api_key:
            raise ValueError("requires_api_key=True needs an API key")

    def providers(self) -> dict[str, ProviderProfile]:
        if not self.base_url or not self.alias:
            return {}
        return {
            self.alias: ProviderProfile(
                provider_id="openai_compatible",
                model_name=self.model_name or DEFAULT_MODEL_NAME,
                base_url=self.base_url,
                requires_api_key=self.requires_api_key,
            )
        }


def _read_key_file(path: str | None) -> str | None:
    if not path:
        return None
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(
            f"Could not read SCS AI model API key file ({type(error).__name__})"
        ) from None
    value = raw.strip()
    if not value:
        raise ValueError("SCS AI model API key file is empty")
    return value


def load_model_config() -> ScsAiModelConfig:
    """Build the SCS AI model config from SCS_AI_MODEL_* environment values."""
    alias = os.environ.get(SCS_AI_MODEL_ALIAS_ENV) or None
    model_name = os.environ.get(SCS_AI_MODEL_NAME_ENV) or None
    base_url = os.environ.get(SCS_AI_MODEL_BASE_URL_ENV) or None
    api_key = os.environ.get(SCS_AI_MODEL_API_KEY_ENV) or None
    if not api_key:
        api_key = _read_key_file(os.environ.get(SCS_AI_MODEL_API_KEY_FILE_ENV))
    if alias is None and base_url:
        alias = DEFAULT_MODEL_ALIAS
    requires = api_key is not None or bool(os.environ.get(SCS_AI_MODEL_API_KEY_ENV))
    return ScsAiModelConfig(
        alias=alias,
        model_name=model_name,
        base_url=base_url,
        api_key=api_key,
        requires_api_key=requires,
    )