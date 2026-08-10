from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from .memory_store import MemoryProposal, MemoryRecord, MemoryStore


class MemoryCommitError(RuntimeError):
    pass


_NAMESPACE_RE = re.compile(r"^[a-z0-9][a-z0-9_.:\-]{0,95}$")


@dataclass(frozen=True)
class CommitResult:
    memory: MemoryRecord
    was_duplicate: bool


class MemoryManager:
    """Gatekeeper for durable memory: propose -> validate -> commit."""

    def __init__(self, store: MemoryStore):
        self.store = store

    def propose(self, *, namespace: str, subject: str, predicate: str, value: Any,
                value_text: str | None = None, confidence: float = 1.0,
                sensitivity: str = "internal", origin: str = "model",
                provenance: list[dict[str, Any]] | None = None) -> MemoryProposal:
        namespace = namespace.strip().lower()
        subject = subject.strip()
        predicate = predicate.strip()
        if not _NAMESPACE_RE.fullmatch(namespace):
            raise ValueError("Invalid memory namespace")
        if not subject:
            raise ValueError("subject is required")
        if not predicate:
            raise ValueError("predicate is required")
        if not 0.0 <= float(confidence) <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        return self.store.create_proposal(
            namespace=namespace,
            subject=subject,
            predicate=predicate,
            value=value,
            value_text=str(value) if value_text is None else value_text,
            confidence=float(confidence),
            sensitivity=sensitivity,
            origin=origin,
            provenance=list(provenance or []),
        )

    def commit(self, proposal_id: str, *, approved_by: str, allow_restricted: bool = False,
               valid_from: str | None = None, valid_to: str | None = None,
               supersedes_memory_id: str | None = None) -> CommitResult:
        proposal = self.store.get_proposal(proposal_id)
        if proposal.status != "pending":
            raise MemoryCommitError(f"Proposal is not pending: {proposal.status}")
        if proposal.origin == "model" and not proposal.provenance:
            raise MemoryCommitError("Model-originated durable memory requires provenance before commit.")
        if proposal.sensitivity == "restricted" and not allow_restricted:
            raise MemoryCommitError("Restricted memory requires explicit allow_restricted approval.")
        existing = self.store.find_active_by_fingerprint(proposal.fingerprint)
        memory = self.store.commit_proposal(
            proposal_id,
            reviewed_by=approved_by,
            valid_from=valid_from,
            valid_to=valid_to,
            supersedes_memory_id=supersedes_memory_id,
        )
        return CommitResult(memory=memory, was_duplicate=existing is not None)

    def reject(self, proposal_id: str, *, approved_by: str, reason: str) -> None:
        self.store.reject_proposal(proposal_id, reviewed_by=approved_by, reason=reason)

    def search(self, query: str, *, namespaces: Iterable[str] | None = None,
               subject: str | None = None, limit: int = 8) -> list[MemoryRecord]:
        return self.store.search(query, namespaces=namespaces, subject=subject, limit=limit)
