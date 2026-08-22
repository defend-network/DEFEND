"""DEFENDcoder model-target normalization (DeepSeek / Next / Sol).

Each backend resolves into a normalized ``ModelTarget`` that never carries
secrets. The run layer picks a target by tier, then builds an
OpenAI-compatible client from the target plus the server-side secret
resolver. Self-hosted Next stays loopback-only; managed-API backends
(DeepSeek, Sol) use remote HTTPS endpoints.

Product identity is always DEFENDcoder (see ``router.py``); the model is an
implementation detail reported by the verified runtime.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable

from .agent_client import AgentChatClient
from .model_config import CoderModelConfig
from .router import NEXT_ALIAS, NEXT_MODEL, SOL_MODEL, TIER_1_MODEL

#: DeepSeek managed-API environment names (legitimate DEFEND abstraction,
#: resolved through the secret store by the caller; never logged/printed).
DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_KEY"
DEEPSEEK_API_KEY_FILE_ENV = "DEEPSEEK_API_KEY_FILE"
DEEPSEEK_MODEL_ENV = "DEEPSEEK_MODEL"
DEEPSEEK_BASE_URL_ENV = "DEEPSEEK_BASE_URL"

#: Sol frontier provider environment names.
SOL_API_KEY_ENV = "OPENAI_API_KEY"
SOL_API_KEY_FILE_ENV = "OPENAI_API_KEY_FILE"
SOL_BASE_URL_ENV = "OPENAI_BASE_URL"

DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_SOL_BASE_URL = "https://api.openai.com/v1"

#: Platform runtime registry forward port for the "defendcoder" product
#: (see defend_control.product_runtime.PRODUCT_FORWARD_PORTS). The Next
#: endpoint is resolved from the runtime manager; this constant is the
#: registry-scoped default when no manager is attached.
NEXT_FORWARD_PORT = 8403

#: Short handoff context the escalation flow carries between models.
HANDOFF_FIELDS = (
    "OBJECTIVE",
    "WORKSPACE",
    "CURRENT_TASK",
    "COMPLETED",
    "CURRENT_FAILURE",
    "RELEVANT_FILES",
    "LATEST_TESTS",
    "ATTEMPTS",
    "CONSTRAINTS",
    "NEXT_ACTION",
)


@dataclass(frozen=True)
class ModelTarget:
    """Normalized, secret-free description of a model backend."""

    tier: str
    alias: str
    provider: str
    model_id: str
    endpoint: str | None
    runtime_kind: str
    requires_external_runtime: bool
    availability: bool
    cost_class: str
    managed_api: bool = field(default=False)

    def as_public_dict(self) -> dict[str, object]:
        return {
            "tier": self.tier,
            "alias": self.alias,
            "provider": self.provider,
            "model": self.model_id,
            "runtime_kind": self.runtime_kind,
            "requires_external_runtime": self.requires_external_runtime,
            "available": self.availability,
            "cost_class": self.cost_class,
        }


def _env_secret(
    env: dict[str, str],
    name: str,
    file_name: str | None = None,
) -> str | None:
    value = (env.get(name) or "").strip()
    if value:
        return value
    if file_name:
        path = (env.get(file_name) or "").strip()
        if path:
            try:
                return open(path, encoding="utf-8").read().strip() or None
            except OSError:
                return None
    return None


def deepseek_target(
    env: dict[str, str] | None = None,
    *,
    availability: bool | None = None,
) -> ModelTarget:
    """TIER_1 managed-API target. Availability is resolved dynamically by
    the credential store; the caller may pass an explicit value so a
    credential saved after startup takes effect without a restart."""
    env = env if env is not None else os.environ
    if availability is None:
        key = _env_secret(env, DEEPSEEK_API_KEY_ENV, DEEPSEEK_API_KEY_FILE_ENV)
        availability = bool(key)
    return ModelTarget(
        tier="DEEPSEEK",
        alias=TIER_1_MODEL,
        provider="deepseek",
        model_id=(env.get(DEEPSEEK_MODEL_ENV) or "").strip()
        or DEFAULT_DEEPSEEK_MODEL,
        endpoint=(env.get(DEEPSEEK_BASE_URL_ENV) or "").strip()
        or DEFAULT_DEEPSEEK_BASE_URL,
        runtime_kind="managed_api",
        requires_external_runtime=False,
        availability=availability,
        cost_class="api",
        managed_api=True,
    )


def sol_target(
    env: dict[str, str] | None = None,
    *,
    availability: bool | None = None,
) -> ModelTarget:
    """TIER_3 frontier managed-API target. Optional at startup; availability
    is resolved dynamically from the credential store."""
    env = env if env is not None else os.environ
    if availability is None:
        key = _env_secret(env, SOL_API_KEY_ENV, SOL_API_KEY_FILE_ENV)
        availability = bool(key)
    return ModelTarget(
        tier="SOL",
        alias=SOL_MODEL,
        provider="openai",
        model_id=SOL_MODEL,
        endpoint=(env.get(SOL_BASE_URL_ENV) or "").strip()
        or DEFAULT_SOL_BASE_URL,
        runtime_kind="managed_api",
        requires_external_runtime=False,
        availability=availability,
        cost_class="frontier_api",
        managed_api=True,
    )


def next_target(*, availability: bool = True, endpoint: str | None = None) -> ModelTarget:
    """TIER_2 self-hosted Next. Availability is the RUNTIME availability;
    the target itself is always resolvable (it may be STOPPED_RETAINED).
    The endpoint comes from the platform runtime manager forward port, never
    a hard-coded legacy tunnel port."""
    return ModelTarget(
        tier="NEXT",
        alias=NEXT_ALIAS,
        provider="self_hosted",
        model_id=NEXT_MODEL,
        endpoint=endpoint or f"http://127.0.0.1:{NEXT_FORWARD_PORT}/v1",
        runtime_kind="vllm",
        requires_external_runtime=True,
        availability=availability,
        cost_class="gpu_hourly",
    )


def build_client(
    target: ModelTarget,
    *,
    api_key: str | None,
    max_tokens: int = 4096,
    max_model_len: int = 8192,
    temperature: float = 0.3,
    urlopen: Callable[..., object] | None = None,
) -> AgentChatClient:
    """Build an OpenAI-compatible client for a resolved target.

    ``api_key`` is supplied by the server secret resolver; it is never
    stored on the target or in run records.
    """
    if not isinstance(target, ModelTarget):
        raise TypeError("target must be a ModelTarget")
    if not target.endpoint:
        raise ValueError("target has no endpoint")
    requires_key = target.managed_api
    if requires_key and not api_key:
        raise ValueError(f"provider {target.provider} requires an API key")
    config = CoderModelConfig(
        alias=target.alias,
        model_name=target.model_id,
        base_url=target.endpoint,
        api_key=api_key,
        requires_api_key=requires_key,
        managed_api=target.managed_api,
    )
    return AgentChatClient(
        config,
        max_tokens=max_tokens,
        max_model_len=max_model_len,
        temperature=temperature,
        urlopen=urlopen,
    )
