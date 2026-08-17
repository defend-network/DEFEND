from __future__ import annotations

from decimal import Decimal
import importlib.util
from pathlib import Path
import sys

import pytest

from defend_markets.domain import CostModel, NoActionReason, ProvenanceStamp, StrategyLifecycle
from defend_markets.strategies import build_default_registry, implied_probability


def _selection(selection_key: str, odds: str, source: str = "book-a") -> dict[str, object]:
    return {
        "selection_key": selection_key,
        "decimal_odds": Decimal(odds),
        "provenance": ProvenanceStamp(
            source_key=source,
            observed_at=None,
            received_at=None,
            raw_ref=f"raw-{source}",
            normalization_version=None,
        ),
    }


def _legacy_tt_engine():
    path = Path(__file__).resolve().parents[1] / "TableTennis" / "tt_engine.py"
    spec = importlib.util.spec_from_file_location("tt_engine_legacy", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestRegistry:
    def test_default_registry_has_tt_arb_and_planned_clv(self):
        registry = build_default_registry()
        keys = {definition.strategy_key for definition in registry.list()}
        assert {"tt_two_way_arb", "tt_clv"} <= keys

    def test_clv_is_planned_not_implemented(self):
        registry = build_default_registry()
        clv = registry.get("tt_clv")
        assert clv.definition.lifecycle is StrategyLifecycle.PLANNED
        assert clv.evaluator is None

    def test_planned_strategy_cannot_be_evaluated(self):
        registry = build_default_registry()
        evaluation = registry.evaluate("tt_clv", {"selections": []})
        assert not evaluation.eligible
        assert NoActionReason.STRATEGY_NOT_ELIGIBLE.value in evaluation.reasons

    def test_unregistered_strategy_raises(self):
        registry = build_default_registry()
        with pytest.raises(KeyError):
            registry.get("invented_on_the_fly")

    def test_duplicate_registration_rejected(self):
        registry = build_default_registry()
        with pytest.raises(ValueError, match="duplicate"):
            registry.get("tt_two_way_arb").definition
            registry.register(registry.get("tt_two_way_arb").definition)


class TestArbMath:
    def test_arb_pair_yields_gross_edge(self):
        registry = build_default_registry()
        evaluation = registry.evaluate(
            "tt_two_way_arb",
            {
                "selections": [_selection("a", "1.85"), _selection("b", "2.35")],
                "params": {"min_edge_pct": "0.5"},
            },
        )
        assert evaluation.eligible
        assert evaluation.gross_edge > Decimal("0.03")
        assert evaluation.costs == CostModel()

    def test_no_arb_pair_not_eligible(self):
        registry = build_default_registry()
        evaluation = registry.evaluate(
            "tt_two_way_arb",
            {
                "selections": [_selection("a", "1.85"), _selection("b", "2.20")],
                "params": {"min_edge_pct": "0.5"},
            },
        )
        assert not evaluation.eligible
        assert any(reason.startswith("below_min_edge") for reason in evaluation.reasons)

    def test_missing_provenance_blocks_evaluation(self):
        registry = build_default_registry()
        evaluation = registry.evaluate(
            "tt_two_way_arb",
            {
                "selections": [
                    {"selection_key": "a", "decimal_odds": Decimal("1.85")},
                    {"selection_key": "b", "decimal_odds": Decimal("2.35")},
                ],
                "params": {"min_edge_pct": "0.5"},
            },
        )
        assert not evaluation.eligible
        assert "missing_provenance" in evaluation.reasons

    def test_explicit_venue_fees_flow_into_costs(self):
        registry = build_default_registry()
        selection_a = _selection("a", "1.85", "book-a")
        selection_b = _selection("b", "2.35", "book-b")
        selection_a["costs"] = CostModel(fees=Decimal("0.002"))
        selection_b["costs"] = CostModel(fees=Decimal("0.002"))
        evaluation = registry.evaluate(
            "tt_two_way_arb",
            {
                "selections": [selection_a, selection_b],
                "params": {"min_edge_pct": "0.5"},
            },
        )
        assert evaluation.eligible
        assert evaluation.costs.fees == Decimal("0.004")
        assert evaluation.costs.vig is None

    def test_unknown_costs_stay_unknown(self):
        registry = build_default_registry()
        selection_a = _selection("a", "1.85")
        selection_b = _selection("b", "2.35")
        selection_a["costs"] = CostModel(fees=Decimal("0.002"))
        evaluation = registry.evaluate(
            "tt_two_way_arb",
            {
                "selections": [selection_a, selection_b],
                "params": {"min_edge_pct": "0.5"},
            },
        )
        assert evaluation.costs.total() is None


class TestLegacyParity:
    def test_implied_probability_matches_legacy_engine(self):
        legacy = _legacy_tt_engine()
        assert implied_probability(Decimal("2.00")) == Decimal(str(legacy.implied_prob(2.0)))

    def test_arb_edge_matches_legacy_find_two_way_arb(self):
        legacy = _legacy_tt_engine()
        registry = build_default_registry()
        evaluation = registry.evaluate(
            "tt_two_way_arb",
            {
                "selections": [_selection("a", "1.85"), _selection("b", "2.35")],
                "params": {"min_edge_pct": "0.1"},
            },
        )
        legacy_result = legacy.find_two_way_arb(1.85, 2.35, min_edge_pct=0.1)
        assert legacy_result is not None
        legacy_edge = Decimal(str(legacy_result["edge_pct"])) / Decimal("100")
        assert abs(evaluation.gross_edge - legacy_edge) < Decimal("0.0001")