"""Structured job conversation memory (M1.4.3, P12-P20).

Per-job memory of turns, verified claims, answered + open questions, and field
readings with explicit stages (AS_FOUND / INTERMEDIATE / FINAL) and reading
identity (equipment_id, instrument_id, operating_mode). Earlier measurements
are never overwritten. Open measurement requests are resolved when the reading
arrives, so the agent never re-asks.

M1.4.3 changes:
  * Shared cross-instance job-memory lock keyed by canonical path (P12).
  * Optimistic atomic update API with deterministic merge (P13) - no lost
    updates under concurrency (P14).
  * Idempotent JobRecord seeding via stable source identity (P15), preserving
    original measurement time where available (P16).
  * Canonical entity-scoped open measurements (P18-P20): STATIC_SPLIT requires
    both static components before resolving.
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

STAGES = ("AS_FOUND", "INTERMEDIATE", "FINAL", "FIELD")

# Canonical measurement concepts (P18): synonyms resolve to one request.
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

# P20: composite requests require ALL components before resolving.
COMPOSITE_COMPONENTS = {
    "STATIC_SPLIT": ("FIELD_SUPPLY_STATIC", "FIELD_RETURN_STATIC"),
}


def canonical_measurement(phrase: str) -> str | None:
    """Resolve a freeform measurement phrase to a canonical concept (P18)."""
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
            self.record_open_measurement(measurement, "requested by agent")

    def record_reading(self, key: str, value: Any, *, source: str = "field",
                       stage: str = "FIELD", equipment_id: str | None = None,
                       instrument_id: str | None = None,
                       operating_mode: str | None = None,
                       concept: str | None = None,
                       source_key: str | None = None,
                       observed_at: str | None = None,
                       unit: str | None = None,
                       entered_by: str | None = None,
                       submitted_value: Any = None,
                       submitted_unit: str | None = None,
                       submitted_concept: str | None = None) -> dict[str, Any]:
        """Store a timestamped reading with explicit stage; never overwrite.

        M1.5B2: ``value``/``unit`` are the CANONICAL value+unit; the technician's
        original ``submitted_value``/``submitted_unit``/``submitted_concept`` are
        preserved. ``observed_at`` is when the measurement was taken (or the
        SOURCE_TIMESTAMP_UNKNOWN marker); ``recorded_at`` is server-derived.
        """
        if equipment_id:
            self.active_entity = equipment_id
        canon = concept or canonical_measurement(key)
        now = datetime.now().isoformat(timespec="seconds")
        if source_key:
            for e in self.readings.get(key, []):
                if e.get("source_key") == source_key:
                    if e.get("value") == value:
                        return e  # idempotent: same source + same value
        entry = {
            "reading_id": f"RD-{uuid.uuid4().hex[:12]}",
            "job_id": self.job_id,
            "equipment_id": equipment_id,
            "concept": canon,
            "submitted_concept": submitted_concept,
            "value": value,
            "unit": unit or "UNKNOWN_LEGACY",
            "submitted_value": submitted_value,
            "submitted_unit": submitted_unit,
            "stage": stage if stage in STAGES else "FIELD",
            "operating_mode": operating_mode, "instrument_id": instrument_id,
            "source": source,
            "entered_by": entered_by,
            "source_key": source_key,
            "observed_at": observed_at or now,
            "recorded_at": now,
        }
        self.readings.setdefault(key, []).append(entry)
        self._resolve_open(canon, equipment_id, value)
        return entry

    def record_open_measurement(self, concept: str, reason: str,
                                entity_id: str | None = None) -> None:
        """P18/P19: store under the CANONICAL concept only, scoped by entity."""
        canon = canonical_measurement(concept) or (concept or "").upper().strip()
        self.open_measurements.setdefault(canon, {
            "state": "OPEN", "reason": reason, "entity_id": entity_id,
            "requested_phrase": concept,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })

    def resolve_open_measurement(self, concept: str, value: Any) -> None:
        self.record_reading(concept, value, stage="FIELD")

    def latest_reading(self, key: str) -> Any | None:
        entries = self.readings.get(key)
        return entries[-1]["value"] if entries else None

    def _has_reading(self, component: str, entity_id: str | None) -> bool:
        for entries in self.readings.values():
            for e in entries:
                if e.get("concept") != component:
                    continue
                # P0/P2: entity-scoped lookup requires EXACT equipment identity.
                # An unscoped reading (equipment_id=None) must not satisfy an
                # entity-scoped component requirement.
                if entity_id:
                    if e.get("equipment_id") == entity_id:
                        return True
                else:
                    return True
        return False

    def _resolve_open(self, canon: str | None, equipment_id: str | None,
                      value: Any) -> None:
        if not canon:
            return
        for oc, entry in self.open_measurements.items():
            if entry.get("state") != "OPEN":
                continue
            req_entity = entry.get("entity_id")
            # P0/P1: fail-closed entity resolution. If the request is entity-
            # scoped, ONLY an exact-match reading may resolve it - a missing
            # entity (None) is NOT a wildcard.
            if req_entity and equipment_id != req_entity:
                continue
            components = COMPOSITE_COMPONENTS.get(oc)
            if components:
                # P20: composite resolves only when all components are present
                if canon in components:
                    entity = req_entity or equipment_id
                    if all(self._has_reading(c, entity) for c in components):
                        entry["state"] = "ANSWERED"
                        entry["resolved_value"] = value
            elif oc == canon:
                entry["state"] = "ANSWERED"
                entry["resolved_value"] = value

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

    def merge_from(self, working: "JobConversationMemory") -> None:
        """Deterministic merge of a working snapshot into this (current) one.

        Used by JobMemoryStore.update for optimistic concurrency (P13): new
        turns/readings are appended by unique id, so independent updates never
        lose each other's work.
        """
        known_turns = {t.get("turn_id") for t in self.turns}
        for turn in working.turns:
            if turn.get("turn_id") not in known_turns:
                self.turns.append(turn)
                known_turns.add(turn.get("turn_id"))
        for key, entries in working.readings.items():
            existing = self.readings.setdefault(key, [])
            known_ids = {e.get("reading_id") for e in existing}
            for e in entries:
                if e.get("reading_id") not in known_ids:
                    existing.append(e)
                    known_ids.add(e.get("reading_id"))
        for question in working.answered_questions:
            if question not in self.answered_questions:
                self.answered_questions.append(question)
        # open measurements: working (later) states win
        self.open_measurements.update(working.open_measurements)
        # session maps: working wins per key (job-scoped sessions)
        self.active_graphs.update(working.active_graphs)
        self.active_procedures.update(working.active_procedures)
        if working.active_entity:
            self.active_entity = working.active_entity
        if working.last_active_task:
            self.last_active_task = working.last_active_task


# ---------------------------------------------------------------------------
# Shared cross-instance lock registry (P12)
# ---------------------------------------------------------------------------

_GLOBAL_LOCKS: dict[str, threading.RLock] = {}
_GLOBAL_LOCKS_GUARD = threading.Lock()


def _shared_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _GLOBAL_LOCKS_GUARD:
        if key not in _GLOBAL_LOCKS:
            _GLOBAL_LOCKS[key] = threading.RLock()
        return _GLOBAL_LOCKS[key]


class JobMemoryCorrupt(Exception):
    """Raised when writes are attempted against a corrupt durable memory file."""

    def __init__(self, job_id: str) -> None:
        super().__init__(f"JOB_MEMORY_CORRUPT: {job_id}; writes blocked pending recovery")
        self.job_id = job_id


class JobMemoryStore:
    """Durable per-job conversation memory (P12-P14).

    Atomic structured JSON storage under the job-private boundary. Concurrency
    is protected by a process-global lock registry keyed by the canonical
    memory path, so two independent JobMemoryStore objects against the same
    job directory cannot lose updates.
    """

    def __init__(self, directory: Path) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", job_id)
        return self._dir / f"{safe}.memory.json"

    def _load_state(self, path: Path, job_id: str) -> tuple[JobConversationMemory | None, str]:
        if not path.exists():
            return JobConversationMemory(job_id=job_id), "EMPTY"
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                raise ValueError("memory state is not an object")
            memory = JobConversationMemory.from_state(state)
            memory.job_id = job_id
            return memory, "OK"
        except Exception:
            # M1.5B4: durable file truth is authoritative. Corruption is
            # explicit and write-blocked — never a silent fresh empty store.
            return None, "CORRUPT"

    def memory_state(self, job_id: str) -> str:
        path = self._path(job_id)
        with _shared_lock(path):
            _memory, state = self._load_state(path, job_id)
            return state

    def _load_or_raise(self, path: Path, job_id: str) -> JobConversationMemory:
        memory, state = self._load_state(path, job_id)
        if state == "CORRUPT":
            raise JobMemoryCorrupt(job_id)
        return memory  # EMPTY -> fresh empty memory; OK -> durable memory

    def _write_path(self, path: Path, memory: JobConversationMemory) -> None:
        tmp = path.with_name(path.name + f".{uuid.uuid4().hex[:8]}.tmp")
        tmp.write_text(json.dumps(memory.to_state(), indent=2, default=str),
                       encoding="utf-8")
        tmp.replace(path)

    def load(self, job_id: str) -> JobConversationMemory:
        path = self._path(job_id)
        with _shared_lock(path):
            return self._load_or_raise(path, job_id)

    def save(self, memory: JobConversationMemory) -> None:
        if not memory.job_id:
            return
        path = self._path(memory.job_id)
        with _shared_lock(path):
            self._load_or_raise(path, memory.job_id)  # blocks overwrite of corrupt
            self._write_path(path, memory)

    def update(self, job_id: str,
               mutator: Callable[[JobConversationMemory], None]) -> JobConversationMemory:
        """P13: atomic load -> mutate -> write under the shared lock."""
        path = self._path(job_id)
        with _shared_lock(path):
            memory = self._load_or_raise(path, job_id)
            mutator(memory)
            self._write_path(path, memory)
            return memory

    def commit(self, job_id: str,
               working: JobConversationMemory) -> JobConversationMemory:
        """Optimistic merge: merge the working snapshot onto the freshly loaded
        current state (P13). Independent updates are never lost (P14)."""
        path = self._path(job_id)
        with _shared_lock(path):
            current = self._load_or_raise(path, job_id)
            current.merge_from(working)
            self._write_path(path, current)
            return current

    def archive_corrupt_and_reset(self, job_id: str, *, actor: str = "operator") -> dict[str, Any]:
        """Explicit owner/operator recovery (B4-01/B4-03): preserve the corrupt
        durable bytes under private SCS storage with their SHA, then begin a
        fresh EMPTY memory. Never invoked automatically."""
        import hashlib
        path = self._path(job_id)
        with _shared_lock(path):
            _memory, state = self._load_state(path, job_id)
            if state != "CORRUPT":
                return {"state": state, "archived": False}
            raw = path.read_bytes()
            sha = hashlib.sha256(raw).hexdigest()
            archive_dir = self._dir / "_recovery"
            archive_dir.mkdir(parents=True, exist_ok=True)
            archive_path = archive_dir / f"{job_id}.corrupt.{sha[:16]}.json"
            archive_path.write_bytes(raw)
            path.unlink()
            return {"state": "RECOVERED", "archived": True,
                    "archive_sha": sha, "actor": actor,
                    "recovered_at": datetime.now().isoformat(timespec="seconds")}

    def delete(self, job_id: str) -> None:
        path = self._path(job_id)
        with _shared_lock(path):
            if path.exists():
                path.unlink()
            self._corrupt.discard(job_id)


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
    """Return canonical measurement requests (P18), not naive substring hits."""
    text = str(answer.get("answer") or "").lower()
    requested = []
    for concept, synonyms in CANONICAL_MEASUREMENTS.items():
        if any(s in text for s in synonyms):
            if concept not in requested:
                requested.append(concept)
    return requested
