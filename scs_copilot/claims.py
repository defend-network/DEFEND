"""Structured claim contract + visible-answer verification (M1.4.2, P1-P8).

The final user-visible answer must derive from the VERIFIED claim set - the
model cannot smuggle unsupported OEM / STANDARD / numeric assertions through
freeform prose. Flow:

    MODEL DRAFTS STRUCTURED CLAIMS (or prose)
    -> SERVER EXTRACTS + VERIFIES
    -> SERVER REMOVES/DOWNGRADES UNSUPPORTED CLAIMS
    -> render_safe() builds the visible answer from verified claims only,
       and NEVER falls back to raw model prose.

M1.4.2 changes (root causes, not report language):
  * ZERO raw-prose fallback (P1): if no technical claim verifies the visible
    answer is an explicit abstention, never the model's unverified prose.
  * First-class EvidenceFact identity (P4): evidence carries concept/unit/
    entity/source/calculator identity. A claim only verifies when semantic
    identity aligns - an unrelated equal number can no longer cross-verify.
  * Unit-aware numeric verification (P5): no universal +-1 tolerance; units
    are canonicalized and converted; values compared at display precision.
  * Structured model response contract (P3) with evidence-ref binding (P6):
    the model can reference EVID-* tool results; fabricated refs are rejected.
  * GENERAL_EXPLANATION is not a bypass class (P7): hidden job/OEM/standard
    claims are re-classified by an adversarial fallback.
  * Diagnostic strength model (P8): POSSIBLE / SUPPORTED / STRONGLY_SUPPORTED
    / CONTRADICTED / RESOLVED; a bare inference is never presented as fact.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

CLAIM_SCHEMA_VERSION = "2.0"
CLAIM_TYPES = ("NUMERIC", "DESIGN", "FIELD", "OEM", "STANDARD", "CALCULATED",
               "PROCEDURE_REQUIREMENT", "DIAGNOSTIC_INFERENCE",
               "GENERAL_EXPLANATION")
DIAGNOSTIC_STRENGTHS = ("POSSIBLE", "SUPPORTED", "STRONGLY_SUPPORTED",
                        "CONTRADICTED", "RESOLVED")

_OEM_NAMES = ("CARRIER", "TRANE", "YORK", "DAIKIN", "LENNOX", "RHEEM", "RUUD",
              "GOODMAN", "AMANA", "AAON", "GREENHECK", "PRICE", "TITUS",
              "NAILOR", "BELIMO", "HONEYWELL", "SIEMENS", "SCHNEIDER",
              "MITSUBISHI", "MANUFACTURER")
_STANDARD_NAMES = ("NEBB", "AABC", "ASHRAE", "SMACNA")
_UNIT_RE = re.compile(
    r"-?\d{1,6}(?:,\d{3})*(?:\.\d+)?\s*(?:CFM|FPM|FT\s?/\s?MIN|IN\.?\s?W\.?\s?C\.?|"
    r"IN\.?\s?W\.?\s?G\.?|PA|PSI|RPM|HZ|HERTZ|HP|KW|W|V|A|AMPS?|VOLTS?|BTUH|"
    r"BTU\s?/\s?H|TONS?|°F|°C|F|C|%)")

# ---------------------------------------------------------------------------
# Unit system (P5): canonicalization + conversion + display precision
# ---------------------------------------------------------------------------

_UNIT_CANON = {
    "CFM": "CFM",
    "FPM": "FPM", "FT/MIN": "FPM", "FT/MIN.": "FPM",
    "IN.W.C.": "IN.W.C.", "IN.W.C": "IN.W.C.", "INWC": "IN.W.C.", "IN WG": "IN.W.C.",
    "IN.W.G.": "IN.W.G.", "IN.W.G": "IN.W.G.", "INWG": "IN.W.G.",
    "PA": "PA", "PSI": "PSI",
    "RPM": "RPM", "HZ": "HZ", "HERTZ": "HZ",
    "%": "%", "PERCENT": "%", "PCT": "%",
    "F": "DEGF", "C": "DEGC", "°F": "DEGF", "°C": "DEGC", "DEGF": "DEGF", "DEGC": "DEGC",
    "BTUH": "BTUH", "BTU/H": "BTUH", "TONS": "TONS", "TON": "TONS", "TR": "TONS",
    "KW": "KW", "HP": "HP", "W": "W",
    "A": "A", "AMP": "A", "AMPS": "A", "V": "V", "VOLT": "V", "VOLTS": "V",
    "FT2": "FT2", "IN": "IN", "FT": "FT", "LB/FT3": "LB/FT3",
}

_DIM = {
    "CFM": "FLOW",
    "FPM": "VELOCITY",
    "IN.W.C.": "PRESSURE", "IN.W.G.": "PRESSURE", "PA": "PRESSURE", "PSI": "PRESSURE",
    "RPM": "SPEED", "HZ": "FREQUENCY",
    "%": "PERCENT",
    "DEGF": "TEMPERATURE", "DEGC": "TEMPERATURE",
    "BTUH": "ENERGY", "TONS": "ENERGY",
    "KW": "POWER", "HP": "POWER", "W": "POWER",
    "A": "CURRENT", "V": "VOLTAGE",
    "FT2": "AREA", "IN": "LENGTH", "FT": "LENGTH",
    "LB/FT3": "DENSITY",
}

_DISPLAY_DECIMALS = {
    "CFM": 0, "FPM": 0, "IN.W.C.": 2, "IN.W.G.": 2, "PA": 0, "PSI": 2,
    "RPM": 0, "HZ": 1, "%": 1, "DEGF": 1, "DEGC": 1, "BTUH": 0, "TONS": 1,
    "KW": 2, "HP": 2, "W": 0, "A": 1, "V": 0, "FT2": 2, "IN": 2, "FT": 1,
    "LB/FT3": 3,
}

# conversion factors into a shared dimension base
_CONVERT_TO_BASE = {
    "PRESSURE": {"IN.W.C.": 249.089, "IN.W.G.": 249.089, "PA": 1.0, "PSI": 6894.76},
    "ENERGY": {"BTUH": 1.0, "TONS": 12000.0},
    "POWER": {"W": 1.0, "KW": 1000.0, "HP": 745.7},
    "LENGTH": {"IN": 1.0, "FT": 12.0},
}


def canonical_unit(unit: str | None) -> str | None:
    if not unit:
        return None
    key = unit.strip().upper().rstrip(".")
    if key in _UNIT_CANON:
        return _UNIT_CANON[key]
    # normalize "in wc" style
    compact = re.sub(r"[\s.]+", "", key)
    for alias, canon in _UNIT_CANON.items():
        if re.sub(r"[\s.]+", "", alias) == compact:
            return canon
    return None


def units_compatible(a: str | None, b: str | None) -> bool:
    if a is None and b is None:
        return True
    ca, cb = canonical_unit(a), canonical_unit(b)
    if ca is None or cb is None:
        return False
    if ca == cb:
        return True
    return _DIM.get(ca) == _DIM.get(cb) and _DIM.get(ca) is not None


def _to_base(unit: str | None, value: float) -> float | None:
    canon = canonical_unit(unit)
    if canon is None:
        return None
    dim = _DIM.get(canon)
    if dim == "TEMPERATURE":
        if canon == "DEGF":
            return (value - 32.0) / 1.8
        return value
    factors = _CONVERT_TO_BASE.get(dim)
    if factors is None:
        return value
    return value * factors.get(canon, 1.0)


def _display_round(value: float, unit: str | None) -> float:
    canon = canonical_unit(unit)
    decimals = _DISPLAY_DECIMALS.get(canon or "", 6)
    return round(float(value), decimals)


def numeric_values_match(claim_value: float, claim_unit: str | None,
                         evidence_value: float, evidence_unit: str | None) -> bool:
    """Unit-aware numeric equality at display precision (P5)."""
    if claim_value is None or evidence_value is None:
        return False
    cu, eu = canonical_unit(claim_unit), canonical_unit(evidence_unit)
    if cu is not None and eu is not None:
        if not units_compatible(cu, eu):
            return False
        base_c = _to_base(cu, claim_value)
        base_e = _to_base(eu, evidence_value)
        if base_c is None or base_e is None:
            return False
        # round both in the claim's display unit-space for comparison
        return _display_round(base_c, cu) == _display_round(base_e, cu) or \
            abs(base_c - base_e) <= _tolerance(cu)
    # at least one unit unknown: compare at a reasonable relative tolerance
    return abs(claim_value - evidence_value) <= max(1e-9, abs(evidence_value) * 5e-3)


def _tolerance(unit: str) -> float:
    return {"CFM": 0.5, "FPM": 0.5, "%": 0.05, "RPM": 0.5}.get(unit, 1e-6)


# ---------------------------------------------------------------------------
# Concept identity (P3/P4): hierarchical - dimension is NOT semantic concept
# ---------------------------------------------------------------------------

# P4: equivalence ONLY through this explicit reviewed alias map. Distinct
# semantic concepts (SUPPLY_STATIC vs RETURN_STATIC vs FILTER_DP vs COIL_DP;
# SUPPLY_CFM vs OA_CFM vs EXHAUST_CFM) MUST remain distinct. Compatible units
# do not make concepts interchangeable (P3).
_CONCEPT_ALIASES = {
    # generic synonyms (reviewed)
    "AIRFLOW": "CFM",
    "VELOCITY": "FPM",
    "SPEED": "RPM",
    "STATIC": "STATIC_PRESSURE",
    # explicit TESP identity (SCS canonical definition)
    "TOTAL_EXTERNAL_STATIC_PRESSURE": "TESP",
    "TOTAL_EXTERNAL_STATIC": "TESP",
    "EXTERNAL_STATIC_PRESSURE": "TESP",
    "MAXIMUM_ESP": "MAX_ESP",
    "PERCENT": "PERCENT",
    "MAXIMUM_RPM": "MAX_RPM",
    "SUPPLY_AIRFLOW": "SUPPLY_CFM",
    "RETURN_AIRFLOW": "RETURN_CFM",
    "OUTSIDE_AIR_CFM": "OA_CFM",
    "OUTDOOR_AIR_CFM": "OA_CFM",
}

_CLASS_PREFIXES = ("DESIGN_", "FIELD_", "OEM_", "CALCULATED_")

# Entity token extraction (P1): token-boundary equipment/device IDs.
_ENTITY_RE = re.compile(
    r"\b(?:RTU|AHU|VAV|EF|SF|DOAS|MAU|FCU|HP|SA|RA|EA|RG|RF|EG|SD|FD|BD|VD|MD|CD|BKD|VFD|ERV|CU|AC|CH|HX|T|DP|SP|DS)-\d{1,3}\b")


def concept_key(concept: str | None) -> tuple[str, str]:
    """Return (class, canonical-base) with strict semantic identity (P3/P4).

    The class prefix (DESIGN/FIELD/OEM/CALCULATED) is part of identity, and the
    base is normalized ONLY through the explicit alias map - never broad
    dimension collapse.
    """
    c = (concept or "").strip().upper()
    cls = ""
    for prefix in _CLASS_PREFIXES:
        if c.startswith(prefix):
            cls = prefix.rstrip("_")
            c = c[len(prefix):]
            break
    return (cls, _CONCEPT_ALIASES.get(c, c))


def concepts_match(a: str | None, b: str | None) -> bool:
    return concept_key(a) == concept_key(b)


def entity_in_text(text: str) -> str | None:
    """Extract a single explicit equipment/device entity ID (P1)."""
    match = _ENTITY_RE.search(str(text or "").upper())
    return match.group(0) if match else None


ENTITY_EXACT = "ENTITY_EXACT"
ENTITY_GLOBAL = "ENTITY_GLOBAL"
ENTITY_UNRESOLVED = "ENTITY_UNRESOLVED"
ENTITY_CONFLICT = "ENTITY_CONFLICT"


def entity_relation(claim_entity: str | None,
                    fact_entity: str | None) -> str:
    """Explicit entity match semantics (P0). Missing entity is never a
    wildcard for job/equipment-specific evidence."""
    c = (claim_entity or "").strip().upper() or None
    f = (fact_entity or "").strip().upper() or None
    if c and f:
        return ENTITY_EXACT if c == f else ENTITY_CONFLICT
    if c and not f:
        return ENTITY_UNRESOLVED
    if not c and f:
        return ENTITY_UNRESOLVED
    return ENTITY_GLOBAL


# ---------------------------------------------------------------------------
# EvidenceFact (P4)
# ---------------------------------------------------------------------------


@dataclass
class EvidenceFact:
    evidence_id: str
    concept: str | None
    value: Any
    unit: str | None = None
    label: str | None = None
    entity_id: str | None = None
    source_id: str | None = None
    source_type: str | None = None
    calculator_id: str | None = None
    instrument_id: str | None = None
    stage: str | None = None
    operating_mode: str | None = None
    page: str | None = None
    section: str | None = None
    chunk_id: str | None = None
    applicability: str | None = None
    confidence: str = "HIGH"
    timestamp: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = {k: v for k, v in self.__dict__.items() if v is not None}
        return data


def build_evidence(facts: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive verification evidence from gathered tool facts (P4/P6).

    Produces the sets used by legacy verify_claims callers plus a rich list of
    EvidenceFact objects (with evidence_id, concept, unit, entity, source,
    calculator identity)."""
    evidence: dict[str, Any] = {
        "calculators": set(), "plan_sources": set(), "oem_sources": set(),
        "standard_sources": set(), "values": [], "facts": [],
        "source_map": {}, "diagnostics": {},
        "diagnostic_support": 0, "diagnostic_contradiction": 0,
        "diagnostic_resolved": False,
    }
    for index, fact in enumerate(facts or [], start=1):
        citation = fact.get("citation") or {}
        label = (fact.get("label") or "").upper()
        value = fact.get("value")
        source_id = citation.get("source_id")
        source_type = citation.get("source_type")
        calculator_id = citation.get("formula")
        fact_evidence_id = fact.get("evidence_id") or f"EVID-F{index:03d}"
        # P22: diagnostic evidence derives from real session state
        if fact.get("diagnostic") and isinstance(fact["diagnostic"], dict):
            diagnostic = fact["diagnostic"]
            evidence["diagnostics"][diagnostic.get("graph_id") or fact_evidence_id] = diagnostic
            for cause in diagnostic.get("causes", []):
                belief = cause.get("belief")
                if belief == "STRONGLY_SUPPORTED":
                    evidence["diagnostic_support"] += 2
                elif belief == "SUPPORTED":
                    evidence["diagnostic_support"] += 1
                elif belief == "CONTRADICTED":
                    evidence["diagnostic_contradiction"] += 1
                elif belief == "RESOLVED":
                    evidence["diagnostic_resolved"] = True
            if diagnostic.get("resolution_note"):
                evidence["diagnostic_resolved"] = True
        evidence_fact = EvidenceFact(
            evidence_id=fact_evidence_id,
            concept=fact.get("concept"),
            value=value,
            unit=fact.get("unit"),
            label=label,
            entity_id=fact.get("entity_id"),
            source_id=source_id,
            source_type=source_type,
            calculator_id=calculator_id,
            instrument_id=fact.get("instrument_id"),
            stage=fact.get("stage"),
            operating_mode=fact.get("operating_mode"),
            page=citation.get("page"),
            section=citation.get("section"),
            chunk_id=citation.get("chunk_id"),
            applicability=citation.get("applicability") or fact.get("applicability"),
            confidence=fact.get("confidence", "HIGH"),
            extra={"evidence_refs": fact.get("evidence_refs", [])},
        )
        evidence["facts"].append(evidence_fact)
        if calculator_id:
            evidence["calculators"].add(calculator_id)
        if label == "CALCULATED" and calculator_id:
            evidence["calculators"].add(calculator_id)
        if label == "DESIGN" and (source_type or "").startswith("PROJECT_"):
            evidence["plan_sources"].add(source_type or source_id)
            if source_id:
                evidence["source_map"][source_id] = citation
        if label == "OEM" and (source_type or "").startswith("OEM_"):
            evidence["oem_sources"].add(source_id or source_type)
            if source_id:
                evidence["source_map"][source_id] = citation
        if label == "STANDARD" and (source_type or "").startswith("STANDARD_"):
            evidence["standard_sources"].add(source_id or source_type)
            if source_id:
                evidence["source_map"][source_id] = citation
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            evidence["values"].append((fact.get("concept"), value,
                                       fact.get("unit"), fact.get("entity_id"),
                                       fact_evidence_id))
    return evidence


# ---------------------------------------------------------------------------
# Claim extraction (prose fallback + structured contract)
# ---------------------------------------------------------------------------


def _sentence_clauses(text: str) -> list[str]:
    parts = re.split(
        r"(?:[.;!?]\s+)|(?:,\s*(?:and|but)\s+)|(?:\s+(?:and|but)\s+)", text)
    return [p.strip() for p in parts if p.strip()]


def _classify_clause(clause: str) -> str:
    upper = clause.upper()
    if any(s in upper for s in _STANDARD_NAMES) and any(
            k in upper for k in ("REQUIRE", "REQUIRES", "REQUIREMENT", "MANDAT",
                                 "PER ", "RECOMMEND", "RECOMMENDS", "CODE",
                                 "STANDARD", "TOLERANCE", "POINTS")):
        return "STANDARD"
    if any(name in upper for name in _OEM_NAMES) and any(
            k in upper for k in ("SAYS", "ALLOW", "ALLOWS", "MAXIMUM", "MAX ",
                                 "LIMIT", "LIMITS", "RATED", "RATING", "SPEC",
                                 "GUIDANCE", "CALLS FOR", "MANUFACTURER")):
        return "OEM"
    if _UNIT_RE.search(clause):
        return "NUMERIC"
    if any(k in upper for k in ("RESTRICT", "LIKELY", "POSSIBLE", "SUGGEST",
                                "SUGGESTS", "APPEARS", "MAY BE", "INDICATES",
                                "PROVES", "THIS IS A", "MEANS", "SUSPECT")):
        return "DIAGNOSTIC_INFERENCE"
    return "GENERAL_EXPLANATION"


def _concept_for(clause: str, claim_type: str) -> str:
    upper = clause.upper()
    if "OA FRACTION" in upper or "OUTSIDE AIR FRACTION" in upper:
        return "OA_FRACTION"
    if "FILTER" in upper and ("DP" in upper or "DELTA" in upper or "PRESSURE" in upper):
        return "FILTER_DP"
    if "COIL" in upper and ("DP" in upper or "DELTA" in upper or "PRESSURE" in upper):
        return "COIL_DP"
    if "RETURN" in upper and ("STATIC" in upper or "SP" in upper):
        return "RETURN_STATIC"
    if "SUPPLY" in upper and ("STATIC" in upper or "SP" in upper):
        return "SUPPLY_STATIC"
    if "TESP" in upper or "TOTAL EXTERNAL" in upper:
        return "TESP"
    if "ESP" in upper or "STATIC" in upper:
        return "OEM_MAX_ESP" if claim_type == "OEM" else "STATIC_PRESSURE"
    if "RPM" in upper or "SPEED" in upper:
        return "RPM"
    if "%" in upper and "DESIGN" in upper:
        return "PERCENT_DESIGN"
    if "%" in upper:
        return "PERCENT"
    if "OUTSIDE AIR" in upper and ("CFM" in upper or "AIR" in upper):
        return "OA_CFM"
    if "EXHAUST" in upper and ("CFM" in upper or "AIR" in upper):
        return "EXHAUST_CFM"
    if "RETURN" in upper and ("CFM" in upper or "AIR" in upper):
        return "RETURN_CFM"
    if "SUPPLY" in upper and ("CFM" in upper or "AIR" in upper):
        return "SUPPLY_CFM"
    if "CFM" in upper or "AIRFLOW" in upper:
        return "DESIGN_SUPPLY_CFM" if claim_type == "DESIGN" else "CFM"
    if "TEMPERATURE" in upper or " DEG" in upper:
        return "TEMPERATURE"
    if claim_type == "STANDARD":
        return "STANDARD_REQUIREMENT"
    if claim_type == "OEM":
        return "OEM_REQUIREMENT"
    if claim_type == "DIAGNOSTIC_INFERENCE":
        return "DIAGNOSTIC"
    return claim_type


def _numeric_value(clause: str) -> Any:
    match = re.search(r"-?\d{1,6}(?:,\d{3})*(?:\.\d+)?", clause)
    if not match:
        return None
    return float(match.group(0).replace(",", ""))


def _unit_of(clause: str) -> str | None:
    match = _UNIT_RE.search(clause)
    if not match:
        return None
    token = match.group(0)
    unit = re.sub(r"^-?\d{1,6}(?:,\d{3})*(?:\.\d+)?\s*", "", token)
    return unit.strip() or None


def extract_claims_from_prose(content: str,
                              evidence: dict[str, Any]) -> list[dict[str, Any]]:
    """Classify visible-prose clauses into structured claims (P0-P3).

    Returns ALL classified claims; verify_claims() decides which survive.
    The visible answer is rendered only from the verified set.
    """
    claims: list[dict[str, Any]] = []
    for index, clause in enumerate(_sentence_clauses(content or ""), start=1):
        claim_type = _classify_clause(clause)
        claim = {
            "claim_id": f"CLAIM-{index:02d}", "claim_type": claim_type,
            "concept": _concept_for(clause, claim_type),
            "value": _numeric_value(clause),
            "unit": _unit_of(clause),
            "entity_id": entity_in_text(clause),
            "assertion_text": clause,
            "evidence_refs": [], "calculator_ref": None, "source_refs": [],
            "inference": claim_type == "DIAGNOSTIC_INFERENCE",
            "applicability": "UNKNOWN", "confidence": "HIGH",
        }
        claims.append(claim)
    return claims


def extract_structured_claims(content: str,
                              evidence: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Parse a structured model response contract (P3).

    Accepts a JSON object (or a fenced JSON block) shaped:
        {"summary", "claims": [{claim_type, concept, entity_id, value, unit,
                                evidence_refs, applicability, confidence}],
         "next_actions": [...], "questions": [...]}

    Evidence references are validated against evidence facts that actually
    occurred in this run; fabricated refs are rejected (P6).
    """
    if not content:
        return None
    obj = _extract_json(content)
    if not isinstance(obj, dict):
        return None
    raw_claims = obj.get("claims")
    if not isinstance(raw_claims, list) or not raw_claims:
        return None
    valid_evidence_ids = {f.evidence_id for f in evidence.get("facts", [])}
    source_map = evidence.get("source_map", {})
    claims: list[dict[str, Any]] = []
    for index, rc in enumerate(raw_claims, start=1):
        if not isinstance(rc, dict):
            continue
        claim_type = str(rc.get("claim_type") or "GENERAL_EXPLANATION").upper()
        evidence_refs = [str(r) for r in rc.get("evidence_refs") or []]
        source_refs = [str(r) for r in rc.get("source_refs") or []]
        # validate evidence refs; fabricated refs -> explicit rejection marker
        invalid_refs = [r for r in evidence_refs if r not in valid_evidence_ids]
        claims.append({
            "claim_id": f"CLAIM-S{index:02d}",
            "claim_type": claim_type,
            "concept": rc.get("concept") or _concept_for(str(rc.get("summary") or ""), claim_type),
            "entity_id": rc.get("entity_id"),
            "value": rc.get("value"),
            "unit": rc.get("unit"),
            "assertion_text": str(rc.get("summary") or rc.get("value") or ""),
            "evidence_refs": evidence_refs,
            "source_refs": source_refs or evidence_refs,
            "calculator_ref": rc.get("calculator_ref"),
            "inference": claim_type == "DIAGNOSTIC_INFERENCE",
            "applicability": rc.get("applicability") or "UNKNOWN",
            "edition": rc.get("edition"),
            "manufacturer": rc.get("manufacturer"),
            "confidence": rc.get("confidence") or "HIGH",
            "_invalid_evidence_refs": invalid_refs,
        })
    return claims


def _extract_json(content: str) -> Any:
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except (json.JSONDecodeError, TypeError):
            return None
    brace = re.search(r"\{.*\}", content, re.DOTALL)
    if brace:
        try:
            return json.loads(brace.group(0))
        except (json.JSONDecodeError, TypeError):
            return None
    return None


# ---------------------------------------------------------------------------
# Verification (P1, P4, P5, P6, P7, P8)
# ---------------------------------------------------------------------------

_APPLICABILITY_RANK = {
    "EXACT_MODEL": 5, "MODEL_SERIES": 4, "FAMILY": 3,
    "GENERAL_MANUFACTURER": 2, "UNKNOWN": 1,
}

_APPLICABILITY_ALIASES = {
    "EXACT_APPLICABILITY": "EXACT_MODEL",
    "FAMILY_APPLICABILITY": "FAMILY",
    "GENERAL_MANUFACTURER_REFERENCE": "GENERAL_MANUFACTURER",
    "MODEL_PREFIX": "MODEL_SERIES",
    "PRODUCT_FAMILY": "FAMILY",
    "MANUFACTURER_GENERAL": "GENERAL_MANUFACTURER",
}


def _normalize_applicability(value: str | None) -> str:
    normalized = (value or "UNKNOWN").strip().upper()
    return _APPLICABILITY_ALIASES.get(normalized, normalized)


def _oem_applicability_ok(claim: dict[str, Any], source_id: str | None,
                          source_map: dict[str, Any]) -> bool:
    """P6: the cited OEM source must prove sufficient applicability for the
    claim. Broad manufacturer evidence cannot satisfy an equipment/model-
    specific technical limit (P6-P8)."""
    required = (claim.get("applicability") or "UNKNOWN").upper()
    claim_entity = claim.get("entity_id")
    meta = source_map.get(source_id) or {}
    source_applicability = _normalize_applicability(meta.get("applicability"))
    if required == "UNKNOWN" and not claim_entity:
        # generic, non-model-specific manufacturer guidance: existing behavior
        return True
    if required == "UNKNOWN" and claim_entity:
        # P6(F): an entity/model-specific claim must require at least FAMILY;
        # GENERAL_MANUFACTURER (rank 2) must NOT pass merely because UNKNOWN
        # ranks lower.
        required = "FAMILY"
    req_rank = _APPLICABILITY_RANK.get(required, 1)
    src_rank = _APPLICABILITY_RANK.get(source_applicability, 1)
    return src_rank >= req_rank


def _standard_edition_ok(claim: dict[str, Any], source_id: str | None,
                         source_map: dict[str, Any]) -> str | None:
    """P4/P7: an edition-specific STANDARD claim requires the source to prove
    the SAME edition. Missing edition metadata is NOT proof. Returns a blocked
    reason, or None when the claim verifies."""
    claim_edition = (claim.get("edition") or "").strip()
    if not claim_edition:
        return None  # claim asserts no edition; do not fabricate one
    meta = source_map.get(source_id) or {}
    source_edition = (meta.get("edition") or "").strip()
    if not source_edition:
        return "STANDARD_EDITION_UNPROVEN"
    if source_edition != claim_edition:
        return "STANDARD_EDITION_MISMATCH"
    return None


def _verify_claim(claim: dict[str, Any], evidence: dict[str, Any]) -> tuple[bool, str | None, str]:
    """Verify a single claim. Returns (ok, blocked_reason, diagnostic_strength)."""
    claim_type = claim.get("claim_type")
    calculators = set(evidence.get("calculators") or [])
    oem_sources = set(evidence.get("oem_sources") or [])
    standard_sources = set(evidence.get("standard_sources") or [])
    plan_sources = set(evidence.get("plan_sources") or [])
    facts: list[EvidenceFact] = evidence.get("facts") or []
    source_map = evidence.get("source_map") or {}
    value = claim.get("value")
    unit = claim.get("unit")
    entity_id = claim.get("entity_id")

    if claim.get("_invalid_evidence_refs"):
        return False, "FABRICATED_EVIDENCE_REFERENCE", "POSSIBLE"

    def _fact_value_matches() -> bool:
        for fact in facts:
            if not isinstance(fact.value, (int, float)) or isinstance(fact.value, bool):
                continue
            if not concepts_match(claim.get("concept"), fact.concept):
                continue
            # P0: missing entity is never a wildcard for job-specific evidence.
            relation = entity_relation(entity_id, fact.entity_id)
            if relation in (ENTITY_CONFLICT, ENTITY_UNRESOLVED):
                continue
            if not numeric_values_match(value, unit, fact.value, fact.unit):
                continue
            return True
        return False

    def _bound_source(refs: list[str], pool: set, prefix: str) -> str | None:
        refs = refs or []
        for r in refs:
            if r in pool:
                return r
            meta = source_map.get(r)
            if meta and str(meta.get("source_type") or "").startswith(prefix):
                return r
        return None

    if claim_type == "CALCULATED":
        if claim.get("calculator_ref") in calculators:
            return True, None, "RESOLVED"
        if value is not None and _fact_value_matches():
            return True, None, "RESOLVED"
        return False, "CALCULATOR_NOT_RUN", "POSSIBLE"
    if claim_type == "NUMERIC":
        if value is not None and _fact_value_matches():
            return True, None, "RESOLVED"
        return False, "UNSUPPORTED_NUMERIC", "POSSIBLE"
    if claim_type == "DESIGN":
        if _bound_source(claim.get("source_refs"), plan_sources, "PROJECT_"):
            return True, None, "RESOLVED"
        if value is not None and _fact_value_matches():
            return True, None, "RESOLVED"
        return False, "DESIGN_EVIDENCE_NOT_INDEXED", "POSSIBLE"
    if claim_type == "FIELD":
        if _bound_source(claim.get("source_refs"), set(), "FIELD_MEASUREMENT"):
            return True, None, "RESOLVED"
        if value is not None and _fact_value_matches():
            return True, None, "RESOLVED"
        return False, "FIELD_MEASUREMENT_MISSING", "POSSIBLE"
    if claim_type == "OEM":
        bound = _bound_source(claim.get("source_refs"), oem_sources, "OEM_")
        if not bound:
            return False, "AUTHORITATIVE_OEM_SOURCE_NOT_INDEXED", "POSSIBLE"
        if not _oem_applicability_ok(claim, bound, source_map):
            return False, "OEM_APPLICABILITY_INSUFFICIENT", "POSSIBLE"
        return True, None, "RESOLVED"
    if claim_type == "STANDARD":
        bound = _bound_source(claim.get("source_refs"), standard_sources, "STANDARD_")
        if not bound:
            return False, "AUTHORITATIVE_STANDARD_SOURCE_NOT_INDEXED", "POSSIBLE"
        edition_reason = _standard_edition_ok(claim, bound, source_map)
        if edition_reason:
            return False, edition_reason, "POSSIBLE"
        return True, None, "RESOLVED"
    if claim_type == "PROCEDURE_REQUIREMENT":
        if _bound_source(claim.get("source_refs"), standard_sources | oem_sources, ""):
            return True, None, "RESOLVED"
        return False, "PROCEDURE_SOURCE_NOT_INDEXED", "POSSIBLE"
    if claim_type == "DIAGNOSTIC_INFERENCE":
        strength = _diagnostic_strength(claim, evidence)
        return True, None, strength
    # GENERAL_EXPLANATION is NOT a bypass class (P7): strip hidden technical
    # assertions. A general explanation only verifies when it contains no
    # technical number/standard/OEM reference.
    text = str(claim.get("assertion_text") or "").upper()
    if _UNIT_RE.search(text) or any(s in text for s in _STANDARD_NAMES) \
            or any(n in text for n in _OEM_NAMES):
        return False, "GENERAL_EXPLANATION_HIDES_TECHNICAL_CLAIM", "POSSIBLE"
    return True, None, "RESOLVED"


def _diagnostic_strength(claim: dict[str, Any], evidence: dict[str, Any]) -> str:
    """Determine diagnostic strength from evidence (P8)."""
    diagnostics = evidence.get("diagnostics") or {}
    resolved = evidence.get("diagnostic_resolved")
    if resolved:
        return "RESOLVED"
    supporting = evidence.get("diagnostic_support", 0)
    contradicting = evidence.get("diagnostic_contradiction", 0)
    if contradicting:
        return "CONTRADICTED"
    if supporting >= 2:
        return "STRONGLY_SUPPORTED"
    if supporting >= 1:
        return "SUPPORTED"
    # fall back to any diagnostic graph belief in the evidence
    for graph in diagnostics.values():
        for cause in graph.get("causes", []):
            belief = cause.get("belief")
            if belief == "STRONGLY_SUPPORTED":
                return "STRONGLY_SUPPORTED"
            if belief == "SUPPORTED":
                return "SUPPORTED"
            if belief == "CONTRADICTED":
                return "CONTRADICTED"
    return "POSSIBLE"


def verify_claims(claims: list[dict[str, Any]],
                  evidence: dict[str, Any]) -> dict[str, Any]:
    """Verify structured claims. Returns verified list + counts + per-claim
    verdicts. Unsupported claims are downgraded/blocked and excluded."""
    verified: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    downgraded = blocked = 0
    for claim in claims:
        claim_type = claim.get("claim_type")
        ok, reason, strength = _verify_claim(claim, evidence)
        if claim_type == "DIAGNOSTIC_INFERENCE":
            claim["diagnostic_strength"] = strength
            if not claim.get("inference"):
                claim["inference"] = True
                claim["label"] = "INFERRED"
                downgraded += 1
            else:
                claim["label"] = claim.get("label") or "INFERRED"
            verified.append(claim)
            results.append({"claim_id": claim["claim_id"], "claim_type": claim_type,
                            "verdict": "VERIFIED", "diagnostic_strength": strength})
        elif ok:
            claim["label"] = claim.get("label") or claim_type
            claim["diagnostic_strength"] = strength
            verified.append(claim)
            results.append({"claim_id": claim["claim_id"], "claim_type": claim_type,
                            "verdict": "VERIFIED"})
        elif claim_type in ("OEM", "STANDARD", "NUMERIC", "CALCULATED",
                            "PROCEDURE_REQUIREMENT"):
            claim["label"] = "UNKNOWN"
            claim["blocked_reason"] = reason or "UNSUPPORTED"
            blocked += 1
            results.append({"claim_id": claim["claim_id"], "claim_type": claim_type,
                            "verdict": "BLOCKED", "reason": reason})
        else:
            claim["label"] = "UNKNOWN"
            claim["blocked_reason"] = reason or "DOWNGRADED"
            downgraded += 1
            results.append({"claim_id": claim["claim_id"], "claim_type": claim_type,
                            "verdict": "DOWNGRADED", "reason": reason})
    return {
        "CLAIMS_STRUCTURED_TOTAL": len(claims),
        "CLAIMS_VERIFIED": len(verified),
        "CLAIMS_DOWNGRADED": downgraded,
        "CLAIMS_BLOCKED": blocked,
        "verified": verified,
        "results": results,
        "verdict": "PASS" if blocked == 0 else "CLAIM_VERIFICATION_FAILED",
    }


# ---------------------------------------------------------------------------
# Rendering (P1: no raw-prose fallback)
# ---------------------------------------------------------------------------

_STRENGTH_PREFIX = {
    "POSSIBLE": "POSSIBLE", "SUPPORTED": "SUPPORTED",
    "STRONGLY_SUPPORTED": "STRONGLY_SUPPORTED",
    "CONTRADICTED": "CONTRADICTED", "RESOLVED": "RESOLVED",
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
        if claim.get("claim_type") == "DIAGNOSTIC_INFERENCE":
            strength = claim.get("diagnostic_strength") or "POSSIBLE"
            lines.append(f"[{_STRENGTH_PREFIX.get(strength, 'POSSIBLE')}] {text}")
            continue
        prefix = f"[{label}] " if label in ("DESIGN", "FIELD", "OEM", "STANDARD",
                                            "CALCULATED", "INFERRED") else ""
        lines.append(prefix + str(text))
    if next_actions:
        lines.append("NEXT BEST ACTION: " + "; ".join(next_actions))
    if questions:
        lines.append("QUESTIONS: " + "; ".join(questions))
    return "\n".join(lines)


def render_safe(verification: dict[str, Any], *,
                next_actions: list[str] | None = None,
                questions: list[str] | None = None,
                missing_evidence: list[str] | None = None) -> str:
    """Render a safe visible answer (P1): when no technical claim verifies,
    return an explicit abstention - NEVER raw model prose."""
    verified = verification.get("verified") or []
    visible = render_visible(verified, next_actions=next_actions,
                             questions=questions)
    if visible.strip():
        return visible
    blocked = [r for r in verification.get("results", [])
               if r.get("verdict") in ("BLOCKED", "DOWNGRADED")]
    lines = ["I don't have verified evidence to support that technical assertion yet."]
    if blocked:
        reasons = sorted({r.get("reason") or "UNSUPPORTED" for r in blocked})
        lines.append("Blocked claims: " + "; ".join(reasons))
    if missing_evidence:
        lines.append("Missing evidence: " + "; ".join(missing_evidence))
    if next_actions:
        lines.append("NEXT BEST ACTION: " + "; ".join(next_actions))
    elif questions:
        lines.append("QUESTIONS: " + "; ".join(questions))
    else:
        lines.append("Next best action: provide the authoritative source or a "
                     "field measurement to verify this.")
    return "\n".join(lines)
