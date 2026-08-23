"""Job-scoped procedure + diagnostic sessions (M1.4.2, P28-P30).

The global procedure library and diagnostic graph builders are IMMUTABLE
templates. Starting a procedure (or a diagnostic) for a job creates a
job-scoped session; updates mutate the session only. Job A can never alter the
procedure state visible to Job B, and sessions survive a service restart via
the durable JobMemoryStore.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from scs_diagnostics.graph import DiagnosticCause, DiagnosticGraph
from scs_procedures.models import ProcedureStep, SCSProcedure


class ProcedureSession:
    """Job-scoped copy of a procedure template (P28)."""

    def __init__(self, procedure: SCSProcedure, job_id: str | None = None,
                 entity: str | None = None) -> None:
        self.procedure_id = procedure.procedure_id
        self.procedure_version = procedure.version
        self.job_id = job_id
        self.entity = entity
        self.steps: list[dict[str, Any]] = [
            {"step_id": s.step_id, "title": s.title, "instruction": s.instruction,
             "required_inputs": list(s.required_inputs),
             "required_readings": list(s.required_readings),
             "provenance": s.provenance, "state": s.state, "note": s.note}
            for s in procedure.steps
        ]
        self.created_at = datetime.now().isoformat(timespec="seconds")
        self.updated_at = self.created_at

    def set_step_state(self, step_id: str, state: str, note: str | None = None) -> bool:
        for step in self.steps:
            if step["step_id"] == step_id:
                step["state"] = state
                step["note"] = note
                self.updated_at = datetime.now().isoformat(timespec="seconds")
                return True
        return False

    def current_step(self) -> dict[str, Any] | None:
        for step in self.steps:
            if step["state"] in ("NOT_STARTED", "IN_PROGRESS"):
                return step
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "procedure_id": self.procedure_id,
            "procedure_version": self.procedure_version,
            "job_id": self.job_id, "entity": self.entity,
            "steps": self.steps, "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProcedureSession":
        session = cls.__new__(cls)
        session.procedure_id = data["procedure_id"]
        session.procedure_version = data.get("procedure_version")
        session.job_id = data.get("job_id")
        session.entity = data.get("entity")
        session.steps = data.get("steps") or []
        session.created_at = data.get("created_at")
        session.updated_at = data.get("updated_at")
        return session


class DiagnosticSession:
    """Job-scoped diagnostic session that persists observations (P29)."""

    def __init__(self, graph: DiagnosticGraph, job_id: str | None = None,
                 entity: str | None = None) -> None:
        self.graph_id = graph.graph_id
        self.graph_version = getattr(graph, "schema_version", "1.0")
        self.job_id = job_id
        self.entity = entity
        self.symptom = graph.symptom
        self.observations: list[dict[str, Any]] = list(graph.observations)
        self.causes: list[dict[str, Any]] = [c.to_dict() for c in graph.causes]
        self.decision_splits: list[str] = list(graph.decision_splits)
        self.next_best_measurements: list[str] = list(graph.next_best_measurements)
        self.resolution_note: str | None = graph.resolution_note
        self.created_at = datetime.now().isoformat(timespec="seconds")
        self.updated_at = self.created_at

    def record_observation(self, key: str, value: Any, source: str) -> None:
        self.observations.append({"key": key, "value": value, "source": source})
        self.updated_at = datetime.now().isoformat(timespec="seconds")

    def update_cause(self, cause_id: str, observation: str, supports: bool,
                     basis: str) -> None:
        for cause in self.causes:
            if cause.get("cause_id") == cause_id:
                if supports:
                    cause.setdefault("supporting_observations", []).append(observation)
                else:
                    cause.setdefault("contradicting_observations", []).append(observation)
                self.updated_at = datetime.now().isoformat(timespec="seconds")
                return

    def to_graph(self) -> DiagnosticGraph:
        graph = DiagnosticGraph(
            graph_id=self.graph_id, symptom=self.symptom,
            causes=[DiagnosticCause(**{k: v for k, v in c.items()
                                       if k in DiagnosticCause.__dataclass_fields__})
                    for c in self.causes],
            observations=list(self.observations),
            decision_splits=list(self.decision_splits),
            next_best_measurements=list(self.next_best_measurements),
            resolution_note=self.resolution_note,
        )
        return graph

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id, "graph_version": self.graph_version,
            "job_id": self.job_id, "entity": self.entity, "symptom": self.symptom,
            "observations": self.observations, "causes": self.causes,
            "decision_splits": self.decision_splits,
            "next_best_measurements": self.next_best_measurements,
            "resolution_note": self.resolution_note,
            "created_at": self.created_at, "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DiagnosticSession":
        session = cls.__new__(cls)
        session.graph_id = data["graph_id"]
        session.graph_version = data.get("graph_version", "1.0")
        session.job_id = data.get("job_id")
        session.entity = data.get("entity")
        session.symptom = data.get("symptom")
        session.observations = data.get("observations") or []
        session.causes = data.get("causes") or []
        session.decision_splits = data.get("decision_splits") or []
        session.next_best_measurements = data.get("next_best_measurements") or []
        session.resolution_note = data.get("resolution_note")
        session.created_at = data.get("created_at")
        session.updated_at = data.get("updated_at")
        return session
