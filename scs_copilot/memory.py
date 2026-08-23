"""Structured job conversation memory (M1.4.1, P18-P22).

Per-job memory of turns, verified claims, answered + open questions, and field
readings with explicit stages (AS_FOUND / INTERMEDIATE / FINAL) and reading
identity (equipment_id, instrument_id, operating_mode). Earlier measurements
are never overwritten. Open measurement requests are resolved when the reading
arrives, so the agent never re-asks.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

STAGES = ("AS_FOUND", "INTERMEDIATE", "FINAL", "FIELD")
_OPEN_STATES = ("OPEN", "ANSWERED", "SUPERSEDED")


class JobConversationMemory:
    def __init__(self) -> None:
        self.turns: list[dict[str, Any]] = []
        self.readings: dict[str, list[dict[str, Any]]] = {}
        self.answered_questions: list[str] = []
        self.open_measurements: dict[str, dict[str, Any]] = {}
        self.active_graphs: dict[str, Any] = {}

    def record_turn(self, question: str, answer: dict[str, Any],
                    answer_id: str | None = None, state: str | None = None,
                    facts: list[dict[str, Any]] | None = None) -> None:
        """Record a turn; mark the normalized question answered only when the
        answer is substantive (not UNKNOWN / BLOCKED / measurement request)."""
        normalized = _normalize_question(question)
        resolved = _answer_resolved(answer)
        answered = resolved and not _needs_measurement(answer)
        if answered and normalized not in self.answered_questions:
            self.answered_questions.append(normalized)
        self.turns.append({
            "turn_id": f"TURN-{len(self.turns) + 1}",
            "question": question, "normalized_intent": normalized,
            "answer_id": answer_id, "state": state,
            "verified_claims": [c.get("claim_id") for c in (facts or [])],
            "open_measurements": list(_requested_measurements(answer)),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })
        for measurement in _requested_measurements(answer):
            self.open_measurements.setdefault(measurement, {
                "state": "OPEN",
                "created_at": datetime.now().isoformat(timespec="seconds"),
            })

    def record_reading(self, key: str, value: Any, *, source: str = "field",
                       stage: str = "FIELD", equipment_id: str | None = None,
                       instrument_id: str | None = None,
                       operating_mode: str | None = None,
                       concept: str | None = None) -> None:
        """Store a timestamped reading with explicit stage; never overwrite."""
        self.readings.setdefault(key, []).append({
            "reading_id": f"RD-{len(self.readings.get(key, [])) + 1}",
            "job_id": None, "equipment_id": equipment_id, "concept": concept,
            "value": value, "unit": None, "stage": stage if stage in STAGES else "FIELD",
            "operating_mode": operating_mode, "instrument_id": instrument_id,
            "source": source,
            "recorded_at": datetime.now().isoformat(timespec="seconds"),
        })
        if key in self.open_measurements:
            self.open_measurements[key]["state"] = "ANSWERED"
            self.open_measurements[key]["resolved_value"] = value

    def record_open_measurement(self, key: str, reason: str) -> None:
        self.open_measurements.setdefault(key, {
            "state": "OPEN", "reason": reason,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })

    def resolve_open_measurement(self, key: str, value: Any) -> None:
        self.record_reading(key, value, stage="FIELD")
        if key in self.open_measurements:
            self.open_measurements[key]["state"] = "ANSWERED"

    def latest_reading(self, key: str) -> Any | None:
        entries = self.readings.get(key)
        return entries[-1]["value"] if entries else None

    def context_packet(self) -> dict[str, Any]:
        readings = {}
        for key, entries in self.readings.items():
            readings[key] = [e for e in entries[-3:]]
        return {
            "readings": readings,
            "answered_questions": list(self.answered_questions[-5:]),
            "open_measurements": {k: v for k, v in self.open_measurements.items()
                                  if v.get("state") == "OPEN"},
            "active_graphs": list(self.active_graphs),
        }


def _normalize_question(question: str) -> str:
    return " ".join(question.lower().split())[:120]


def _answer_resolved(answer: dict[str, Any]) -> bool:
    text = str(answer.get("answer") or "").upper()
    if "UNKNOWN" in text or "BLOCKED" in text:
        return False
    return bool(answer.get("facts")) or answer.get("tool") is not None


def _needs_measurement(answer: dict[str, Any]) -> bool:
    text = str(answer.get("answer") or "").upper()
    return any(k in text for k in ("NEED", "MEASURE", "NEXT BEST", "RECORD"))


def _requested_measurements(answer: dict[str, Any]) -> list[str]:
    text = str(answer.get("answer") or "").lower()
    requested = []
    for key in ("fan rpm", "supply static", "return static", "filter dp",
                "coil dp", "oa cfm", "static split", "rpm"):
        if key in text:
            requested.append(key.replace(" ", "_"))
    return requested
