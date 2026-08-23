"""Fail-closed backend for when no billable provider is configured.

This is the PRODUCTION default when VAST_API_KEY is absent. It can never
report a ready endpoint or instance, never provisions, never resumes, and
never destroys. LocalFakeCoderBackend is TEST/OFFLINE-only and is only ever
injected explicitly by tests, never selected by the production factory.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .models import CoderModelRef


class NoProviderBackend:
    """Deterministic fail-closed provider boundary (no billing, no endpoint)."""

    def __init__(self) -> None:
        self.provider = "none"

    def start(
        self,
        model: CoderModelRef,
        *,
        local_port: int,
        session_budget_usd: Decimal,
        launch_runtype: str | None = None,
        resume_instance: object | None = None,
    ) -> dict[str, Any]:
        del model, local_port, session_budget_usd, launch_runtype, resume_instance
        raise ProviderNotConfigured(
            "no billable provider is configured; cannot provision a runtime"
        )

    def smoke(self, endpoint: str, model: CoderModelRef) -> dict[str, Any]:
        del endpoint, model
        return {"ok": False, "latency_ms": 0, "detail": "provider not configured"}

    def stop(
        self,
        *,
        instance_id: int | None,
        provider_run_id: str | None,
        destroy: bool,
    ) -> dict[str, Any]:
        del instance_id, provider_run_id, destroy
        return {"state": "absent", "message": "no runtime to stop"}


class ProviderNotConfigured(RuntimeError):
    """Raised when a provider mutation is attempted without configuration."""
