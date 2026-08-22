"""Governed read-only tools the Quant Director uses to answer questions.

Every tool reads current database state and never exposes raw SQL, a shell,
or arbitrary filesystem access. Values are reported as-is; absence is reported
explicitly rather than fabricated.
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
