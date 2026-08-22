"""SCS knowledge source model + question-dependent authority (M1.3, P0-P2).

Separates FACTS / CALCULATIONS / PROCEDURES / DIAGNOSTIC HYPOTHESES /
REFERENCE KNOWLEDGE / JOB EVIDENCE / LESSONS / AI INFERENCE - these never
silently collapse. Every fact carries a semantic concept (DESIGN_ vs FIELD_
vs OEM_) and a visible provenance label.
"""
from __future__ import annotations

from typing import Any

SOURCE_TYPES = (
    "FIELD_MEASUREMENT", "PROJECT_PLAN", "PROJECT_SPECIFICATION",
    "PROJECT_SCHEDULE", "PROJECT_NOTE", "OEM_IOM", "OEM_SERVICE_MANUAL",
    "OEM_ENGINEERING_DATA", "OEM_SUBMITTAL", "OEM_CATALOG",
    "STANDARD_NEBB", "STANDARD_AABC", "STANDARD_ASHRAE", "STANDARD_SMACNA",
    "INSTRUMENT_MANUAL", "SCS_APPROVED_PLAYBOOK", "SCS_APPROVED_LESSON",
    "CURRENT_RESEARCH_PRIMARY", "CURRENT_RESEARCH_SECONDARY",
    "BASE_MODEL_KNOWLEDGE",
)

# visible fact-provenance labels (P2)
FACT_LABELS = ("DESIGN", "FIELD", "OEM", "STANDARD", "CALCULATED",
               "SCS_PLAYBOOK", "RESEARCHED", "INFERRED", "UNKNOWN", "CONFLICT")

# semantic concept types (P60) - prevents false conflicts across categories
CONCEPT_TYPES = {
    "DESIGN_SUPPLY_CFM", "FIELD_SUPPLY_CFM", "OEM_NOMINAL_CFM",
    "DESIGN_RPM", "FIELD_RPM", "OEM_MAX_RPM",
    "DESIGN_ESP", "FIELD_TESP", "OEM_MAX_ESP",
    "DESIGN_OA_CFM", "FIELD_OA_CFM", "OEM_DESIGN_CFM",
    "DESIGN_TOTAL_CFM", "FIELD_TOTAL_CFM",
    "DESIGN_HEAT_CFM", "DESIGN_COOL_CFM",
    "DESIGN_VAV_MIN", "DESIGN_VAV_MAX", "FIELD_VAV_CFM",
    "DESIGN_EXHAUST_CFM", "FIELD_EXHAUST_CFM",
}


def fact_concept(kind: str, field: str) -> str:
    """Map (kind, field) to a semantic concept type."""
    upper = field.upper()
    base = "CFM" if "CFM" in upper else (
        "RPM" if "RPM" in upper else (
            "ESP" if "ESP" in upper or "STATIC" in upper else upper))
    if kind == "DESIGN":
        return f"DESIGN_{base}"
    if kind == "FIELD":
        return f"FIELD_{base}"
    if kind == "OEM":
        return f"OEM_{base}"
    return f"{kind}_{base}"


def is_same_concept(a: str, b: str) -> bool:
    return a == b


class SourceAuthorityContext:
    """Question-dependent source authority (P1) - no universal ranking."""

    def authority_order(self, question: str) -> list[str]:
        upper = question.upper()
        if any(k in upper for k in ("DESIGN", "SCHEDULE", "PLAN", "ENGINEER",
                                    "WHAT IS THE DESIGN", "SCHEDULED")):
            return ["PROJECT_PLAN", "PROJECT_SCHEDULE", "PROJECT_SPECIFICATION",
                    "PROJECT_NOTE", "OEM_ENGINEERING_DATA", "OEM_CATALOG"]
        if any(k in upper for k in ("MEASURE", "READ", "ACTUAL", "FIELD",
                                    "WE MEASURED", "OUR READING")):
            return ["FIELD_MEASUREMENT", "PROJECT_NOTE", "PROJECT_PLAN"]
        if any(k in upper for k in ("ALLOW", "MANUFACTURER", "OEM", "MOTOR",
                                    "CONFIGURATION", "MAX", "LIMIT", "DRIVE")):
            return ["OEM_IOM", "OEM_SERVICE_MANUAL", "OEM_ENGINEERING_DATA",
                    "OEM_SUBMITTAL", "OEM_CATALOG", "PROJECT_SPECIFICATION"]
        if any(k in upper for k in ("NEBB", "AABC", "ASHRAE", "SMACNA",
                                    "STANDARD", "REQUIRE", "TOLERANCE", "PROCEDURE")):
            return ["STANDARD_NEBB", "STANDARD_AABC", "STANDARD_ASHRAE",
                    "STANDARD_SMACNA", "SCS_APPROVED_PLAYBOOK"]
        if any(k in upper for k in ("TROUBLE", "WHY", "DIAGNOSE", "LOW",
                                    "HIGH", "NEXT", "CHECK")):
            return ["FIELD_MEASUREMENT", "PROJECT_PLAN", "PROJECT_SCHEDULE",
                    "OEM_IOM", "STANDARD_NEBB", "SCS_APPROVED_LESSON"]
        return ["PROJECT_PLAN", "PROJECT_SCHEDULE", "PROJECT_NOTE",
                "OEM_IOM", "STANDARD_NEBB", "SCS_APPROVED_PLAYBOOK",
                "BASE_MODEL_KNOWLEDGE"]

    def rank(self, question: str, source_type: str) -> int:
        order = self.authority_order(question)
        return order.index(source_type) if source_type in order else len(order)


class KnowledgeFact:
    """A single sourced fact with concept + provenance + label."""

    def __init__(self, concept: str, value: Any, unit: str | None,
                 label: str, *, source_id: str | None = None,
                 source_type: str | None = None, citation: dict[str, Any] | None = None,
                 confidence: str = "HIGH", job_id: str | None = None) -> None:
        self.concept = concept
        self.value = value
        self.unit = unit
        self.label = label
        self.source_id = source_id
        self.source_type = source_type
        self.citation = citation
        self.confidence = confidence
        self.job_id = job_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept": self.concept, "value": self.value, "unit": self.unit,
            "label": self.label, "source_id": self.source_id,
            "source_type": self.source_type, "citation": self.citation,
            "confidence": self.confidence, "job_id": self.job_id,
        }
