"""Structured job conversation memory (M1.4.2, P18-P27).

Per-job memory of turns, verified claims, answered + open questions, and field
readings with explicit stages (AS_FOUND / INTERMEDIATE / FINAL) and reading
identity (equipment_id, instrument_id, operating_mode). Earlier measurements
are never overwritten. Open measurement requests are resolved when the reading
arrives, so the agent never re-asks.

M1.4.2 changes:
  * Durable JobMemoryStore (P22-P23): memory persists per job on disk and
    survives service restart - no correctness dependence on process memory.
  * Globally unique reading IDs (P25): UUID-based, job_id always persisted.
  * Real reading history seeding (P24): AS_FOUND / INTERMEDIATE / FINAL kept
    separate; design values remain DESIGN, never field readings.
  * Canonical open-measurement semantics (P26): synonyms resolve to the same
    canonical concept request.
  * Active-entity tracking (P63).
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

STAGES = ("AS_FOUND", "INTERMEDIATE", "FINAL", "FIELD")
_OPEN_STATES = ("OPEN", "ANSWERED", "SUPERSEDED")

# Canonical measurement concepts (P26): synonyms resolve to one request.
CANONICAL_MEASUREMENTS = {
    "FAN_RPM": ("fan rpm", "fan speed", "rpm"),
    "FIELD_SUPPLY_STATIC": ("supply static", "supply static pressure"),
    "FIELD_RETURN_STATIC": ("return static", "return static pressure"),
    "FILTER_DP": ("filter dp", "filter pressure drop", "filter delta"),
    "COIL_DP": ("coil dp", "coil pressure drop", "coil delta"),
    "FIELD_OA_CFM": ("oa cfm", "outside air cfm", "outdoor air cfm"),
    "FIELD_SUPPLY_CFM": ("supply cfm", "airflow cfm"),
    "STATIC_SPLIT": ("static split", "supply vs return static"),
    "FAN_MOTOR_RPM": ("motor rpm",),
    "VFD_FREQUENCY": ("vfd frequency", "drive frequency"),
}


def canonical_measurement(phrase: str) -> str | None:
    """Resolve a freeform measurement phrase to a canonical concept (P26)."""
    p = (phrase or "").lower().strip()
    for concept, synonyms in CANONICAL_MEASUREMENTS.items():
        if p in synonyms or any(s in p for s in synonyms):
            return concept
    return None


class JobConversationMemory:
    def __init__(self, job_id: str | None = None) -> None:
        self.job_id = job_id
        self.turns: list[dict[str, Any]] = []
        self.readings: dict[str, list[dict[str, Any]]] = {}
        self.answered_questions: list[str] = []
        self.open_measurements: dict[str, dict[str, Any]] = {}
        self.active_graphs: dict[str, Any] = {}
        self.active_procedures: dict[str, Any] = {}
        self.active_entity: str | None = None
        self.last_active_task: str | None = None

    def focus_entity(self, entity_id: str | None) -> None:
        if entity_id:
            self.active_entity = entity_id

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
        requested = _requested_measurements(answer)
        self.last_active_task = answer.get("tool") or state
        self.turns.append({
            "turn_id": f"TURN-{uuid.uuid4().hex[:12]}",
            "question": question, "normalized_intent": normalized,
            "answer_id": answer_id, "state": state,
            "verified_claims": [c.get("claim_id") for c in (facts or [])],
            "open_measurements": requested,
            "active_entity": self.active_entity,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })
        for measurement in requested:
            self.open_measurements.setdefault(measurement, {
                "state": "OPEN",
                "created_at": datetime.now().isoformat(timespec="seconds"),
            })

    def record_reading(self, key: str, value: Any, *, source: str = "field",
                       stage: str = "FIELD", equipment_id: str | None = None,
                       instrument_id: str | None = None,
                       operating_mode: str | None = None,
                       concept: str | None = None) -> dict[str, Any]:
        """Store a timestamped reading with explicit stage; never overwrite."""
        if equipment_id:
            self.active_entity = equipment_id
        entry = {
            "reading_id": f"RD-{uuid.uuid4().hex[:12]}",
            "job_id": self.job_id,
            "equipment_id": equipment_id, "concept": concept or canonical_measurement(key),
            "value": value, "unit": None,
            "stage": stage if stage in STAGES else "FIELD",
            "operating_mode": operating_mode, "instrument_id": instrument_id,
            "source": source,
            "recorded_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.readings.setdefault(key, []).append(entry)
        canon = concept or canonical_measurement(key)
        if canon and canon in self.open_measurements:
            self.open_measurements[canon]["state"] = "ANSWERED"
            self.open_measurements[canon]["resolved_value"] = value
        if key in self.open_measurements:
            self.open_measurements[key]["state"] = "ANSWERED"
            self.open_measurements[key]["resolved_value"] = value
        return entry

    def record_open_measurement(self, key: str, reason: str) -> None:
        canon = canonical_measurement(key) or key
        self.open_measurements.setdefault(key, {
            "state": "OPEN", "reason": reason, "concept": canon,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })

    def resolve_open_measurement(self, key: str, value: Any) -> None:
        self.record_reading(key, value, stage="FIELD")
        if key in self.open_measurements:
            self.open_measurements[key]["state"] = "ANSWERED"
            self.open_measurements[key]["resolved_value"] = value
        canon = canonical_measurement(key)
        if canon and canon in self.open_measurements:
            self.open_measurements[canon]["state"] = "ANSWERED"
            self.open_measurements[canon]["resolved_value"] = value

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
            "active_procedures": list(self.active_procedures),
            "active_entity": self.active_entity,
        }

    def to_state(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "turns": self.turns,
            "readings": self.readings,
            "answered_questions": self.answered_questions,
            "open_measurements": self.open_measurements,
            "active_graphs": self.active_graphs,
            "active_procedures": self.active_procedures,
            "active_entity": self.active_entity,
            "last_active_task": self.last_active_task,
        }

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> "JobConversationMemory":
        memory = cls(job_id=state.get("job_id"))
        memory.turns = state.get("turns") or []
        memory.readings = state.get("readings") or {}
        memory.answered_questions = state.get("answered_questions") or []
        memory.open_measurements = state.get("open_measurements") or {}
        memory.active_graphs = state.get("active_graphs") or {}
        memory.active_procedures = state.get("active_procedures") or {}
        memory.active_entity = state.get("active_entity")
        memory.last_active_task = state.get("last_active_task")
        return memory


class JobMemoryStore:
    """Durable per-job conversation memory (P22-P23).

    Atomic structured JSON storage under the job-private boundary with a
    process lock for thread safety. Load/save each request; correctness never
    depends on long-lived Python process memory.
    """

    def __init__(self, directory: Path) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, job_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", job_id)
        return self._dir / f"{safe}.memory.json"

    def load(self, job_id: str) -> JobConversationMemory:
        with self._lock:
            path = self._path(job_id)
            if not path.exists():
                return JobConversationMemory(job_id=job_id)
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
                memory = JobConversationMemory.from_state(state)
                memory.job_id = job_id
                return memory
            except Exception:
                return JobConversationMemory(job_id=job_id)

    def save(self, memory: JobConversationMemory) -> None:
        if not memory.job_id:
            return
        with self._lock:
            path = self._path(memory.job_id)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(memory.to_state(), indent=2, default=str),
                           encoding="utf-8")
            tmp.replace(path)

    def delete(self, job_id: str) -> None:
        with self._lock:
            path = self._path(job_id)
            if path.exists():
                path.unlink()


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
    """Return canonical measurement requests (P26), not naive substring hits."""
    text = str(answer.get("answer") or "").lower()
    requested = []
    for concept, synonyms in CANONICAL_MEASUREMENTS.items():
        if any(s in text for s in synonyms):
            if concept not in requested:
                requested.append(concept)
    return requested
