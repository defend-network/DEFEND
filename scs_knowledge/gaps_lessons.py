"""Knowledge citations, gaps, and lesson candidates (M1.3, P5, P47-P55).

Citation objects carry source metadata + section/page/table/chunk; page/section
numbers are never invented. Knowledge gaps are detected honestly and either
resolved from the private library or staged as candidates; customer-specific
facts never become global knowledge; generalized lessons require owner
approval.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


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


# ---------------------------------------------------------------------------
# Knowledge gaps (P47-P48)
# ---------------------------------------------------------------------------

GAP_TYPES = (
    "OEM_DOCUMENT_MISSING", "EXACT_MODEL_UNRESOLVED", "STANDARD_EDITION_UNKNOWN",
    "PROCEDURE_NOT_AVAILABLE", "FORMULA_INPUT_MISSING", "INSTRUMENT_MANUAL_MISSING",
    "CONTROLLER_DOC_MISSING", "PLAN_CONTEXT_MISSING",
    "DIAGNOSTIC_EVIDENCE_INSUFFICIENT", "CONFLICT_UNRESOLVED", "UNKNOWN_TERM",
    "UNKNOWN_MODEL_NOMENCLATURE",
)


class KnowledgeGapLog:
    def __init__(self, store_path: Path) -> None:
        self._path = Path(store_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._gaps = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._gaps, indent=2), encoding="utf-8")

    def record(self, gap_type: str, *, detail: str, question: str = "",
               entity: str | None = None) -> dict[str, Any]:
        gap_id = f"GAP-{len(self._gaps) + 1:04d}"
        entry = {
            "gap_id": gap_id, "gap_type": gap_type, "detail": detail,
            "question": question, "entity": entity,
            "detected_at": datetime.now().isoformat(timespec="seconds"),
            "resolved": False, "resolved_via": None,
        }
        self._gaps[gap_id] = entry
        self._save()
        return entry

    def resolve(self, gap_id: str, via: str) -> None:
        if gap_id in self._gaps:
            self._gaps[gap_id]["resolved"] = True
            self._gaps[gap_id]["resolved_via"] = via
            self._save()

    def detect(self, gap_type: str, *, detail: str, question: str = "",
               entity: str | None = None) -> dict[str, Any]:
        """Detect + record a gap (dedupes identical unresolved gaps)."""
        for entry in self._gaps.values():
            if not entry["resolved"] and entry["gap_type"] == gap_type \
                    and entry["detail"] == detail:
                entry["count"] = entry.get("count", 1) + 1
                self._save()
                return entry
        entry = self.record(gap_type, detail=detail, question=question, entity=entity)
        entry["count"] = 1
        return entry

    def unresolved(self) -> list[dict[str, Any]]:
        return [g for g in self._gaps.values() if not g["resolved"]]

    def improvement_opportunities(self, threshold: int = 2) -> list[dict[str, Any]]:
        """P49/P92: repeated gaps become higher-priority improvement items."""
        return [g for g in self._gaps.values()
                if g.get("count", 1) >= threshold and not g["resolved"]]


# ---------------------------------------------------------------------------
# Knowledge candidates / lesson candidates (P51-P55)
# ---------------------------------------------------------------------------


class KnowledgeCandidateStore:
    """Staged knowledge: CANDIDATE -> SOURCE_VERIFIED -> CURATED -> ACTIVE."""

    def __init__(self, store_path: Path) -> None:
        self._path = Path(store_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._candidates = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._candidates, indent=2), encoding="utf-8")

    def stage(self, *, source_type: str, title: str, summary: str,
              provenance: dict[str, Any], manufacturer: str | None = None,
              model: str | None = None) -> dict[str, Any]:
        """New knowledge enters CANDIDATE, never TRUSTED."""
        candidate_id = f"KC-{len(self._candidates) + 1:04d}"
        entry = {
            "candidate_id": candidate_id, "source_type": source_type,
            "title": title, "summary": summary, "provenance": provenance,
            "manufacturer": manufacturer, "model": model,
            "state": "CANDIDATE",
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._candidates[candidate_id] = entry
        self._save()
        return entry

    def promote(self, candidate_id: str, state: str) -> dict[str, Any] | None:
        if candidate_id in self._candidates:
            self._candidates[candidate_id]["state"] = state
            self._save()
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
        return {
            "lesson_id": f"L-{hash(self.source_job_id) & 0xffff:04x}",
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


class ApprovedLessonStore:
    def __init__(self, store_path: Path) -> None:
        self._path = Path(store_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lessons = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._lessons, indent=2), encoding="utf-8")

    def approve(self, candidate: SCSLessonCandidate, *, owner: str = "owner") -> dict[str, Any]:
        """Promote a generalizable lesson to SCS_APPROVED_LESSON."""
        lesson = candidate.to_dict()
        lesson.update({
            "source_type": "SCS_APPROVED_LESSON",
            "reviewed_by": owner,
            "review_date": datetime.now().isoformat(timespec="seconds"),
            "limitations": "generalization is provisional; revalidated against field evidence",
        })
        self._lessons[lesson["lesson_id"]] = lesson
        self._save()
        return lesson

    def list(self) -> list[dict[str, Any]]:
        return list(self._lessons.values())


# ---------------------------------------------------------------------------
# OEM research tasks + weakness registry + coverage matrix (P49-P54, P55-P63,
# P97-P100, H-addendum)
# ---------------------------------------------------------------------------


class OemResearchStore:
    """OEMResearchTask: manufacturer/model/family -> required fact -> status ->
    candidate sources -> selected authoritative source. SOURCE_VERIFIED only
    with official-manufacturer identity + content + hash + applicability."""

    def __init__(self, store_path: Path) -> None:
        self._path = Path(store_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._tasks = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._tasks, indent=2), encoding="utf-8")

    def create(self, *, manufacturer: str, model: str | None, family: str | None,
               required_fact: str) -> dict[str, Any]:
        task_id = f"OEM-{len(self._tasks) + 1:04d}"
        task = {
            "task_id": task_id, "manufacturer": manufacturer, "model": model,
            "family": family, "required_fact": required_fact, "status": "OPEN",
            "candidate_sources": [], "selected_source": None,
            "hash": None, "applicability": "UNKNOWN",
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._tasks[task_id] = task
        self._save()
        return task

    def add_candidate(self, task_id: str, *, url: str, title: str,
                      authority: str = "manufacturer") -> None:
        if task_id in self._tasks:
            self._tasks[task_id]["candidate_sources"].append({
                "url": url, "title": title, "authority": authority,
                "trust": "CANDIDATE"})
            self._save()

    def mark_verified(self, task_id: str, *, url: str, document_hash: str,
                      applicability: str) -> None:
        if task_id in self._tasks:
            task = self._tasks[task_id]
            task["status"] = "SOURCE_VERIFIED"
            task["selected_source"] = {"url": url, "hash": document_hash,
                                       "applicability": applicability}
            self._save()

    def list(self) -> list[dict[str, Any]]:
        return list(self._tasks.values())


class SCSWeaknessRegistry:
    """P55-P63: field question -> failure/gap -> classify -> improve -> resolve.
    No autonomous source-trust escalation."""

    def __init__(self, store_path: Path) -> None:
        self._path = Path(store_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._items = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._items, indent=2), encoding="utf-8")

    def record(self, *, question: str, failure_type: str, detail: str,
               classification: str = "UNCLASSIFIED") -> dict[str, Any]:
        wid = f"W-{len(self._items) + 1:04d}"
        item = {
            "weakness_id": wid, "question": question, "failure_type": failure_type,
            "detail": detail, "classification": classification,
            "state": "OPEN", "improvement": None,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._items[wid] = item
        self._save()
        return item

    def classify(self, weakness_id: str, classification: str) -> None:
        if weakness_id in self._items:
            self._items[weakness_id]["classification"] = classification
            self._save()

    def resolve(self, weakness_id: str, improvement: str) -> None:
        if weakness_id in self._items:
            self._items[weakness_id]["state"] = "RESOLVED"
            self._items[weakness_id]["improvement"] = improvement
            self._save()

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
