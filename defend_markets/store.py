"""Markets store seam: persistence the decision loop depends on.

``PostgresMarketsStore`` is the real PostgreSQL implementation;
hermetic tests inject an in-memory store implementing ``MarketsStore``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, Sequence, runtime_checkable
from uuid import UUID

from defend_markets.domain import Opportunity, RiskPolicy, TTMatchResult
from defend_markets.repositories import MarketsRepository


@runtime_checkable
class MarketsStore(Protocol):
    def load_policy(self, policy_key: str, version: int = 1) -> RiskPolicy: ...

    def strategy_id(self, strategy_key: str) -> UUID: ...

    def policy_id(self, policy_key: str) -> UUID: ...

    def insert_opportunity(self, opportunity: Opportunity) -> UUID: ...

    def ensure_instrument(self, opportunity: Opportunity) -> None: ...

    def catalog_instruments(self, desk: str | None = None) -> list[dict[str, object]]: ...

    def catalog_events(self) -> list[dict[str, object]]: ...

    def catalog_policies(self) -> list[dict[str, object]]: ...

    def catalog_strategies(self) -> list[dict[str, object]]: ...

    def catalog_opportunities(self, limit: int = 50) -> list[dict[str, object]]: ...

    def catalog_decisions(self, limit: int = 50) -> list[dict[str, object]]: ...

    def catalog_outcomes(self, limit: int = 500) -> list[dict[str, object]]: ...

    def catalog_quality(self, limit: int = 50) -> list[dict[str, object]]: ...

    def catalog_tt_results(self, limit: int = 2000) -> list[dict[str, object]]: ...

    def counts(self) -> dict[str, int]: ...


class PostgresMarketsStore:
    def __init__(
        self,
        database: Any,
        repository: MarketsRepository | None = None,
    ) -> None:
        self._database = database
        self._repository = repository if repository is not None else MarketsRepository()

    def load_policy(self, policy_key: str, version: int = 1) -> RiskPolicy:
        with self._database.connect() as connection:
            with connection.transaction():
                return self._repository.load_policy(connection, policy_key, version)

    def strategy_id(self, strategy_key: str) -> UUID:
        with self._database.connect() as connection:
            with connection.transaction():
                return self._repository.strategy_id(connection, strategy_key)

    def policy_id(self, policy_key: str) -> UUID:
        with self._database.connect() as connection:
            with connection.transaction():
                return self._repository.policy_id(connection, policy_key)

    def insert_opportunity(self, opportunity: Opportunity) -> UUID:
        with self._database.connect() as connection:
            with connection.transaction():
                return self._repository.insert_opportunity(connection, opportunity)

    def ensure_instrument(self, opportunity: Opportunity) -> None:
        from defend_markets.domain import InstrumentStatus, InstrumentType, MarketInstrument

        parts = opportunity.instrument_key.split(":")
        event_key = parts[1] if len(parts) > 1 else opportunity.instrument_key
        with self._database.connect() as connection:
            with connection.transaction():
                instrument = MarketInstrument(
                    instrument_key=opportunity.instrument_key,
                    instrument_type=InstrumentType.SPORTS_MARKET,
                    display_name=f"{event_key} {opportunity.direction}",
                    venue_key="sports-fixture",
                    status=InstrumentStatus.ACTIVE,
                    taxonomy={
                        "desk": "sports",
                        "event_key": event_key,
                        "strategy": opportunity.strategy_key,
                    },
                )
                self._repository.upsert_instrument(connection, instrument)

    def catalog_instruments(self, desk: str | None = None) -> list[dict[str, object]]:
        with self._database.connect() as connection:
            return self._repository.list_instruments(connection, desk=desk)

    def catalog_events(self) -> list[dict[str, object]]:
        with self._database.connect() as connection:
            return self._repository.list_events(connection)

    def catalog_policies(self) -> list[dict[str, object]]:
        with self._database.connect() as connection:
            return self._repository.list_policies(connection)

    def catalog_strategies(self) -> list[dict[str, object]]:
        with self._database.connect() as connection:
            return self._repository.list_strategies(connection)

    def catalog_opportunities(self, limit: int = 50) -> list[dict[str, object]]:
        with self._database.connect() as connection:
            return self._repository.list_opportunities(connection, limit=limit)

    def catalog_decisions(self, limit: int = 50) -> list[dict[str, object]]:
        with self._database.connect() as connection:
            return self._repository.list_decisions(connection, limit=limit)

    def catalog_outcomes(self, limit: int = 500) -> list[dict[str, object]]:
        with self._database.connect() as connection:
            return self._repository.list_outcomes(connection, limit=limit)

    def catalog_quality(self, limit: int = 50) -> list[dict[str, object]]:
        with self._database.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT q.quality_id, i.instrument_key, q.venue_key, q.score,
                           q.freshness_ok, q.availability, q.as_of
                    FROM market_data_quality q
                    JOIN market_instruments i ON i.instrument_id = q.instrument_id
                    ORDER BY q.as_of DESC LIMIT %s
                    """,
                    (limit,),
                )
                return [
                    {
                        "quality_id": str(row[0]),
                        "instrument_key": row[1],
                        "venue_key": row[2],
                        "score": row[3],
                        "freshness_ok": row[4],
                        "availability": row[5],
                        "as_of": row[6],
                    }
                    for row in cursor.fetchall()
                ]

    def catalog_tt_results(self, limit: int = 2000) -> list[dict[str, object]]:
        with self._database.connect() as connection:
            return self._repository.list_tt_results(connection, limit=limit)

    def upsert_feed(self, definition: Any) -> None:
        with self._database.connect() as connection:
            with connection.transaction():
                self._repository.upsert_feed(
                    connection, definition.provider_id, definition.display_name
                )

    def record_probe(self, result: Any, *, observed_at: datetime) -> None:
        with self._database.connect() as connection:
            with connection.transaction():
                self._repository.record_feed_probe(
                    connection,
                    result.provider_id,
                    status=result.status,
                    observed_at=observed_at,
                    error=result.error,
                    latency_ms=result.latency_ms,
                    detail=result.detail,
                    records_ingested=result.record_count,
                    last_record_at=observed_at if result.records else None,
                )

    def insert_records(
        self, provider_id: str, records: Sequence[Any], *, received_at: datetime
    ) -> int:
        with self._database.connect() as connection:
            with connection.transaction():
                return self._repository.insert_feed_records(
                    connection,
                    provider_id,
                    [
                        {
                            "record_key": record.record_key,
                            "payload": dict(record.payload),
                            "observed_at": record.observed_at,
                        }
                        for record in records
                    ],
                    received_at=received_at,
                )

    def record_tt_results(self, results: Sequence[TTMatchResult]) -> int:
        with self._database.connect() as connection:
            with connection.transaction():
                for result in results:
                    self._repository.upsert_tt_result(connection, result)
                return len(results)

    def list_feeds(self) -> list[dict[str, object]]:
        with self._database.connect() as connection:
            return self._repository.list_feeds(connection)

    def list_records(self, provider_id: str, limit: int = 50) -> list[dict[str, object]]:
        with self._database.connect() as connection:
            return self._repository.list_feed_records(connection, provider_id, limit=limit)

    def counts(self) -> dict[str, int]:
        tables = (
            "market_instruments",
            "market_events",
            "market_strategies",
            "market_risk_policies",
            "market_opportunities",
            "market_decisions",
            "market_outcomes",
            "market_data_quality",
            "provider_feeds",
            "market_feed_records",
            "tt_match_results",
        )
        with self._database.connect() as connection:
            return {
                table: self._repository.count_rows(connection, table) for table in tables
            }