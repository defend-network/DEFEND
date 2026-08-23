"""Deterministic ready-to-leave engine (M1.5, P20-P23).

Not an LLM judgment. A deterministic state machine that evaluates the actual
job truth: report-required fields (from the existing completeness evaluator),
open measurement requests, active procedures, active diagnostics and
unresolved conflicts. Each result carries explicit reasons; UNKNOWN is never
treated as N/A.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .completeness import evaluate
from .schema import JobRecord

READY_STATES = ("NOT_READY", "NEEDS_REVIEW", "READY_WITH_NOTES", "READY")

_UNRESOLVED_BELIEFS = ("UNASSESSED", "POSSIBLE", "SUPPORTED", "STRONGLY_SUPPORTED")
_INCOMPLETE_PROCEDURE_STATES = ("NOT_STARTED", "IN_PROGRESS")


@dataclass
class ReadinessReason:
    key: str
    severity: str  # BLOCKING | IMPORTANT | OPTIONAL
    label: str
    action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "severity": self.severity,
                "label": self.label, "action": self.action}


@dataclass
class ReadinessResult:
    state: str = "NOT_READY"
    reasons: list[ReadinessReason] = field(default_factory=list)

    def blocking(self) -> list[ReadinessReason]:
        return [r for r in self.reasons if r.severity == "BLOCKING"]

    def important(self) -> list[ReadinessReason]:
        return [r for r in self.reasons if r.severity == "IMPORTANT"]

    def optional(self) -> list[ReadinessReason]:
        return [r for r in self.reasons if r.severity == "OPTIONAL"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "readiness": self.state.replace("_", " "),
            "reasons": [r.to_dict() for r in self.reasons],
            "BLOCKING": [r.to_dict() for r in self.blocking()],
            "IMPORTANT": [r.to_dict() for r in self.important()],
            "OPTIONAL": [r.to_dict() for r in self.optional()],
        }


def evaluate_readiness(record: JobRecord, *, graph: Any | None = None,
                       memory: Any | None = None) -> ReadinessResult:
    """Evaluate ready-to-leave state deterministically (P20-P23)."""
    result = ReadinessResult()
    base = evaluate(record)

    # 1) report-required fields (BLOCKING/IMPORTANT from completeness)
    for item in base.items:
        if item.status == "BLOCKING":
            result.reasons.append(ReadinessReason(
                key=item.field, severity="BLOCKING", label=item.reason,
                action=_action_for(item.field)))
        elif item.status == "IMPORTANT":
            result.reasons.append(ReadinessReason(
                key=item.field, severity="IMPORTANT", label=item.reason,
                action=_action_for(item.field)))

    if memory is not None:
        # 2) open measurement requests block leaving site
        for concept, entry in getattr(memory, "open_measurements", {}).items():
            if entry.get("state") == "OPEN":
                entity = entry.get("entity_id") or "equipment"
                result.reasons.append(ReadinessReason(
                    key=f"open_measurement:{concept}", severity="BLOCKING",
                    label=f"{concept} still required for {entry.get('entity_id') or 'equipment'}",
                    action="Enter the requested reading"))

        # 3) active procedures must be complete
        for procedure_id, session in getattr(memory, "active_procedures", {}).items():
            steps = session.get("steps", []) if isinstance(session, dict) else []
            incomplete = [s.get("step_id") for s in steps
                          if s.get("state") in _INCOMPLETE_PROCEDURE_STATES]
            if incomplete:
                result.reasons.append(ReadinessReason(
                    key=f"procedure:{procedure_id}", severity="BLOCKING",
                    label=f"procedure {procedure_id} incomplete (steps: {', '.join(incomplete)})",
                    action="Complete the active procedure"))

        # 4) active diagnostics must be resolved
        for graph_id, session in getattr(memory, "active_graphs", {}).items():
            causes = session.get("causes", []) if isinstance(session, dict) else []
            unresolved = [c.get("cause_id") for c in causes
                          if c.get("belief") in _UNRESOLVED_BELIEFS]
            if unresolved:
                result.reasons.append(ReadinessReason(
                    key=f"diagnostic:{graph_id}", severity="IMPORTANT",
                    label=f"diagnostic {graph_id} unresolved ({', '.join(unresolved)})",
                    action="Resolve the active diagnostic"))

    # 5) unresolved graph conflicts
    if graph is not None:
        conflicts = getattr(graph, "conflicts", None)
        if conflicts:
            result.reasons.append(ReadinessReason(
                key="conflicts", severity="IMPORTANT",
                label=f"{len(conflicts)} unresolved conflict(s)",
                action="Review and resolve document conflicts"))

    result.state = _state_for(result)
    return result


def _action_for(field: str) -> str:
    if field == "air_devices" or field.startswith("planned_devices"):
        return "Capture final airflow readings"
    if ":final_cfm" in field:
        return "Record the final CFM for this device"
    if ":design_cfm" in field:
        return "Provide the design airflow"
    if ":as_found_cfm" in field:
        return "Record the as-found reading"
    if field == "photos":
        return "Attach job photos"
    if field in ("project_name", "site_name", "technician", "test_date"):
        return "Complete job metadata"
    return "Resolve this item"


def _state_for(result: ReadinessResult) -> str:
    if result.blocking():
        return "NOT_READY"
    if result.important():
        return "NEEDS_REVIEW"
    if result.optional():
        return "READY_WITH_NOTES"
    return "READY"
