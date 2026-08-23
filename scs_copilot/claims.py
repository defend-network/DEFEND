"""Structured claim contract + visible-answer verification (M1.4.1, P0-P6).

The final user-visible answer must derive from the VERIFIED claim set - the
model cannot smuggle unsupported OEM / STANDARD / numeric assertions through
freeform prose. Flow:

    MODEL DRAFTS STRUCTURED CLAIMS (or prose)
    -> SERVER EXTRACTS + VERIFIES
    -> SERVER REMOVES/DOWNGRADES UNSUPPORTED CLAIMS
    -> render_visible() builds the visible answer from verified claims only.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

CLAIM_SCHEMA_VERSION = "1.0"
CLAIM_TYPES = ("NUMERIC", "DESIGN", "FIELD", "OEM", "STANDARD", "CALCULATED",
               "PROCEDURE_REQUIREMENT", "DIAGNOSTIC_INFERENCE",
               "GENERAL_EXPLANATION")
_OEM_NAMES = ("CARRIER", "TRANE", "YORK", "DAIKIN", "LENNOX", "RHEEM", "RUUD",
              "GOODMAN", "AMANA", "AAON", "GREENHECK", "PRICE", "TITUS",
              "NAILOR", "BELIMO", "HONEYWELL", "SIEMENS", "SCHNEIDER",
              "MITSUBISHI")
_STANDARD_NAMES = ("NEBB", "AABC", "ASHRAE", "SMACNA")
_UNIT_RE = re.compile(r"\d{1,6}(?:,\d{3})*(?:\.\d+)?\s*(?:CFM|FPM|IN\.?W\.?C\.?|"
                      r"IN\.?W\.?G\.?|PA|PSI|RPM|HZ|HP|KW|V|A|BTUH|TONS?|F|C|%)")


def _sentence_clauses(text: str) -> list[str]:
    """Split visible prose into claim-sized clauses (sentences + conjunctions)."""
    parts = re.split(
        r"(?:[.;!?]\s+)|(?:,\s*(?:and|but)\s+)|(?:\s+(?:and|but)\s+)", text)
    return [p.strip() for p in parts if p.strip()]


def extract_claims_from_prose(content: str,
                              evidence: dict[str, Any]) -> list[dict[str, Any]]:
    """Classify visible-prose clauses into structured claims (P0-P3).

    Returns ALL classified claims; verify_claims() decides which survive.
    The visible answer is rendered only from the verified set.
    """
    claims: list[dict[str, Any]] = []
    for index, clause in enumerate(_sentence_clauses(content), start=1):
        claim_type = _classify_clause(clause)
        claim = {
            "claim_id": f"CLAIM-{index:02d}", "claim_type": claim_type,
            "concept": _concept_for(clause, claim_type),
            "value": _numeric_value(clause),
            "unit": _unit_of(clause),
            "assertion_text": clause,
            "evidence_refs": [], "calculator_ref": None, "source_refs": [],
            "inference": claim_type == "DIAGNOSTIC_INFERENCE",
            "applicability": "UNKNOWN", "confidence": "HIGH",
        }
        claims.append(claim)
    return claims


def _classify_clause(clause: str) -> str:
    upper = clause.upper()
    if any(s in upper for s in _STANDARD_NAMES) and any(
            k in upper for k in ("REQUIRE", "REQUIRES", "MANDAT", "PER ")):
        return "STANDARD"
    if any(name in upper for name in _OEM_NAMES) and any(
            k in upper for k in ("SAYS", "ALLOW", "MAXIMUM", "LIMIT", "RATED",
                                 "SPEC")):
        return "OEM"
    if _UNIT_RE.search(clause):
        return "NUMERIC"
    if any(k in upper for k in ("RESTRICT", "LIKELY", "POSSIBLE", "SUGGEST",
                                "APPEARS", "MAY BE")):
        return "DIAGNOSTIC_INFERENCE"
    return "GENERAL_EXPLANATION"


def _concept_for(clause: str, claim_type: str) -> str:
    upper = clause.upper()
    if "ESP" in upper or "STATIC" in upper:
        return "OEM_MAX_ESP" if claim_type == "OEM" else "STATIC_PRESSURE"
    if "RPM" in upper or "SPEED" in upper:
        return "RPM"
    if "CFM" in upper or "AIRFLOW" in upper:
        return "DESIGN_SUPPLY_CFM" if claim_type == "DESIGN" else "CFM"
    if claim_type == "STANDARD":
        return "STANDARD_REQUIREMENT"
    if claim_type == "DIAGNOSTIC_INFERENCE":
        return "DIAGNOSTIC"
    return claim_type


def _numeric_value(clause: str) -> Any:
    match = re.search(r"\d{1,6}(?:,\d{3})*(?:\.\d+)?", clause)
    if not match:
        return None
    return float(match.group(0).replace(",", ""))


def _unit_of(clause: str) -> str | None:
    match = _UNIT_RE.search(clause)
    if not match:
        return None
    token = match.group(0).split()[-1].upper().rstrip(".")
    mapping = {"IN.W.C": "IN.W.C.", "IN.W.G": "IN.W.G.", "BTUH": "BTUH",
               "TONS": "TONS"}
    return mapping.get(token, token)


def _verify_claim(claim: dict[str, Any], evidence: dict[str, Any]) -> bool:
    claim_type = claim["claim_type"]
    calculators = set(evidence.get("calculators") or [])
    oem_sources = set(evidence.get("oem_sources") or [])
    standard_sources = set(evidence.get("standard_sources") or [])
    plan_sources = set(evidence.get("plan_sources") or [])
    values = evidence.get("values") or []
    value = claim.get("value")

    def value_matches() -> bool:
        return any(value is not None and v is not None and abs(value - v) <= 1.0
                   for _c, v in values)

    if claim_type in ("NUMERIC", "CALCULATED"):
        if claim.get("calculator_ref") in calculators:
            return True
        if value is not None and value_matches():
            return True
        return False
    if claim_type == "DESIGN":
        if set(claim.get("source_refs") or []) & plan_sources:
            return True
        if value is not None and value_matches():
            return True
        return False
    if claim_type == "FIELD":
        return value is not None and value_matches()
    if claim_type == "OEM":
        return bool(set(claim.get("source_refs") or []) & oem_sources)
    if claim_type == "STANDARD":
        return bool(set(claim.get("source_refs") or []) & standard_sources)
    if claim_type == "DIAGNOSTIC_INFERENCE":
        return True  # inherently inferred; label enforced by renderer
    if claim_type == "PROCEDURE_REQUIREMENT":
        return bool(claim.get("source_refs"))
    return True  # GENERAL_EXPLANATION allowed (no specific technical assertion)


def verify_claims(claims: list[dict[str, Any]],
                  evidence: dict[str, Any]) -> dict[str, Any]:
    """Verify structured claims. Returns verified list + counts + per-claim
    verdicts. Unsupported claims are downgraded/blocked and excluded."""
    verified: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    downgraded = blocked = 0
    for claim in claims:
        claim_type = claim.get("claim_type")
        ok = _verify_claim(claim, evidence)
        if claim_type == "DIAGNOSTIC_INFERENCE":
            if not claim.get("inference"):
                claim["inference"] = True
                claim["label"] = "INFERRED"
                downgraded += 1
            verified.append(claim)
            results.append({"claim_id": claim["claim_id"], "claim_type": claim_type,
                            "verdict": "VERIFIED"})
        elif ok:
            claim["label"] = claim_type
            verified.append(claim)
            results.append({"claim_id": claim["claim_id"], "claim_type": claim_type,
                            "verdict": "VERIFIED"})
        elif claim_type in ("OEM", "STANDARD", "NUMERIC", "CALCULATED"):
            claim["label"] = "UNKNOWN"
            claim["blocked_reason"] = ("AUTHORITATIVE_OEM_SOURCE_NOT_INDEXED"
                                       if claim_type == "OEM" else
                                       "AUTHORITATIVE_STANDARD_SOURCE_NOT_INDEXED"
                                       if claim_type == "STANDARD" else
                                       "UNSUPPORTED_NUMERIC")
            blocked += 1
            results.append({"claim_id": claim["claim_id"], "claim_type": claim_type,
                            "verdict": "BLOCKED"})
        else:
            claim["label"] = "UNKNOWN"
            downgraded += 1
            results.append({"claim_id": claim["claim_id"], "claim_type": claim_type,
                            "verdict": "DOWNGRADED"})
    return {
        "CLAIMS_STRUCTURED_TOTAL": len(claims),
        "CLAIMS_VERIFIED": len(verified),
        "CLAIMS_DOWNGRADED": downgraded,
        "CLAIMS_BLOCKED": blocked,
        "verified": verified,
        "results": results,
        "verdict": "PASS" if blocked == 0 else "CLAIM_VERIFICATION_FAILED",
    }


def render_visible(verified: list[dict[str, Any]], *,
                   next_actions: list[str] | None = None,
                   questions: list[str] | None = None,
                   summary: str | None = None) -> str:
    """Build the visible technical answer from VERIFIED claims only."""
    lines = []
    if summary and not _UNIT_RE.search(summary) and not any(
            name in summary.upper() for name in _STANDARD_NAMES + _OEM_NAMES):
        lines.append(summary)
    for claim in verified:
        text = claim.get("assertion_text") or claim.get("value")
        label = claim.get("label")
        if label in ("UNKNOWN",):
            continue
        prefix = f"[{label}] " if label in ("DESIGN", "FIELD", "OEM", "STANDARD",
                                            "CALCULATED", "INFERRED") else ""
        lines.append(prefix + str(text))
    if next_actions:
        lines.append("NEXT BEST ACTION: " + "; ".join(next_actions))
    if questions:
        lines.append("QUESTIONS: " + "; ".join(questions))
    return "\n".join(lines)


def build_evidence(facts: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive verification evidence from gathered tool facts."""
    evidence: dict[str, Any] = {
        "calculators": set(), "plan_sources": set(), "oem_sources": set(),
        "standard_sources": set(), "values": [],
    }
    for fact in facts:
        citation = fact.get("citation") or {}
        label = fact.get("label")
        value = fact.get("value")
        if label == "CALCULATED" and citation.get("formula"):
            evidence["calculators"].add(citation["formula"])
        if label == "DESIGN" and citation.get("source_type", "").startswith("PROJECT_"):
            evidence["plan_sources"].add(citation.get("source_type"))
        if label == "OEM" and citation.get("source_type", "").startswith("OEM_"):
            evidence["oem_sources"].add(citation.get("source_id")
                                        or citation.get("source_type"))
        if label == "STANDARD" and citation.get("source_type", "").startswith("STANDARD_"):
            evidence["standard_sources"].add(citation.get("source_id")
                                             or citation.get("source_type"))
        if isinstance(value, (int, float)):
            evidence["values"].append((fact.get("concept"), value))
    return evidence
