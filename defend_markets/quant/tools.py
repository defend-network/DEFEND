"""Governed read-only tools the Quant Director uses to answer questions.

Every tool reads current database state through typed, bounded queries and
never exposes raw SQL, a shell, or arbitrary filesystem access. Values are
reported as-is; absence is reported explicitly rather than fabricated.
"""

from __future__ import annotations

from typing import Any


class GovernedMarketTools:
    def __init__(self, store: Any, *, weights_doc: dict[str, Any] | None = None) -> None:
        self._store = store
        self._weights_doc = weights_doc

    def current_blocking_layers(self) -> dict[str, Any]:
        raise NotImplementedError

    def provider_state(self) -> dict[str, Any]:
        raise NotImplementedError

    def price_observations(self) -> dict[str, Any]:
        raise NotImplementedError

    def active_tt_events(self, limit: int = 50) -> list[dict[str, Any]]:
        raise NotImplementedError

    def market_observations_summary(self) -> dict[str, Any]:
        raise NotImplementedError

    def m5_predictions_summary(self) -> dict[str, Any]:
        raise NotImplementedError

    def player_history(self, player_key: str, limit: int = 100) -> dict[str, Any]:
        raise NotImplementedError

    def settled_events(self, limit: int = 50) -> list[dict[str, Any]]:
        raise NotImplementedError

    def journal_summary(self) -> dict[str, Any]:
        raise NotImplementedError

    def calibration_summary(self) -> dict[str, Any]:
        raise NotImplementedError

    def market_disagreement_summary(self) -> dict[str, Any]:
        raise NotImplementedError

    def data_freshness(self) -> dict[str, Any]:
        raise NotImplementedError

    def missing_data_stats(self) -> dict[str, Any]:
        raise NotImplementedError

    def drift_indicators(self) -> dict[str, Any]:
        raise NotImplementedError

    def m5_champion(self) -> dict[str, Any] | None:
        return self._store.champion()

    def model_registry(self) -> list[dict[str, Any]]:
        return self._store.list_models()

    def research_entries(self) -> list[dict[str, Any]]:
        return self._store.list_research_entries()

    def all_tool_state(self) -> dict[str, Any]:
        return {
            "blocking_layers": self.current_blocking_layers(),
            "provider_state": self.provider_state(),
            "prices": self.price_observations(),
            "champion": self.m5_champion(),
            "registry": self.model_registry(),
            "research": self.research_entries(),
        }


class PostgresMarketTools(GovernedMarketTools):
    """Read-only tools over the live Markets database."""

    def __init__(self, database: Any, store: Any, *, weights_doc: dict[str, Any] | None = None) -> None:
        super().__init__(store, weights_doc=weights_doc)
        self._database = database

    def _counts(self) -> dict[str, int]:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM tt_forward_events")
            events = int(cursor.fetchone()[0])
            cursor.execute("SELECT count(*) FROM tt_forward_events WHERE canonical_event_id IS NOT NULL")
            matched = int(cursor.fetchone()[0])
            cursor.execute("SELECT count(*) FROM tt_m5_live_predictions WHERE availability = 'AVAILABLE'")
            predictions = int(cursor.fetchone()[0])
            cursor.execute("SELECT count(*) FROM tt_market_observations")
            observations = int(cursor.fetchone()[0])
            cursor.execute("SELECT count(DISTINCT bookmaker) FROM tt_market_observations")
            bookmakers = int(cursor.fetchone()[0])
        return {
            "events": events,
            "matched": matched,
            "predictions": predictions,
            "observations": observations,
            "bookmakers": bookmakers,
        }

    def current_blocking_layers(self) -> dict[str, Any]:
        counts = self._counts()
        if counts["events"] == 0:
            return {"primary": "event_discovery", "details": "no forward TT events discovered"}
        if counts["observations"] == 0:
            return {
                "primary": "provider_tt_price_coverage",
                "details": "events are matched but no bookmaker returns usable TT prices",
            }
        return {"primary": "none", "details": "no blocking layer detected"}

    def provider_state(self) -> dict[str, Any]:
        counts = self._counts()
        return {
            "healthy": True,
            "events_discovered": counts["events"],
            "events_matched": counts["matched"],
            "available_predictions": counts["predictions"],
        }

    def price_observations(self) -> dict[str, Any]:
        counts = self._counts()
        return {
            "observations": counts["observations"],
            "bookmakers_with_prices": counts["bookmakers"],
        }

    def active_tt_events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT provider_event_id, canonical_event_id, competition, "
                "player_a_key, player_b_key, scheduled_commence, match_level, state "
                "FROM tt_forward_events ORDER BY scheduled_commence LIMIT %s",
                (max(1, min(limit, 200)),),
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def market_observations_summary(self) -> dict[str, Any]:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM tt_market_observations")
            total = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT observation_class, count(*) FROM tt_market_observations GROUP BY observation_class"
            )
            by_class = {str(row[0]): int(row[1]) for row in cursor.fetchall()}
        return {"total": total, "by_class": by_class}

    def m5_predictions_summary(self) -> dict[str, Any]:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT availability, count(*) FROM tt_m5_live_predictions GROUP BY availability"
            )
            by_availability = {str(row[0]): int(row[1]) for row in cursor.fetchall()}
        return {"by_availability": by_availability}

    def player_history(self, player_key: str, limit: int = 100) -> dict[str, Any]:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT event_key, completed_at, home_participant_key, away_participant_key, "
                "home_score, away_score FROM tt_match_results "
                "WHERE home_participant_key = %s OR away_participant_key = %s "
                "ORDER BY completed_at DESC LIMIT %s",
                (player_key, player_key, max(1, min(limit, 500))),
            )
            columns = [column.name for column in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return {"player_key": player_key, "count": len(rows), "rows": rows}

    def settled_events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT event_key, home_participant_key, away_participant_key, "
                "home_score, away_score, completed_at FROM tt_match_results "
                "WHERE home_score IS NOT NULL AND away_score IS NOT NULL "
                "ORDER BY completed_at DESC LIMIT %s",
                (max(1, min(limit, 200)),),
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def journal_summary(self) -> dict[str, Any]:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM tt_predictions")
            predictions = int(cursor.fetchone()[0])
            cursor.execute("SELECT count(*) FROM tt_settlements")
            settled = int(cursor.fetchone()[0])
            cursor.execute("SELECT count(*) FROM market_decisions")
            decisions = int(cursor.fetchone()[0])
        return {"predictions": predictions, "settled": settled, "paper_decisions": decisions}

    def calibration_summary(self) -> dict[str, Any]:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM tt_shadow_evaluation WHERE m5_p_a IS NOT NULL AND actual IS NOT NULL"
            )
            rows = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT count(*) FROM tt_shadow_evaluation WHERE m5_brier IS NOT NULL"
            )
            with_brier = int(cursor.fetchone()[0])
        return {"evaluation_rows": rows, "with_brier": with_brier}

    def market_disagreement_summary(self) -> dict[str, Any]:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM tt_market_ruler_rows WHERE model_market_disagreement IS NOT NULL"
            )
            rows = int(cursor.fetchone()[0])
        return {"ruler_rows_with_disagreement": rows}

    def data_freshness(self) -> dict[str, Any]:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT max(last_seen_at) FROM tt_forward_events")
            events_seen = cursor.fetchone()[0]
            cursor.execute("SELECT max(observed_at) FROM tt_market_observations")
            odds_seen = cursor.fetchone()[0]
            cursor.execute("SELECT max(completed_at) FROM tt_match_results")
            results_seen = cursor.fetchone()[0]
        return {
            "events_last_seen": str(events_seen) if events_seen else None,
            "odds_last_seen": str(odds_seen) if odds_seen else None,
            "results_last_seen": str(results_seen) if results_seen else None,
        }

    def missing_data_stats(self) -> dict[str, Any]:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM tt_forward_events WHERE canonical_event_id IS NULL")
            unmatched = int(cursor.fetchone()[0])
            cursor.execute("SELECT count(*) FROM tt_forward_events")
            total = int(cursor.fetchone()[0])
        return {"unmatched_events": unmatched, "total_events": total}

    def drift_indicators(self) -> dict[str, Any]:
        counts = self._counts()
        return {
            "note": "deterministic counters only; statistical drift requires historical snapshots",
            "events": counts["events"],
            "observations": counts["observations"],
            "predictions": counts["predictions"],
        }


class InMemoryMarketTools(GovernedMarketTools):
    """Fixture-driven tools for tests and the mock runtime."""

    def __init__(
        self,
        store: Any,
        *,
        weights_doc: dict[str, Any] | None = None,
        events_discovered: int = 0,
        events_matched: int = 0,
        available_predictions: int = 0,
        price_observations: int = 0,
        bookmakers_with_prices: int = 0,
        provider_healthy: bool = True,
    ) -> None:
        super().__init__(store, weights_doc=weights_doc)
        self._events_discovered = events_discovered
        self._events_matched = events_matched
        self._available_predictions = available_predictions
        self._price_observations = price_observations
        self._bookmakers_with_prices = bookmakers_with_prices
        self._provider_healthy = provider_healthy

    def current_blocking_layers(self) -> dict[str, Any]:
        if not self._provider_healthy:
            return {"primary": "provider_health", "details": "provider reported unhealthy"}
        if self._price_observations == 0:
            if self._events_discovered > 0:
                return {
                    "primary": "provider_tt_price_coverage",
                    "details": "events are discovered but no bookmaker returns usable TT prices",
                }
            return {"primary": "event_discovery", "details": "no TT events discovered"}
        return {"primary": "none", "details": "no blocking layer detected"}

    def provider_state(self) -> dict[str, Any]:
        return {
            "healthy": self._provider_healthy,
            "events_discovered": self._events_discovered,
            "events_matched": self._events_matched,
            "available_predictions": self._available_predictions,
        }

    def price_observations(self) -> dict[str, Any]:
        return {
            "observations": self._price_observations,
            "bookmakers_with_prices": self._bookmakers_with_prices,
        }

    def active_tt_events(self, limit: int = 50) -> list[dict[str, Any]]:
        return []

    def market_observations_summary(self) -> dict[str, Any]:
        return {"total": self._price_observations, "by_class": {}}

    def m5_predictions_summary(self) -> dict[str, Any]:
        return {"by_availability": {"AVAILABLE": self._available_predictions}}

    def player_history(self, player_key: str, limit: int = 100) -> dict[str, Any]:
        return {"player_key": player_key, "count": 0, "rows": []}

    def settled_events(self, limit: int = 50) -> list[dict[str, Any]]:
        return []

    def journal_summary(self) -> dict[str, Any]:
        return {"predictions": 0, "settled": 0, "paper_decisions": 0}

    def calibration_summary(self) -> dict[str, Any]:
        return {"evaluation_rows": 0, "with_brier": 0}

    def market_disagreement_summary(self) -> dict[str, Any]:
        return {"ruler_rows_with_disagreement": 0}

    def data_freshness(self) -> dict[str, Any]:
        return {"events_last_seen": None, "odds_last_seen": None, "results_last_seen": None}

    def missing_data_stats(self) -> dict[str, Any]:
        return {"unmatched_events": self._events_discovered - self._events_matched, "total_events": self._events_discovered}

    def drift_indicators(self) -> dict[str, Any]:
        return {
            "note": "fixture",
            "events": self._events_discovered,
            "observations": self._price_observations,
            "predictions": self._available_predictions,
        }
