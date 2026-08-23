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
# P39: the Quant Director may remain CONFIGURED_NOT_CALLED until live reviews
# are intentionally activated; LIVE_DEEPSEEK_CALLS may remain 0.
STATE_CONFIGURED_NOT_CALLED = "CONFIGURED_NOT_CALLED"
STATE_INTEGRATION_REQUIRED = "INTEGRATION_REQUIRED"


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
    state = STATE_INTEGRATION_REQUIRED
    if authorized:
        state = STATE_CONFIGURED_NOT_CALLED  # P39: authorized but not yet invoked
    return {
        "result": AUDIT_RESULT if not authorized else "AUTHORIZED",
        "state": state,
        "authorized": authorized,
        "live_deepseek_calls": 0,
        "policy_version": DEEPSEEK_AUDIT_VERSION,
        "evidence": evidence,
        "note": "Do not copy or duplicate the canonical DeepSeek secret; integration must be owner-authorized via the shared registry. No live AI call is made merely to prove key availability.",
    }


def quant_director_arb_review_allowed() -> bool:
    """P50: DeepSeek arb review is allowed only when the shared credential is
    authorized for DEFENDMarkets. Currently returns False."""
    return audit_deepseek_integration()["authorized"]


# P40 AI authority boundary. The Quant Director may analyze, review, suggest and
# summarize; it may NEVER place wagers, alter bookmaker accounts, change the
# selected subscription, bypass promotion gates, change M5 weights, override
# deterministic arb math, or modify settlements without evidence.
QUANT_DIRECTOR_FORBIDDEN_ACTIONS = (
    "PLACE_WAGER",
    "ALTER_BOOKMAKER_ACCOUNT",
    "CHANGE_SELECTED_BOOKMAKER",
    "BYPASS_PROMOTION_GATE",
    "CHANGE_M5_WEIGHTS",
    "OVERRIDE_ARB_MATH",
    "MODIFY_SETTLEMENT_WITHOUT_EVIDENCE",
)

QUANT_DIRECTOR_ALLOWED_ACTIONS = (
    "ANALYZE_PERFORMANCE",
    "REVIEW_WEAKNESSES",
    "SUGGEST_HYPOTHESES",
    "SUMMARIZE_ARB_EVIDENCE",
)


def ai_authority_boundary() -> dict[str, Any]:
    return {
        "allowed": list(QUANT_DIRECTOR_ALLOWED_ACTIONS),
        "forbidden": list(QUANT_DIRECTOR_FORBIDDEN_ACTIONS),
        "policy_version": DEEPSEEK_AUDIT_VERSION,
    }
