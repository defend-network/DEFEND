"""SCSProcedure object model (M1.3, P20-P24).

Procedures are structured (steps, decision points, stop conditions, report
fields, citations) - not prose-only RAG. Each step tracks state. Steps know
their provenance (STANDARD_REQUIREMENT / OEM_REQUIREMENT / SCS_PRACTICE).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

STEP_STATES = ("NOT_STARTED", "IN_PROGRESS", "COMPLETE", "SKIPPED_WITH_REASON",
               "BLOCKED", "REVIEW_REQUIRED")


@dataclass
class ProcedureStep:
    step_id: str
    title: str
    instruction: str
    required_inputs: list[str] = field(default_factory=list)
    required_readings: list[str] = field(default_factory=list)
    provenance: str = "SCS_PRACTICE"  # STANDARD_REQUIREMENT / OEM_REQUIREMENT / SCS_PRACTICE
    state: str = "NOT_STARTED"
    note: str | None = None

    def set_state(self, state: str, note: str | None = None) -> None:
        assert state in STEP_STATES, state
        self.state = state
        self.note = note


@dataclass
class SCSProcedure:
    procedure_id: str
    version: str
    title: str
    scope: str
    equipment_classes: list[str] = field(default_factory=list)
    system_types: list[str] = field(default_factory=list)
    applicable_instruments: list[str] = field(default_factory=list)
    required_inputs: list[str] = field(default_factory=list)
    required_preconditions: list[str] = field(default_factory=list)
    required_readings: list[str] = field(default_factory=list)
    optional_readings: list[str] = field(default_factory=list)
    steps: list[ProcedureStep] = field(default_factory=list)
    decision_points: list[str] = field(default_factory=list)
    stop_conditions: list[str] = field(default_factory=list)
    safety_notes: list[str] = field(default_factory=list)
    common_failure_modes: list[str] = field(default_factory=list)
    report_fields: list[str] = field(default_factory=list)
    standard_citations: list[str] = field(default_factory=list)
    oem_citations: list[str] = field(default_factory=list)
    owner_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "procedure_id": self.procedure_id, "version": self.version,
            "title": self.title, "scope": self.scope,
            "equipment_classes": self.equipment_classes,
            "system_types": self.system_types,
            "applicable_instruments": self.applicable_instruments,
            "required_inputs": self.required_inputs,
            "required_preconditions": self.required_preconditions,
            "required_readings": self.required_readings,
            "optional_readings": self.optional_readings,
            "steps": [{"step_id": s.step_id, "title": s.title,
                       "instruction": s.instruction,
                       "required_inputs": s.required_inputs,
                       "required_readings": s.required_readings,
                       "provenance": s.provenance, "state": s.state, "note": s.note}
                      for s in self.steps],
            "decision_points": self.decision_points,
            "stop_conditions": self.stop_conditions,
            "safety_notes": self.safety_notes,
            "common_failure_modes": self.common_failure_modes,
            "report_fields": self.report_fields,
            "standard_citations": self.standard_citations,
            "oem_citations": self.oem_citations,
        }

    def current_step(self) -> ProcedureStep | None:
        for step in self.steps:
            if step.state in ("NOT_STARTED", "IN_PROGRESS"):
                return step
        return None

    def blocked(self) -> bool:
        return any(s.state == "BLOCKED" for s in self.steps)

    def progress(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for step in self.steps:
            counts[step.state] = counts.get(step.state, 0) + 1
        return counts
