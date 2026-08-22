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
