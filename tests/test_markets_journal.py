from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from defend_markets.domain import (
    DecisionRecord,
    DecisionType,
    NoActionReason,
    Outcome,
)
from defend_markets.journal import DecisionJournal

from tests.fakes_markets import InMemoryJournal

HAS_DATABASE_URL = bool(os.environ.get("MARKETS_TEST_DATABASE_URL"))

pytestmark_db = pytest.mark.skipif(
    not HAS_DATABASE_URL,
    reason="MARKETS_TEST_DATABASE_URL not configured; DB-gated tests skipped",
)

DETERMINISTIC_CUTOFF = datetime(2026, 8, 16, 12, 0, 0, tzinfo=timezone.utc)


def _record(data_cutoff_timestamp: datetime | None = DETERMINISTIC_CUTOFF) -> DecisionRecord:
    return DecisionRecord(
        opportunity_id=str(uuid4()),
        strategy_key="tt_two_way_arb",
        strategy_version=1,
        policy_key="markets_core",
        policy_version=1,
        decision_type=DecisionType.NO_ACTION,
        reason_codes=(NoActionReason.COSTS_UNACCOUNTED,),
        thesis="Arb edge present but execution costs unknown.",
        confidence=Decimal("0.9"),
        estimated_edge=None,
        cost_estimate=None,
        data_cutoff_timestamp=data_cutoff_timestamp,
    )


class TestJournalContractHermetic:
    def test_append_is_immutable(self):
        journal = InMemoryJournal()
        entry = journal.append(
            _record(),
            opportunity_id=uuid4(),
            strategy_id=uuid4(),
            policy_id=uuid4(),
        )
        assert journal.get(entry.decision_id).record is entry.record
        assert len(journal.entries) == 1

    def test_amendment_links_new_record_to_original(self):
        journal = InMemoryJournal()
        original = journal.append(
            _record(),
            opportunity_id=uuid4(),
            strategy_id=uuid4(),
            policy_id=uuid4(),
        )
        amended = journal.amend(
            original.decision_id,
            thesis="Corrected thesis after recheck.",
            note="typo fix",
            strategy_id=uuid4(),
            policy_id=uuid4(),
        )
        assert amended.decision_id != original.decision_id
        assert amended.record.amendment_of == str(original.decision_id)
        assert original.record.thesis != amended.record.thesis
        assert original.record.thesis == "Arb edge present but execution costs unknown."
        assert journal.amendments_of(original.decision_id) == [amended.decision_id]

    def test_resolve_attaches_outcome_without_mutating_decision(self):
        journal = InMemoryJournal()
        decision_id = uuid4()
        entry = journal.append(
            _record(),
            opportunity_id=uuid4(),
            strategy_id=uuid4(),
            policy_id=uuid4(),
        )
        outcome = Outcome(decision_id=str(decision_id), result="WON", pnl=Decimal("0.01"))
        outcome_id = journal.resolve(entry.decision_id, outcome)
        assert isinstance(outcome_id, UUID)
        assert journal.get(entry.decision_id).record.outcome is None

    def test_latest_returns_most_recent_first(self):
        journal = InMemoryJournal()
        first = journal.append(
            _record(),
            opportunity_id=None,
            strategy_id=uuid4(),
            policy_id=uuid4(),
        )
        second = journal.append(
            _record(),
            opportunity_id=None,
            strategy_id=uuid4(),
            policy_id=uuid4(),
        )
        assert [entry.decision_id for entry in journal.latest()] == [first.decision_id, second.decision_id]


@pytestmark_db
class TestDecisionJournalPostgres:
    def test_append_get_roundtrip(self):
        from defend_markets.db import MarketsDatabase

        database = MarketsDatabase(os.environ["MARKETS_TEST_DATABASE_URL"])
        database.migrate()
        journal = DecisionJournal(database)

        from defend_markets.repositories import MarketsRepository

        repository = MarketsRepository()
        with database.connect() as connection:
            with connection.transaction():
                repository.seed_defaults(connection)
                strategy_id = repository.strategy_id(connection, "tt_two_way_arb")
                policy_id = repository.policy_id(connection, "markets_core")

        record = _record()
        entry = journal.append(
            record,
            opportunity_id=None,
            strategy_id=strategy_id,
            policy_id=policy_id,
        )
        fetched = journal.get(entry.decision_id)
        assert fetched.record.strategy_key == "tt_two_way_arb"
        assert fetched.record.policy_key == "markets_core"
        assert fetched.record.decision_type is DecisionType.NO_ACTION
        assert fetched.record.reason_codes == (NoActionReason.COSTS_UNACCOUNTED,)
        assert fetched.record.data_cutoff_timestamp == DETERMINISTIC_CUTOFF

    def test_amendment_chain_persists(self):
        from defend_markets.db import MarketsDatabase

        database = MarketsDatabase(os.environ["MARKETS_TEST_DATABASE_URL"])
        database.migrate()
        journal = DecisionJournal(database)

        from defend_markets.repositories import MarketsRepository

        repository = MarketsRepository()
        with database.connect() as connection:
            with connection.transaction():
                repository.seed_defaults(connection)
                strategy_id = repository.strategy_id(connection, "tt_two_way_arb")
                policy_id = repository.policy_id(connection, "markets_core")

        original = journal.append(
            _record(),
            opportunity_id=None,
            strategy_id=strategy_id,
            policy_id=policy_id,
        )
        amended = journal.amend(
            original.decision_id,
            thesis="Revised thesis.",
            strategy_id=strategy_id,
            policy_id=policy_id,
        )
        assert amended.record.amendment_of == str(original.decision_id)
        fetched_amendment = journal.get(amended.decision_id)
        assert fetched_amendment.record.amendment_of == str(original.decision_id)

    def test_resolve_attaches_outcome(self):
        from defend_markets.db import MarketsDatabase

        database = MarketsDatabase(os.environ["MARKETS_TEST_DATABASE_URL"])
        database.migrate()
        journal = DecisionJournal(database)

        from defend_markets.repositories import MarketsRepository

        repository = MarketsRepository()
        with database.connect() as connection:
            with connection.transaction():
                repository.seed_defaults(connection)
                strategy_id = repository.strategy_id(connection, "tt_two_way_arb")
                policy_id = repository.policy_id(connection, "markets_core")

        entry = journal.append(
            _record(),
            opportunity_id=None,
            strategy_id=strategy_id,
            policy_id=policy_id,
        )
        outcome = Outcome(
            decision_id=str(entry.decision_id),
            result="UNREALIZED",
        )
        outcome_id = journal.resolve(entry.decision_id, outcome)
        assert isinstance(outcome_id, UUID)

    def test_append_rejects_missing_data_cutoff(self):
        from defend_markets.db import MarketsDatabase

        database = MarketsDatabase(os.environ["MARKETS_TEST_DATABASE_URL"])
        database.migrate()
        journal = DecisionJournal(database)

        from defend_markets.repositories import MarketsRepository

        repository = MarketsRepository()
        with database.connect() as connection:
            with connection.transaction():
                repository.seed_defaults(connection)
                strategy_id = repository.strategy_id(connection, "tt_two_way_arb")
                policy_id = repository.policy_id(connection, "markets_core")

        with pytest.raises(ValueError, match="data_cutoff_timestamp"):
            journal.append(
                _record(data_cutoff_timestamp=None),
                opportunity_id=None,
                strategy_id=strategy_id,
                policy_id=policy_id,
            )

    def test_get_unknown_decision_raises(self):
        from defend_markets.db import MarketsDatabase

        database = MarketsDatabase(os.environ["MARKETS_TEST_DATABASE_URL"])
        database.migrate()
        journal = DecisionJournal(database)
        with pytest.raises(KeyError):
            journal.get(UUID(int=0))