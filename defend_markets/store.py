"""Markets store seam: persistence the decision loop depends on.

``PostgresMarketsStore`` is the real PostgreSQL implementation;
hermetic tests inject an in-memory store implementing ``MarketsStore``.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from defend_markets.domain import Opportunity, RiskPolicy
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

    def catalog_quality(self, limit: int = 50) -> list[dict[str, object]]: ...

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
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT strategy_id FROM market_strategies
                    WHERE strategy_key = %s ORDER BY version DESC LIMIT 1
                    """,
                    (strategy_key,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise KeyError(f"strategy not seeded: {strategy_key}")
                return row[0]

    def policy_id(self, policy_key: str) -> UUID:
        with self._database.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT policy_id FROM market_risk_policies
                    WHERE policy_key = %s ORDER BY version DESC LIMIT 1
                    """,
                    (policy_key,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise KeyError(f"policy not seeded: {policy_key}")
                return row[0]

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
        )
        with self._database.connect() as connection:
            return {
                table: self._repository.count_rows(connection, table) for table in tables
            }