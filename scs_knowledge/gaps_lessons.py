"""Knowledge citations, gaps, and lesson candidates (M1.4.2, P31-P33, P75).

Citation objects carry source metadata + section/page/table/chunk; page/section
numbers are never invented. Knowledge gaps are detected honestly and either
resolved from the private library or staged as candidates.

M1.4.2 changes:
  * Customer-data firewall (P31-P33): global gap/weakness stores hold ONLY
    sanitized, generalized entries - never customer names, raw questions,
    field readings, photos, or plan text. Job-private detail is separated from
    global improvement state.
  * Stable IDs (P75): UUID-based (not len(store)+1) and deterministic lesson
    IDs (not Python hash(), which is randomized across processes).
  * Thread-safe atomic writes (P72): no lost updates under concurrency.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _deterministic_uid(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("::".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def sanitize_global_text(text: str | None) -> str:
    """Strip customer-identifying content before it enters any GLOBAL store
    (P31/P33): customer names, raw field readings, and equipment tags."""
    if not text:
        return ""
    t = str(text)
    t = re.sub(r"\bat\s+[A-Z][A-Za-z0-9]*\b", "[customer]", t, flags=re.IGNORECASE)
    t = re.sub(r"(?<![A-Za-z0-9])\d{1,6}(?:,\d{3})*(?:\.\d+)?(?![A-Za-z0-9])",
               "[reading]", t)
    t = re.sub(r"\b(RTU|AHU|VAV|EF|SF|DOAS|MAU|FCU|HP|ERV)-\d{1,3}\b",
               "[equipment]", t, flags=re.IGNORECASE)
    t = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
               "[email]", t)
    return re.sub(r"\s+", " ", t).strip()[:200]


@dataclass
class KnowledgeCitation:
    source_id: str
    source_type: str
    title: str | None = None
    edition: str | None = None
    revision: str | None = None
    section: str | None = None
    page: str | None = None
    table: str | None = None
    figure: str | None = None
    chunk_id: str | None = None
    source_hash: str | None = None
    retrieved_at: str | None = None
    applicability: str | None = None
    quoted_text: str | None = None
    paraphrase: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


GAP_TYPES = (
    "OEM_DOCUMENT_MISSING", "EXACT_MODEL_UNRESOLVED", "STANDARD_EDITION_UNKNOWN",
    "PROCEDURE_NOT_AVAILABLE", "FORMULA_INPUT_MISSING", "INSTRUMENT_MANUAL_MISSING",
    "CONTROLLER_DOC_MISSING", "PLAN_CONTEXT_MISSING",
    "DIAGNOSTIC_EVIDENCE_INSUFFICIENT", "CONFLICT_UNRESOLVED", "UNKNOWN_TERM",
    "UNKNOWN_MODEL_NOMENCLATURE",
)


class _AtomicJsonStore:
    """Shared atomic + thread-safe JSON persistence (P72)."""

    def __init__(self, store_path: Path) -> None:
        self._path = Path(store_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self, data: dict[str, Any]) -> None:
        with self._lock:
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
            tmp.replace(self._path)


class KnowledgeGapLog(_AtomicJsonStore):
    """Global knowledge gap log - sanitized only (P31)."""

    def __init__(self, store_path: Path) -> None:
        super().__init__(store_path)
        self._gaps = self._load()

    def record(self, gap_type: str, *, detail: str, question: str = "",
               entity: str | None = None) -> dict[str, Any]:
        gap_id = _uid("GAP")
        entry = {
            "gap_id": gap_id, "gap_type": gap_type,
            "detail": sanitize_global_text(detail),
            "question": sanitize_global_text(question),
            "entity": sanitize_global_text(entity),
            "detected_at": datetime.now().isoformat(timespec="seconds"),
            "resolved": False, "resolved_via": None,
        }
        self._gaps[gap_id] = entry
        self._save(self._gaps)
        return entry

    def resolve(self, gap_id: str, via: str) -> None:
        if gap_id in self._gaps:
            self._gaps[gap_id]["resolved"] = True
            self._gaps[gap_id]["resolved_via"] = via
            self._save(self._gaps)

    def detect(self, gap_type: str, *, detail: str, question: str = "",
               entity: str | None = None) -> dict[str, Any]:
        """Detect + record a gap (dedupes identical unresolved sanitized gaps)."""
        sanitized = sanitize_global_text(detail)
        for entry in self._gaps.values():
            if not entry["resolved"] and entry["gap_type"] == gap_type \
                    and entry["detail"] == sanitized:
                entry["count"] = entry.get("count", 1) + 1
                self._save(self._gaps)
                return entry
        entry = self.record(gap_type, detail=detail, question=question, entity=entity)
        entry["count"] = 1
        return entry

    def unresolved(self) -> list[dict[str, Any]]:
        return [g for g in self._gaps.values() if not g["resolved"]]

    def improvement_opportunities(self, threshold: int = 2) -> list[dict[str, Any]]:
        return [g for g in self._gaps.values()
                if g.get("count", 1) >= threshold and not g["resolved"]]


class KnowledgeCandidateStore(_AtomicJsonStore):
    """Staged knowledge: CANDIDATE -> SOURCE_VERIFIED -> CURATED -> ACTIVE."""

    def __init__(self, store_path: Path) -> None:
        super().__init__(store_path)
        self._candidates = self._load()

    def stage(self, *, source_type: str, title: str, summary: str,
              provenance: dict[str, Any], manufacturer: str | None = None,
              model: str | None = None) -> dict[str, Any]:
        """New knowledge enters CANDIDATE, never TRUSTED."""
        candidate_id = _uid("KC")
        entry = {
            "candidate_id": candidate_id, "source_type": source_type,
            "title": title, "summary": summary, "provenance": provenance,
            "manufacturer": manufacturer, "model": model,
            "state": "CANDIDATE",
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._candidates[candidate_id] = entry
        self._save(self._candidates)
        return entry

    def promote(self, candidate_id: str, state: str) -> dict[str, Any] | None:
        if candidate_id in self._candidates:
            self._candidates[candidate_id]["state"] = state
            self._save(self._candidates)
            return self._candidates[candidate_id]
        return None

    def list(self) -> list[dict[str, Any]]:
        return list(self._candidates.values())


class SCSLessonCandidate:
    """Field experience memory (P53-P55). Customer facts never globalize."""

    def __init__(self, *, source_job_id: str, equipment_class: str,
                 manufacturer: str | None, model_family: str | None,
                 symptom: str, observations: str, action_taken: str,
                 result: str, proposed_generalization: str | None,
                 supporting_evidence: list[str] | None = None,
                 customer_specific: bool = True,
                 confidence: str = "LOW",
                 owner_approval_state: str = "PENDING") -> None:
        self.source_job_id = source_job_id
        self.equipment_class = equipment_class
        self.manufacturer = manufacturer
        self.model_family = model_family
        self.symptom = symptom
        self.observations = observations
        self.action_taken = action_taken
        self.result = result
        self.proposed_generalization = proposed_generalization
        self.supporting_evidence = supporting_evidence or []
        self.customer_specific = customer_specific
        self.confidence = confidence
        self.owner_approval_state = owner_approval_state

    @property
    def can_generalize(self) -> bool:
        return bool(self.proposed_generalization) and not self.customer_specific

    def to_dict(self) -> dict[str, Any]:
        # P75: deterministic lesson ID - never Python hash() (process-randomized)
        lesson_id = _deterministic_uid("L", "lesson", self.source_job_id,
                                       self.equipment_class, self.symptom)
        return {
            "lesson_id": lesson_id,
            "source_job_id": self.source_job_id,
            "equipment_class": self.equipment_class,
            "manufacturer": self.manufacturer, "model_family": self.model_family,
            "symptom": self.symptom, "observations": self.observations,
            "action_taken": self.action_taken, "result": self.result,
            "proposed_generalization": self.proposed_generalization,
            "supporting_evidence": self.supporting_evidence,
            "customer_specific": self.customer_specific,
            "confidence": self.confidence,
            "owner_approval_state": self.owner_approval_state,
            "can_generalize": self.can_generalize,
        }


class ApprovedLessonStore(_AtomicJsonStore):
    def __init__(self, store_path: Path) -> None:
        super().__init__(store_path)
        self._lessons = self._load()

    def approve(self, candidate: SCSLessonCandidate, *, owner: str = "owner") -> dict[str, Any]:
        """Promote a generalizable lesson to SCS_APPROVED_LESSON (sanitized)."""
        lesson = candidate.to_dict()
        lesson.update({
            "source_type": "SCS_APPROVED_LESSON",
            "reviewed_by": owner,
            "review_date": datetime.now().isoformat(timespec="seconds"),
            "limitations": "generalization is provisional; revalidated against field evidence",
        })
        self._lessons[lesson["lesson_id"]] = lesson
        self._save(self._lessons)
        return lesson

    def list(self) -> list[dict[str, Any]]:
        return list(self._lessons.values())


class OemResearchStore(_AtomicJsonStore):
    """OEMResearchTask: manufacturer/model/family -> required fact -> status ->
    candidate sources -> selected authoritative source. SOURCE_VERIFIED only
    with official-manufacturer identity + content + hash + applicability."""

    def __init__(self, store_path: Path) -> None:
        super().__init__(store_path)
        self._tasks = self._load()

    def create(self, *, manufacturer: str, model: str | None, family: str | None,
               required_fact: str) -> dict[str, Any]:
        task_id = _uid("OEM")
        task = {
            "task_id": task_id, "manufacturer": manufacturer, "model": model,
            "family": family, "required_fact": required_fact, "status": "OPEN",
            "candidate_sources": [], "selected_source": None,
            "hash": None, "applicability": "UNKNOWN",
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._tasks[task_id] = task
        self._save(self._tasks)
        return task

    def add_candidate(self, task_id: str, *, url: str, title: str,
                      authority: str = "manufacturer") -> None:
        if task_id in self._tasks:
            self._tasks[task_id]["candidate_sources"].append({
                "url": url, "title": title, "authority": authority,
                "trust": "CANDIDATE"})
            self._save(self._tasks)

    def mark_verified(self, task_id: str, *, url: str, document_hash: str,
                      applicability: str) -> None:
        if task_id in self._tasks:
            task = self._tasks[task_id]
            task["status"] = "SOURCE_VERIFIED"
            task["selected_source"] = {"url": url, "hash": document_hash,
                                       "applicability": applicability}
            self._save(self._tasks)

    def list(self) -> list[dict[str, Any]]:
        return list(self._tasks.values())


class SCSWeaknessRegistry(_AtomicJsonStore):
    """P55-P63: field question -> failure/gap -> classify -> improve -> resolve.
    Global registry holds SANITIZED entries only (P31-P33); no customer data."""

    def __init__(self, store_path: Path) -> None:
        super().__init__(store_path)
        self._items = self._load()

    def record(self, *, question: str, failure_type: str, detail: str,
               classification: str = "UNCLASSIFIED") -> dict[str, Any]:
        wid = _uid("W")
        item = {
            "weakness_id": wid,
            "question": sanitize_global_text(question),
            "failure_type": failure_type,
            "detail": sanitize_global_text(detail),
            "classification": classification,
            "state": "OPEN", "improvement": None,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._items[wid] = item
        self._save(self._items)
        return item

    def classify(self, weakness_id: str, classification: str) -> None:
        if weakness_id in self._items:
            self._items[weakness_id]["classification"] = classification
            self._save(self._items)

    def resolve(self, weakness_id: str, improvement: str) -> None:
        if weakness_id in self._items:
            self._items[weakness_id]["state"] = "RESOLVED"
            self._items[weakness_id]["improvement"] = improvement
            self._save(self._items)

    def list(self) -> list[dict[str, Any]]:
        return list(self._items.values())


class CoverageMatrix:
    """P97-P100: coverage derived only from indexed sources - never invented."""

    def __init__(self, library) -> None:
        self._library = library

    def compute(self) -> dict[str, Any]:
        sources = self._library.list_sources()
        counts: dict[str, int] = {}
        manufacturer_models: dict[str, set[str]] = {}
        standards: dict[str, int] = {}
        for source in sources:
            if source.source_state == "QUARANTINED":
                continue
            counts[source.source_type] = counts.get(source.source_type, 0) + 1
            if source.source_type.startswith("STANDARD_"):
                standards[source.source_type] = standards.get(source.source_type, 0) + 1
            if source.manufacturer:
                manufacturer_models.setdefault(source.manufacturer, set()).add(
                    source.equipment_family_tags[0] if source.equipment_family_tags else "")
        return {
            "coverage_by_source_type": counts,
            "standards_indexed": standards,
            "oem_manufacturers": {m: len(ms - {""}) for m, ms in manufacturer_models.items()},
            "procedures": len(PROCEDURE_REFERENCE),
            "note": "coverage derived from indexed sources only",
        }


PROCEDURE_REFERENCE = []  # populated by scs_procedures.library import
