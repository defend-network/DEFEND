"""DEFENDcoder-owned runtime status authority.

DEFENDcoder derives its own model runtime status from its own provider/runtime
configuration. Control Center does NOT publish this status; it may only READ
it through the product's health/status endpoint. Status-only observation never
starts GPU compute.
"""

from __future__ import annotations

from typing import Any

from .providers import DEFAULT_DEEPSEEK_MODEL


def coder_runtime_status(
    credentials: object,
    *,
    next_runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Consumer-safe DEFENDcoder runtime status (product-owned truth)."""
    deepseek = bool(credentials.configured("deepseek"))
    sol = bool(credentials.configured("sol"))

    if deepseek:
        state = "ready"
        provider = "deepseek"
        model = DEFAULT_DEEPSEEK_MODEL
        alias = "DEFENDcoder"
        detail = None
    else:
        state = "offline"
        provider = None
        model = None
        alias = None
        detail = "DeepSeek is not configured"

    next_state = (next_runtime or {}).get("state", "ABSENT")

    return {
        "state": state,
        "provider": provider,
        "model": model,
        "alias": alias,
        "context_used": None,
        "context_limit": None,
        "detail": detail,
        "deepseek_configured": deepseek,
        "sol_configured": sol,
        "next_state": next_state,
    }
