"""M4.7 shared DeepSeek credential audit (P51).

The DEFENDcoder owner key exists in the canonical platform secret store, but
DEFENDMarkets is NOT authorized to consume it. Authorization would require a
record in the shared integration registry (PRODUCT_PROVIDERS) granting an
ai-model provider to the ``defendmarkets`` product. As of M4.7 no such grant
exists and no shared resolver routes credentials to Markets, so this module
returns DEFENDMARKETS_DEEPSEEK_INTEGRATION_REQUIRED=YES.

Rules enforced here:

* Never copy or duplicate the secret.
* Never reveal the key.
* Deterministic arb engine owns arithmetic; DeepSeek review is summary-only.
"""

from __future__ import annotations

from typing import Any

DEEPSEEK_AUDIT_VERSION = "DEEPSEEK_AUDIT_V1"
AUDIT_RESULT = "DEFENDMARKETS_DEEPSEEK_INTEGRATION_REQUIRED=YES"


def audit_deepseek_integration() -> dict[str, Any]:
    """Return the deterministic P51 audit result.

    Checks the shared integration registry for any ai-model provider granted to
    the ``defendmarkets`` product. If none exists, integration is required
    before any DeepSeek use by DEFENDMarkets.
    """
    authorized = False
    evidence: list[str] = []
    try:
        from defend_integrations.registry import PRODUCT_PROVIDERS, find_provider

        product_providers = PRODUCT_PROVIDERS.get("defendmarkets", ())
        for provider_id in product_providers:
            provider = find_provider(provider_id)
            if provider is None:
                continue
            if provider.category == "ai_models":
                authorized = True
                evidence.append(f"{provider_id} (category=ai_models) is granted to defendmarkets")
    except Exception as error:  # noqa: BLE001
        evidence.append(f"registry unavailable: {type(error).__name__}")
    if not authorized:
        evidence.append("no ai_models provider is granted to the defendmarkets product in the shared registry")
        evidence.append("no shared credential resolver routes DeepSeek to DEFENDMarkets")
    return {
        "result": "AUTHORIZED" if authorized else AUDIT_RESULT,
        "authorized": authorized,
        "policy_version": DEEPSEEK_AUDIT_VERSION,
        "evidence": evidence,
        "note": "Do not copy or duplicate the canonical DeepSeek secret; integration must be owner-authorized via the shared registry.",
    }


def quant_director_arb_review_allowed() -> bool:
    """P50: DeepSeek arb review is allowed only when the shared credential is
    authorized for DEFENDMarkets. Currently returns False."""
    return audit_deepseek_integration()["authorized"]
