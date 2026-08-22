"""DiagnosticGraph model (M1.3, P27-P30).

Not an LLM list of possibilities: explicit symptoms, candidate causes with
belief states, supporting/contradicting observations, required measurements,
decision splits, risk, source basis. Evidence updates are deterministic
qualitative grades (UNASSESSED/POSSIBLE/SUPPORTED/STRONGLY_SUPPORTED/
CONTRADICTED/RESOLVED) - no fake probabilities without a calibrated basis.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

BELIEFS = ("UNASSESSED", "POSSIBLE", "SUPPORTED", "STRONGLY_SUPPORTED",
           "CONTRADICTED", "RESOLVED")


@dataclass
class DiagnosticCause:
    cause_id: str
    description: str
    belief: str = "UNASSESSED"
    supporting_observations: list[str] = field(default_factory=list)
    contradicting_observations: list[str] = field(default_factory=list)
    required_measurements: list[str] = field(default_factory=list)
    risk: str = "LOW"
    source_basis: list[str] = field(default_factory=list)

    def update(self, observation: str, supports: bool, basis: str) -> None:
        if supports:
            self.supporting_observations.append(observation)
            order = ["UNASSESSED", "POSSIBLE", "SUPPORTED", "STRONGLY_SUPPORTED"]
            if self.belief in order:
                self.belief = order[min(order.index(self.belief) + 1,
                                        len(order) - 1)]
        else:
            self.contradicting_observations.append(observation)
            if self.belief in ("SUPPORTED", "STRONGLY_SUPPORTED"):
                self.belief = "POSSIBLE"
            elif self.belief in ("POSSIBLE", "UNASSESSED"):
                self.belief = "CONTRADICTED"
        if basis and basis not in self.source_basis:
            self.source_basis.append(basis)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class DiagnosticGraph:
    graph_id: str
    symptom: str
    causes: list[DiagnosticCause] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)
    decision_splits: list[str] = field(default_factory=list)
    next_best_measurements: list[str] = field(default_factory=list)
    resolution_note: str | None = None

    def cause(self, cause_id: str) -> DiagnosticCause | None:
        return next((c for c in self.causes if c.cause_id == cause_id), None)

    def record_observation(self, key: str, value: Any, source: str) -> None:
        self.observations.append({"key": key, "value": value, "source": source})

    def update_cause(self, cause_id: str, observation: str, supports: bool,
                     basis: str) -> None:
        cause = self.cause(cause_id)
        if cause:
            cause.update(observation, supports, basis)

    def unresolved_causes(self) -> list[DiagnosticCause]:
        return [c for c in self.causes
                if c.belief in ("UNASSESSED", "POSSIBLE", "SUPPORTED",
                                "STRONGLY_SUPPORTED")]

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id, "symptom": self.symptom,
            "causes": [c.to_dict() for c in self.causes],
            "observations": self.observations,
            "decision_splits": self.decision_splits,
            "next_best_measurements": self.next_best_measurements,
            "resolution_note": self.resolution_note,
        }
