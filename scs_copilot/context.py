"""SCSJobContext - the runtime bundle the Copilot reasons over (M1.3, P40).

Joins JobRecord + MechanicalPlanGraph + DesignBasis + resolver results +
field measurements + photos + procedures + diagnostic state + knowledge
citations + report state. Job-aware by default; no manual context pasting.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SCSJobContext:
    job_id: str
    job: Any = None
    graph: Any = None
    design_basis: dict[str, Any] = field(default_factory=dict)
    equipment_resolved: dict[str, dict[str, Any]] = field(default_factory=dict)
    readings: dict[str, Any] = field(default_factory=dict)
    photos: list[dict[str, Any]] = field(default_factory=list)
    active_procedures: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    knowledge_citations: list[dict[str, Any]] = field(default_factory=list)
    report_state: dict[str, Any] = field(default_factory=dict)
    partial_plan: bool = False
    missing_context: list[dict[str, Any]] = field(default_factory=list)

    # ---- helpers ----------------------------------------------------------

    def design_value(self, equipment_id: str, field_name: str) -> Any:
        for equipment in self.design_basis.get("equipment", []):
            if equipment.get("tag") == equipment_id:
                return equipment.get(field_name)
        return None

    def equipment_from_graph(self, equipment_id: str) -> dict[str, Any] | None:
        if self.graph and hasattr(self.graph, "equipment"):
            return next((e for e in self.graph.equipment if e["id"] == equipment_id),
                        None)
        return None

    def record_reading(self, key: str, value: Any, source: str = "field") -> None:
        self.readings[key] = {"value": value, "source": source}

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "equipment_resolved": self.equipment_resolved,
            "readings": self.readings,
            "photos": self.photos,
            "active_procedures": {
                k: (v.to_dict() if hasattr(v, "to_dict") else v)
                for k, v in self.active_procedures.items()
            },
            "diagnostics": {
                k: (v.to_dict() if hasattr(v, "to_dict") else v)
                for k, v in self.diagnostics.items()
            },
            "knowledge_citations": self.knowledge_citations,
            "partial_plan": self.partial_plan,
            "missing_context": self.missing_context,
        }
