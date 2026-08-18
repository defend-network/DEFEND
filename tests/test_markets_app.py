from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re

import pytest
from fastapi.testclient import TestClient

from defend_markets import app as app_module
from defend_markets.app import MarketsDependencies
from defend_markets.config import MarketsSettings
from defend_markets.feeds import FeedDefinition, FeedProbeResult, FeedRecord
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
        assert client.get("/v1/providers").status_code == 200
        assert client.get("/v1/providers/world_bank/records").status_code == 200
        assert client.get("/v1/catalog/venues").status_code == 503

    def test_providers_endpoint_lists_ingested_feeds_and_records(self):
        store = InMemoryStore()
        for strategy_key in ("tt_two_way_arb", "tt_clv"):
            store.register_strategy(strategy_key)
        for policy in default_policies().values():
            store.register_policy(policy)
        store.upsert_feed(FeedDefinition("world_bank", "World Bank"))
        store.record_probe(
            FeedProbeResult(provider_id="world_bank", ok=True, status="HEALTHY", latency_ms=120),
            observed_at=NOW,
        )
        store.insert_records(
            "world_bank",
            [FeedRecord(record_key="USA:NY.GDP.MKTP.KD.ZG:2025", payload={"value": 2.4}, observed_at=NOW)],
            received_at=NOW,
        )
        deps = MarketsDependencies(
            settings=_build_dependencies().settings,
            database=None,
            sports_database=None,
            reader=None,
            store=store,
            journal=InMemoryJournal(),
            registry=build_default_registry(),
            reasoners=ReasonerRegistry(),
            clock=lambda: NOW,
        )
        app = app_module.build_markets_app(deps)
        client = TestClient(app)
        body = client.get("/v1/providers").json()
        assert any(p["provider_id"] == "world_bank" and p["status"] == "HEALTHY" for p in body["providers"])
        records = client.get("/v1/providers/world_bank/records").json()
        assert records["provider_id"] == "world_bank"
        assert records["records"][0]["record_key"] == "USA:NY.GDP.MKTP.KD.ZG:2025"


class TestTableTennisBoard:
    def test_board_without_reader_is_503(self):
        app = app_module.build_markets_app(_build_dependencies())
        response = TestClient(app).get("/v1/sports/table-tennis")
        assert response.status_code == 503

    def test_board_reports_real_odds_edges_and_honest_unavailable_values(self):
        reader = FakeSportsReader(quotes={("tt-live-001", "match_winner"): arb_pair()})
        app = app_module.build_markets_app(_build_dependencies(reader))
        body = TestClient(app).get("/v1/sports/table-tennis").json()

        assert body["strategy_key"] == "tt_two_way_arb"
        assert body["market_key"] == "match_winner"
        assert body["now"] == NOW.isoformat()
        assert len(body["events"]) == 1

        event = body["events"][0]
        assert event["event_key"] == "tt-live-001"
        assert event["display_name"] == "Player A vs Player B"
        assert len(event["legs"]) == 2
        for leg in event["legs"]:
            assert leg["implied_probability"] is not None
            assert leg["source_key"] in ("book-a", "book-b")
        assert event["gross_edge"] is not None
        assert event["costs"]["total"] is None
        assert event["net_edge"] is None
        assert event["model_probability"] is None
        assert event["model_probability_available"] is False
        assert event["confidence"] is not None
        assert event["data_quality"] is not None
        assert event["freshness"]["status"] == "STALE"
        assert event["freshness"]["age_seconds"] == 7200
        assert event["strategy"]["key"] == "tt_two_way_arb"
        assert event["strategy"]["eligible"] is True
        assert event["decision"] is None

    def test_board_passes_through_live_state_when_present(self):
        reader = FakeSportsReader(quotes={("tt-live-001", "match_winner"): arb_pair()})
        reader.set_live_state(
            "tt-live-001",
            {"status": "live", "sets": [1, 0], "games": [3, 2], "points": [9, 7]},
        )
        app = app_module.build_markets_app(_build_dependencies(reader))
        body = TestClient(app).get("/v1/sports/table-tennis").json()
        event = body["events"][0]
        assert event["live"] is not None
        assert event["live"]["state"]["status"] == "live"
        assert event["live"]["state"]["sets"] == [1, 0]
        assert event["live"]["observed_at"] is not None

    def test_board_attaches_latest_journaled_decision_per_event(self):
        reader = FakeSportsReader(
            quotes={("tt-live-001", "match_winner"): arb_pair(fees="0.001")}
        )
        dependencies = _build_dependencies(reader)
        app = app_module.build_markets_app(dependencies)
        client = TestClient(app)
        outcome = client.post(
            "/v1/evaluate/sports",
            json={"event_key": "tt-live-001", "market_key": "match_winner"},
        ).json()
        assert outcome["decision_type"] == "OPPORTUNITY"

        dependencies.store.record_decision(
            {
                "decision_id": outcome["decision_id"],
                "opportunity_id": outcome["opportunity_id"],
                "strategy_key": "tt_two_way_arb",
                "policy_key": "markets_core",
                "decision_type": "OPPORTUNITY",
                "reason_codes": [],
                "thesis": "tt_two_way_arb evaluation on tt-live-001 match_winner using real observed odds.",
                "confidence": outcome["confidence"],
                "estimated_edge": outcome["estimated_edge"],
                "cost_estimate": outcome["cost_estimate"],
                "data_cutoff_timestamp": NOW.isoformat(),
                "model_version": None,
                "created_at": NOW.isoformat(),
                "amendment_of": None,
                "outcome_id": None,
                "instrument_key": "sports:tt-live-001:match_winner",
            }
        )
        body = client.get("/v1/sports/table-tennis").json()
        event = body["events"][0]
        assert event["decision"] is not None
        assert event["decision"]["decision_type"] == "OPPORTUNITY"
        assert event["decision"]["decision_id"] == outcome["decision_id"]

    def test_board_marks_no_action_with_reason_codes(self):
        reader = FakeSportsReader(quotes={("tt-live-001", "match_winner"): arb_pair()})
        dependencies = _build_dependencies(reader)
        app = app_module.build_markets_app(dependencies)
        client = TestClient(app)
        outcome = client.post(
            "/v1/evaluate/sports",
            json={"event_key": "tt-live-001", "market_key": "match_winner"},
        ).json()
        assert outcome["decision_type"] == "NO_ACTION"
        dependencies.store.record_decision(
            {
                "decision_id": outcome["decision_id"],
                "decision_type": "NO_ACTION",
                "reason_codes": ["costs_unaccounted"],
                "instrument_key": "sports:tt-live-001:match_winner",
            }
        )
        event = client.get("/v1/sports/table-tennis").json()["events"][0]
        assert event["decision"]["decision_type"] == "NO_ACTION"
        assert event["decision"]["reason_codes"] == ["costs_unaccounted"]


class TestPerformance:
    def test_performance_reports_empty_sample_size_honestly(self):
        app = app_module.build_markets_app(_build_dependencies())
        body = TestClient(app).get("/v1/performance").json()
        assert body["sample_size"]["decisions"] == 0
        assert body["no_action_pct"] is None
        assert body["net_pnl"] is None
        assert body["win_rate"] is None
        assert body["roi"]["available"] is False
        assert body["clv"]["available"] is False
        assert body["calibration"]["available"] is False
        assert body["max_drawdown"]["available"] is False

    def test_performance_aggregates_real_journal_rows(self):
        dependencies = _build_dependencies()
        store = dependencies.store
        store.record_decision(
            {
                "decision_id": "d-1",
                "decision_type": "NO_ACTION",
                "reason_codes": ["costs_unaccounted"],
                "instrument_key": "sports:tt-live-001:match_winner",
            }
        )
        store.record_decision(
            {
                "decision_id": "d-2",
                "decision_type": "OPPORTUNITY",
                "reason_codes": [],
                "instrument_key": "sports:tt-live-001:match_winner",
            }
        )
        store.record_outcome(
            {
                "outcome_id": "o-1",
                "decision_id": "d-2",
                "instrument_key": "sports:tt-live-001:match_winner",
                "resolved_at": NOW.isoformat(),
                "result": "WON",
                "pnl": "12.5",
                "clv": "0.03",
                "calibration_bucket": "0.85-1.00",
            }
        )
        store.record_outcome(
            {
                "outcome_id": "o-2",
                "decision_id": "d-2",
                "instrument_key": "sports:tt-live-001:match_winner",
                "resolved_at": NOW.isoformat(),
                "result": "LOST",
                "pnl": "-8.0",
                "clv": None,
                "calibration_bucket": None,
            }
        )
        app = app_module.build_markets_app(dependencies)
        body = TestClient(app).get("/v1/performance").json()

        assert body["sample_size"]["decisions"] == 2
        assert body["sample_size"]["no_actions"] == 1
        assert body["sample_size"]["settled"] == 2
        assert body["no_action_pct"] == 0.5
        assert float(body["net_pnl"]) == 4.5
        assert body["win_rate"] == 0.5
        assert body["roi"]["available"] is False
        assert float(body["clv"]["value"]) == 0.03
        assert body["clv"]["available"] is True
        assert body["calibration"]["available"] is True
        assert body["calibration"]["buckets"] == {"0.85-1.00": 1}
        assert float(body["max_drawdown"]["value"]) == 8.0