"""Model routing and transport-failure policy.

Infrastructure failures (timeout, 429, 5xx, DNS, tool outage) never escalate
the model. Only deterministic quality failures may justify Flash -> Pro, and
Pro never routes to Sol automatically.
"""

from __future__ import annotations

from typing import Any

INFRA_FAILURE_KINDS = {
    "timeout",
    "rate_limited",
    "429",
    "5xx",
    "500",
    "502",
    "503",
    "dns",
    "unavailable",
    "tool_outage",
    "connection_error",
}


def classify_transport_failure(status_code: int | None, error_kind: str | None = None) -> str | None:
    if status_code in (401, 403):
        return "credential_failure"
    if status_code == 429 or error_kind == "rate_limited":
        return "rate_limited"
    if status_code is not None and status_code >= 500:
        return "server_error"
    if status_code is None or error_kind in INFRA_FAILURE_KINDS:
        return error_kind or "unavailable"
    return None


def should_escalate_to_pro(
    *,
    transport_kind: str | None,
    quality_claims_unsupported: bool,
    attempt: int,
    max_pro_escalations: int = 1,
) -> dict[str, Any]:
    if transport_kind in INFRA_FAILURE_KINDS or transport_kind in (
        "credential_failure",
        "rate_limited",
        "server_error",
    ):
        return {"escalate": False, "reason": f"infrastructure failure ({transport_kind}); do not escalate model"}
    if quality_claims_unsupported and attempt <= max_pro_escalations:
        return {"escalate": True, "reason": "deterministic quality failure; Pro escalation candidate"}
    return {"escalate": False, "reason": "no justified escalation"}
