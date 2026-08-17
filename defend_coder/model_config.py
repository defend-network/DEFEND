from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlsplit

CODER_MODEL_ALIAS_ENV = "CODER_MODEL_ALIAS"
CODER_MODEL_NAME_ENV = "CODER_MODEL_NAME"
CODER_MODEL_BASE_URL_ENV = "CODER_MODEL_BASE_URL"
CODER_MODEL_API_KEY_ENV = "CODER_MODEL_API_KEY"
CODER_MODEL_API_KEY_FILE_ENV = "CODER_MODEL_API_KEY_FILE"

DEFAULT_MODEL_ALIAS = "defendcoder-heavy"
DEFAULT_MODEL_NAME = "Qwen/Qwen3-Coder-Next"

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _loopback_only(base_url: str) -> bool:
    try:
        parts = urlsplit(base_url)
    except ValueError:
        return False
    if parts.scheme not in {"http", "https"}:
        return False
    host = parts.hostname or ""
    return host.casefold() in _LOOPBACK_HOSTS


@dataclass(frozen=True)
class CoderModelConfig:
    """DEFENDcoder agent model wiring read from the environment.

    The alias is the model identity; the base URL must be a loopback
    endpoint (the SSH tunnel exposes the remote vLLM on 127.0.0.1). The
    API key is never included in repr/status and never reaches argv,
    prompts, or logs.
    """

    alias: str = DEFAULT_MODEL_ALIAS
    model_name: str = DEFAULT_MODEL_NAME
    base_url: str | None = None
    api_key: str | None = field(default=None, repr=False)
    requires_api_key: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.alias, str) or not self.alias.strip():
            raise ValueError("model alias must not be empty")
        if not isinstance(self.model_name, str) or not self.model_name.strip():
            raise ValueError("model_name must not be empty")
        if self.base_url is not None:
            if not isinstance(self.base_url, str) or not self.base_url.strip():
                raise ValueError("model base_url must not be empty")
            if not _loopback_only(self.base_url):
                raise ValueError(
                    "CODER_MODEL_BASE_URL must be a loopback endpoint "
                    "(http://127.0.0.1, localhost, or ::1)"
                )
            object.__setattr__(
                self, "base_url", self.base_url.strip().rstrip("/")
            )
        if self.requires_api_key and not self.api_key:
            raise ValueError("requires_api_key=True needs an API key")


def _read_key_file(path: str | None) -> str | None:
    if not path:
        return None
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(
            f"Could not read CODER model API key file "
            f"({type(error).__name__})"
        ) from None
    value = raw.strip()
    if not value:
        raise ValueError("CODER model API key file is empty")
    return value


def load_model_config() -> CoderModelConfig:
    """Build the agent model config from CODER_MODEL_* environment values."""
    alias = os.environ.get(CODER_MODEL_ALIAS_ENV) or DEFAULT_MODEL_ALIAS
    model_name = os.environ.get(CODER_MODEL_NAME_ENV) or DEFAULT_MODEL_NAME
    base_url = os.environ.get(CODER_MODEL_BASE_URL_ENV) or None
    api_key = os.environ.get(CODER_MODEL_API_KEY_ENV) or None
    if not api_key:
        api_key = _read_key_file(os.environ.get(CODER_MODEL_API_KEY_FILE_ENV))
    requires = api_key is not None or bool(
        os.environ.get(CODER_MODEL_API_KEY_ENV)
    )
    return CoderModelConfig(
        alias=alias,
        model_name=model_name,
        base_url=base_url,
        api_key=api_key,
        requires_api_key=requires,
    )