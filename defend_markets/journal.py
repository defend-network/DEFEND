"""Append-only decision journal.

Every ranked opportunity decision path produces an append-only decision
record. Historical content is never overwritten: corrections or amendments
are new records linked to the original via ``amendment_of``. Outcomes are
attached later by id, leaving the decision text untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from defend_markets.domain import DecisionRecord, DecisionType, NoActionReason, Outcome
from defend_markets.repositories import MarketsRepository


@dataclass(frozen=True)
class JournalEntry:
    decision_id: UUID
    record: DecisionRecord


@runtime_checkable
class DecisionSink(Protocol):
    """Append-only journal contract; amendable by linked new records only."""

    def append(
        self,
        record: DecisionRecord,
        *,
        opportunity_id: UUID | None,
        strategy_id: UUID,
        policy_id: UUID,
    ) -> JournalEntry: ...

    def amend(
        self,
        decision_id: UUID,
        *,
        thesis: str,
        counter_thesis: str | None = None,
        confidence: Decimal | None = None,
        estimated_edge: Decimal | None = None,
        invalidation: str | None = None,
        note: str | None = None,
        strategy_id: UUID,
        policy_id: UUID,
        opportunity_id: UUID | None = None,
    ) -> JournalEntry: ...

    def resolve(self, decision_id: UUID, outcome: Outcome) -> UUID: ...

    def get(self, decision_id: UUID) -> JournalEntry: ...

    def latest(self, limit: int = 50) -> list[JournalEntry]: ...


class DecisionJournal:
    def __init__(
        self,
        database: Any,
        repository: MarketsRepository | None = None,
    ) -> None:
        self._database = database
        self._repository = repository if repository is not None else MarketsRepository()

    def append(
        self,
        record: DecisionRecord,
        *,
        opportunity_id: UUID | None = None,
        strategy_id: UUID,
        policy_id: UUID,
    ) -> JournalEntry:
        with self._database.connect() as connection:
            with connection.transaction():
                decision_id = self._repository.insert_decision(
                    connection,
                    record,
                    opportunity_id=opportunity_id,
                    strategy_id=strategy_id,
                    policy_id=policy_id,
                )
        return JournalEntry(decision_id=decision_id, record=record)

    def amend(
        self,
        decision_id: UUID,
        *,
        thesis: str,
        counter_thesis: str | None = None,
        confidence: Decimal | None = None,
        estimated_edge: Decimal | None = None,
        invalidation: str | None = None,
        note: str | None = None,
        strategy_id: UUID,
        policy_id: UUID,
        opportunity_id: UUID | None = None,
    ) -> JournalEntry:
        """Corrections are new records linked to the original decision."""
        original = self.get(decision_id)
        amended = DecisionRecord(
            opportunity_id=original.record.opportunity_id if original.record.opportunity_id else None,
            strategy_key=original.record.strategy_key,
            strategy_version=original.record.strategy_version,
            policy_key=original.record.policy_key,
            policy_version=original.record.policy_version,
            decision_type=original.record.decision_type,
            reason_codes=original.record.reason_codes,
            thesis=thesis,
            counter_thesis=counter_thesis if counter_thesis is not None else original.record.counter_thesis,
            confidence=confidence if confidence is not None else original.record.confidence,
            estimated_edge=estimated_edge if estimated_edge is not None else original.record.estimated_edge,
            cost_estimate=original.record.cost_estimate,
            data_cutoff_timestamp=original.record.data_cutoff_timestamp,
            invalidation=invalidation if invalidation is not None else original.record.invalidation,
            model_version=original.record.model_version,
            amendment_of=str(decision_id),
            note=note,
        )
        return self.append(
            amended,
            opportunity_id=opportunity_id if opportunity_id is not None else (
                _uuid_or_none(original.record.opportunity_id)
            ),
            strategy_id=strategy_id,
            policy_id=policy_id,
        )

    def resolve(self, decision_id: UUID, outcome: Outcome) -> UUID:
        with self._database.connect() as connection:
            with connection.transaction():
                outcome_id = self._repository.insert_outcome(connection, outcome)
                self._repository.attach_outcome(connection, decision_id, outcome_id)
        return outcome_id

    def get(self, decision_id: UUID) -> JournalEntry:
        with self._database.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT d.decision_id, d.opportunity_id, s.strategy_key, s.version,
                           p.policy_key, p.version, d.decision_type, d.reason_codes,
                           d.thesis, d.counter_thesis, d.confidence, d.estimated_edge,
                           d.cost_estimate, d.data_cutoff_timestamp, d.invalidation,
                           d.model_version, d.created_at, d.amendment_of
                    FROM market_decisions d
                    JOIN market_strategies s ON s.strategy_id = d.strategy_id
                    JOIN market_risk_policies p ON p.policy_id = d.policy_id
                    WHERE d.decision_id = %s
                    """,
                    (decision_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise KeyError(f"decision not found: {decision_id}")
        return JournalEntry(
            decision_id=row[0],
            record=DecisionRecord(
                decision_id=str(row[0]),
                opportunity_id=str(row[1]) if row[1] else None,
                strategy_key=row[2],
                strategy_version=row[3],
                policy_key=row[4],
                policy_version=row[5],
                decision_type=DecisionType(row[6]),
                reason_codes=tuple(NoActionReason(code) for code in (row[7] or [])),
                thesis=row[8],
                counter_thesis=row[9],
                confidence=row[10],
                estimated_edge=row[11],
                cost_estimate=row[12],
                data_cutoff_timestamp=row[13],
                invalidation=row[14],
                model_version=row[15],
                created_at=row[16],
                amendment_of=str(row[17]) if row[17] else None,
            ),
        )

    def latest(self, limit: int = 50) -> list[JournalEntry]:
        with self._database.connect() as connection:
            rows = self._repository.list_decisions(connection, limit=limit)
        entries: list[JournalEntry] = []
        for row in rows:
            entries.append(
                JournalEntry(
                    decision_id=UUID(row["decision_id"]),
                    record=DecisionRecord(
                        decision_id=row["decision_id"],
                        opportunity_id=row["opportunity_id"],
                        strategy_key=str(row["strategy_key"]),
                        policy_key=str(row["policy_key"]),
                        decision_type=DecisionType(row["decision_type"]),
                        reason_codes=tuple(
                            NoActionReason(code) for code in (row["reason_codes"] or [])
                        ),
                        thesis=str(row["thesis"]),
                        confidence=row["confidence"],
                        estimated_edge=row["estimated_edge"],
                        cost_estimate=row["cost_estimate"],
                        data_cutoff_timestamp=row["data_cutoff_timestamp"],
                        model_version=row["model_version"],
                        created_at=row["created_at"],
                        amendment_of=row["amendment_of"],
                    ),
                )
            )
        return entries


def _uuid_or_none(value: str | None) -> UUID | None:
    return UUID(value) if value else None