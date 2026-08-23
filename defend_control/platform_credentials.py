"""Platform credential metadata (Section 15, 16).

Platform owns the secret storage MECHANISM; products own HOW they use a
credential. This module is a neutral, read-only view over the existing Setup /
Integrations credential control plane:

- configured/masked state come from the shared encrypted secret store via
  :class:`defend_integrations.stores.SecretRegistry` (never raw values).
- provider -> ``intended_products`` comes from the neutral provider registry
  (:mod:`defend_integrations.registry`) as provider product METADATA. It
  expresses intended/relevant products, NOT runtime enforcement.
- verification state is derived from the last sanitized probe badge.

``PRODUCT_USE_ENFORCEMENT`` is NOT_IMPLEMENTED: nothing here restricts a
product at secret-resolution time. A successful credential test only verifies
the credential; it never authorizes product provider use.
"""

from __future__ import annotations

from typing import Any

from defend_integrations.models import HealthBadge as _IntegrationHealthBadge
from defend_integrations.service import SetupIntegrationsService

_FAILED_BADGES = frozenset(
    {
        _IntegrationHealthBadge.AUTH_FAILED,
        _IntegrationHealthBadge.PLAN_REQUIRED,
        _IntegrationHealthBadge.UNAVAILABLE,
        _IntegrationHealthBadge.DEGRADED,
        _IntegrationHealthBadge.RATE_LIMITED,
    }
)


def verification_state(
    *,
    configured: bool,
    tested_at: str | None,
    health_badge: str,
) -> str:
    """Map stored health evidence onto the Platform credential vocabulary.

    VERIFIED only follows a real, recent, passing probe. NOT_CONFIGURED when
    no value is saved. FAILED when the last probe reported an auth/plan/health
    failure. UNKNOWN when the credential exists but was never verified.
    """
    if not configured:
        return "NOT_CONFIGURED"
    if health_badge == _IntegrationHealthBadge.HEALTHY.value:
        return "VERIFIED"
    if tested_at is None:
        return "UNKNOWN"
    if health_badge in {badge.value for badge in _FAILED_BADGES}:
        return "FAILED"
    return "UNKNOWN"


class PlatformCredentialRegistry:
    """Read-only entitlement view over the shared credential control plane."""

    def __init__(self, service: SetupIntegrationsService) -> None:
        if not isinstance(service, SetupIntegrationsService):
            raise TypeError("service must be a SetupIntegrationsService")
        self._service = service

    def entitlement_rows(self) -> tuple[dict[str, Any], ...]:
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        snapshot = self._service.snapshot()
        for category in snapshot.get("categories", []):
            for provider in category.get("providers", []):
                for credential in provider.get("credentials", []):
                    secret_name = credential.get("name")
                    if not isinstance(secret_name, str) or not secret_name:
                        continue
                    if secret_name in seen:
                        continue
                    seen.add(secret_name)
                    configured = bool(credential.get("configured"))
                    rows.append(
                        {
                            "credential_key": secret_name,
                            "provider": str(provider.get("provider_id") or "unknown"),
                            "provider_name": str(provider.get("display_name") or "unknown"),
                            "category": str(provider.get("category") or "unknown"),
                            "configured": configured,
                            "masked": (
                                str(credential["masked"])
                                if credential.get("masked") is not None
                                else None
                            ),
                            "intended_products": sorted(
                                str(product)
                                for product in provider.get("products", [])
                                if isinstance(product, str)
                            ),
                            "verification_state": verification_state(
                                configured=configured,
                                tested_at=(
                                    str(provider["tested_at"])
                                    if provider.get("tested_at") is not None
                                    else None
                                ),
                                health_badge=str(
                                    provider.get("health_badge")
                                    or _IntegrationHealthBadge.NOT_CONFIGURED.value
                                ),
                            ),
                        }
                    )
        return tuple(
            sorted(rows, key=lambda row: (row["category"], row["credential_key"]))
        )

    def product_use_enforcement(self) -> str:
        """Secret-resolution-time enforcement status.

        The provider registry carries intended/eligible product metadata only;
        Control Center does not gate secret resolution per product. This is
        metadata, not a security entitlement.
        """
        return "NOT_IMPLEMENTED"

    def configured_count(self) -> int:
        return sum(1 for row in self.entitlement_rows() if row["configured"])

    def verified_count(self) -> int:
        return sum(
            1
            for row in self.entitlement_rows()
            if row["verification_state"] == "VERIFIED"
        )

    def to_dict(self) -> dict[str, Any]:
        rows = self.entitlement_rows()
        return {
            "credentials": rows,
            "total": len(rows),
            "configured": sum(1 for row in rows if row["configured"]),
            "verified": sum(
                1 for row in rows if row["verification_state"] == "VERIFIED"
            ),
            "product_use_enforcement": self.product_use_enforcement(),
        }
