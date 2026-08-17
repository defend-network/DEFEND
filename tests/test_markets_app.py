from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re

import pytest
from fastapi.testclient import TestClient

from defend_markets import app as app_module
from defend_markets.app import MarketsDependencies
from defend_markets.config import MarketsSettings
from defend_markets.models import ReasonerRegistry
from defend_markets.strategies import build_default_registry

from tests.fakes_markets import FakeSportsReader, InMemoryJournal, InMemoryStore, arb_pair, default_policies

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)

_SOURCES_ROOT = Path(__file__).resolve().parents[1] / "defend_markets"

_FORBIDDEN_MODEL_ID_PATTERNS = (
    re.compile(r"\bqwen[0-9.-]*\b", re.IGNORECASE),
    re.compile(r"\bkimi[0-9.-]*\b", re.IGNORECASE),
    re.compile(r"\bdeepseek[0-9.-]*\b", re.IGNORECASE),
    re.compile(r"\bgpt[0-9][a-z0-9.-]*\b", re.IGNORECASE),
    re.compile(r"\bclaude[0-9.-]*\b", re.IGNORECASE),
    re.compile(r"\bgemini[0-9.-]*\b", re.IGNORECASE),
    re.compile(r"\bllama[0-9.-]*\b", re.IGNORECASE),
    re.compile(r"\bmistral[0-9.-]*\b", re.IGNORECASE),
)


def test_no_hard_coded_model_ids_in_markets_domain_logic():
    offenders: list[str] = []
    for path in sorted(_SOURCES_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for pattern in _FORBIDDEN_MODEL_ID_PATTERNS:
                if pattern.search(line):
                    offenders.append(f"{path.name}:{line_number}: {line.strip()}")
    assert offenders == [], (
        "hard-coded model identifiers leaked into DEFENDmarkets sources: "
        + "; ".join(offenders)
    )


def test_model_version_stays_none_when_no_reasoner_invoked():
    reasoners = ReasonerRegistry()
    assert reasoners.get("null").label == "null"
    assert reasoners.labels() == ()


def test_reasoner_registry_is_abstraction_only():
    source_text = (_SOURCES_ROOT / "models.py").read_text(encoding="utf-8")
    assert "class Reasoner" in source_text
    assert "NullReasoner" in source_text


def test_strategy_registry_uses_no_hard_coded_models():
    registry = build_default_registry()
    definitions = registry.list()
    assert definitions
    for definition in definitions:
        assert definition.lifecycle is not None
        assert definition.source_ref is not None


def _build_dependencies(reader: FakeSportsReader | None = None) -> MarketsDependencies:
    settings = MarketsSettings(
        data_root=Path("."), database_url="postgresql://f:f@localhost:1/markets"
    )
    store = InMemoryStore()
    for strategy_key in ("tt_two_way_arb", "tt_clv"):
        store.register_strategy(strategy_key)
    for policy in default_policies().values():
        store.register_policy(policy)
    return MarketsDependencies(
        settings=settings,
        database=None,
        sports_database=None,
        reader=reader,
        store=store,
        journal=InMemoryJournal(),
        registry=build_default_registry(),
        reasoners=ReasonerRegistry(),
        clock=lambda: NOW,
    )


class TestApiHermetic:
    def test_health_endpoint_reports_unavailable_database_honestly(self):
        app = app_module.build_markets_app(_build_dependencies())
        response = TestClient(app).get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["application_id"] == "markets"
        assert body["ok"] is False
        assert body["database"] == "unavailable"

    def test_desks_endpoint_lists_sports_ready_and_others_pending(self):
        app = app_module.build_markets_app(_build_dependencies())
        body = TestClient(app).get("/v1/desks").json()
        assert body["sports"]["available"] is True
        assert body["equities"]["available"] is False
        assert body["equities"]["status"] == "pending"

    def test_overview_reports_zero_decisions_without_reader(self):
        app = app_module.build_markets_app(_build_dependencies())
        body = TestClient(app).get("/v1/overview").json()
        assert body["application_id"] == "markets"
        assert body["counts"]["market_decisions"] == 0
        assert body["pit_availability"] == []

    def test_evaluate_without_reader_is_503(self):
        app = app_module.build_markets_app(_build_dependencies())
        response = TestClient(app).post(
            "/v1/evaluate/sports",
            json={"event_key": "tt-live-001", "market_key": "match_winner"},
        )
        assert response.status_code == 503

    def test_evaluate_no_action_when_costs_unknown(self):
        reader = FakeSportsReader(quotes={("tt-live-001", "match_winner"): arb_pair()})
        app = app_module.build_markets_app(_build_dependencies(reader))
        response = TestClient(app).post(
            "/v1/evaluate/sports",
            json={"event_key": "tt-live-001", "market_key": "match_winner"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["decision_type"] == "NO_ACTION"
        assert "costs_unaccounted" in body["reason_codes"]
        assert body["policy_version"] == 1

    def test_evaluate_opportunity_when_costs_known(self):
        reader = FakeSportsReader(
            quotes={("tt-live-001", "match_winner"): arb_pair(fees="0.001")}
        )
        app = app_module.build_markets_app(_build_dependencies(reader))
        response = TestClient(app).post(
            "/v1/evaluate/sports",
            json={"event_key": "tt-live-001", "market_key": "match_winner"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["decision_type"] == "OPPORTUNITY"
        assert body["decision_id"] is not None
        assert body["estimated_edge"] is not None
        assert float(body["estimated_edge"]) > 0

    def test_catalog_endpoints_are_stable(self):
        app = app_module.build_markets_app(_build_dependencies())
        client = TestClient(app)
        assert client.get("/v1/catalog/instruments").status_code == 200
        assert client.get("/v1/catalog/events").status_code == 200
        assert client.get("/v1/policies").status_code == 200
        assert client.get("/v1/strategies").status_code == 200
        assert client.get("/v1/opportunities").status_code == 200
        assert client.get("/v1/decisions").status_code == 200
        assert client.get("/v1/data-quality").status_code == 200
        assert client.get("/v1/catalog/venues").status_code == 503