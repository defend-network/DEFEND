"""Bounded production health probe for the DEFENDcoder runtime endpoint.

READY requires a successful bounded probe that confirms the served model
identity matches the intended model. The HTTP transport is dependency-injected
so tests are fully deterministic (no real network).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping

MAX_RESPONSE_BYTES = 64 * 1024
DEFAULT_TIMEOUT_SECONDS = 5.0


def _default_transport(
    url: str,
    *,
    timeout_seconds: float,
) -> Mapping[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("health response exceeded the bounded size")
    data = json.loads(body.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("health response is not a JSON object")
    return data


def _parse_served_model_ids(data: Mapping[str, Any]) -> frozenset[str]:
    models = data.get("data")
    if not isinstance(models, list):
        return frozenset()
    ids: set[str] = set()
    for item in models:
        if isinstance(item, Mapping) and isinstance(item.get("id"), str):
            ids.add(item["id"])
    return frozenset(ids)


def probe_endpoint_ready(
    endpoint: str,
    expected_model: str,
    *,
    transport: Callable[..., Mapping[str, Any]] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> bool:
    """Return True only when the endpoint serves the intended model.

    Endpoint alone is never sufficient: the served model identity must match.
    A missing/empty model list, a mismatched model, or any error -> False.
    """
    if not endpoint or not expected_model:
        return False
    fetch = transport or _default_transport
    try:
        data = fetch(f"{endpoint.rstrip('/')}/models", timeout_seconds=timeout_seconds)
    except Exception:  # noqa: BLE001 - any transport/timeout/parse failure fails closed
        return False
    served = _parse_served_model_ids(data)
    return expected_model in served
