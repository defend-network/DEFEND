"""CopilotAnswerVerifier (M1.4, H3-H4).

Deterministic post-synthesis verification of substantial technical claims
before they are presented. Claims are classified (NUMERIC / DESIGN / FIELD /
OEM / STANDARD / CALCULATED / DIAGNOSTIC_INFERENCE / PROCEDURE_REQUIREMENT /
GENERAL_EXPLANATION) and checked against the evidence available in the answer
(facts with labels + citations + calculator results + tool outputs). Unsupported
claims are removed, downgraded to INFERRED/UNKNOWN, or returned as
CLAIM_VERIFICATION_FAILED. Counts: CLAIMS_TOTAL / VERIFIED / DOWNGRADED /
BLOCKED.
"""
from __future__ import annotations

import re
from typing import Any

CALCULATED_LABELS = {"CALCULATED"}
OEM_LABELS = {"OEM"}
STANDARD_LABELS = {"STANDARD", "SCS_PLAYBOOK"}
DESIGN_LABELS = {"DESIGN"}
FIELD_LABELS = {"FIELD"}
INFERRED_LABELS = {"INFERRED"}


def classify_claim(claim: dict[str, Any]) -> str:
    concept = str(claim.get("concept") or "").upper()
    label = str(claim.get("label") or "").upper()
    if claim.get("calculation_id") or claim.get("formula_id"):
        return "CALCULATED"
    if concept.startswith("DESIGN_"):
        return "DESIGN"
    if concept.startswith("FIELD_"):
        return "FIELD"
    if concept.startswith("OEM_"):
        return "OEM"
    if label in STANDARD_LABELS:
        return "STANDARD"
    if label in INFERRED_LABELS or claim.get("inference"):
        return "DIAGNOSTIC_INFERENCE"
    if label in CALCULATED_LABELS:
        return "CALCULATED"
    if label in OEM_LABELS:
        return "OEM"
    if label in DESIGN_LABELS:
        return "DESIGN"
    if label in FIELD_LABELS:
        return "FIELD"
    return "GENERAL_EXPLANATION"


def _has_evidence(claim: dict[str, Any], claim_type: str) -> bool:
    citation = claim.get("citation")
    if claim_type in ("NUMERIC", "CALCULATED"):
        return bool(claim.get("calculation_id") or claim.get("formula_id")
                    or (citation and citation.get("formula")))
    if claim_type == "DESIGN":
        return bool(claim.get("source") or (citation and citation.get("source_type") in
                     ("PROJECT_PLAN", "PROJECT_SCHEDULE", "PROJECT_SPECIFICATION")))
    if claim_type == "FIELD":
        return bool(claim.get("source") or (citation and citation.get("source_type") == "FIELD_MEASUREMENT"))
    if claim_type == "OEM":
        return bool(citation and citation.get("source_type", "").startswith("OEM_"))
    if claim_type == "STANDARD":
        return bool(citation and citation.get("source_type", "").startswith("STANDARD_"))
    if claim_type == "DIAGNOSTIC_INFERENCE":
        return True  # inherently inferred; must carry the label
    if claim_type == "PROCEDURE_REQUIREMENT":
        return bool(claim.get("source") or claim.get("procedure_id"))
    return True


def verify_answer(facts: list[dict[str, Any]]) -> dict[str, Any]:
    """Verify each structured fact; returns counts + verdict per fact."""
    total = len(facts)
    verified = 0
    downgraded = 0
    blocked = 0
    results: list[dict[str, Any]] = []
    for claim in facts:
        claim_type = classify_claim(claim)
        if claim.get("label") == "CALCULATED" and claim.get("value") is not None \
                and claim.get("citation", {}).get("formula"):
            verified += 1
            verdict = "VERIFIED"
        elif claim_type in ("NUMERIC", "CALCULATED") and not _has_evidence(claim, claim_type):
            claim["label"] = "UNKNOWN"
            blocked += 1
            verdict = "BLOCKED"
        elif claim_type in ("OEM", "STANDARD") and not _has_evidence(claim, claim_type):
            claim["label"] = "UNKNOWN"
            downgraded += 1
            verdict = "DOWNGRADED"
        elif claim_type == "DESIGN" and not _has_evidence(claim, claim_type):
            claim["label"] = "UNKNOWN"
            downgraded += 1
            verdict = "DOWNGRADED"
        elif claim_type == "DIAGNOSTIC_INFERENCE":
            if claim.get("label") != "INFERRED":
                claim["label"] = "INFERRED"
                downgraded += 1
                verdict = "DOWNGRADED"
            else:
                verified += 1
                verdict = "VERIFIED"
        else:
            verified += 1
            verdict = "VERIFIED"
        results.append({"claim_type": claim_type, "verdict": verdict,
                        "label": claim.get("label")})
    return {
        "CLAIMS_TOTAL": total, "CLAIMS_VERIFIED": verified,
        "CLAIMS_DOWNGRADED": downgraded, "CLAIMS_BLOCKED": blocked,
        "results": results,
        "verdict": "PASS" if blocked == 0 else "CLAIM_VERIFICATION_FAILED",
    }


def strip_unsupported_numeric_claims(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove unverifiable numeric claims entirely (H3: never send confidently)."""
    return [c for c in claims
            if not (c.get("concept", "").upper().startswith("FIELD_")
                    and c.get("value") is None
                    and not c.get("source"))]
