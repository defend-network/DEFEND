"""M4.7 tests: DeepSeek credential audit (P51) and arb data-quality weakness
detection (P49)."""

from __future__ import annotations

from datetime import datetime, timezone

from defend_markets.quant.deepseek_audit import (
    AUDIT_RESULT,
    audit_deepseek_integration,
    quant_director_arb_review_allowed,
)
from defend_markets.quant.weakness import WeaknessDetector

NOW = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)


class TestDeepSeekAudit:
    def test_returns_integration_required(self):
        result = audit_deepseek_integration()
        assert result["result"] == AUDIT_RESULT
        assert result["authorized"] is False

    def test_arb_review_not_allowed(self):
        assert quant_director_arb_review_allowed() is False

    def test_never_reveals_secret(self):
        # The audit output must never contain a key value.
        import json
        payload = json.dumps(audit_deepseek_integration())
        assert "sk-" not in payload
        assert "api_key" not in payload.lower()


class TestArbWeaknessDetection:
    def test_second_book_zero_detected(self):
        detector = WeaknessDetector()
        snapshot = {
            "prices": {}, "predictions": {}, "coverage_by_bookmaker": {}, "bookmakers": {},
            "pairing": {}, "pass_reasons": {},
            "arb": {
                "rejection_funnel": {"quote_sets_examined": 10, "mathematical_arbs": 0},
                "opportunities": [],
            },
        }
        specs = detector.detect(snapshot)
        types = {s["weakness_type"] for s in specs}
        assert "ARB_SECOND_BOOK_ZERO" in types

    def test_staleness_high_detected(self):
        detector = WeaknessDetector()
        snapshot = {
            "prices": {}, "predictions": {}, "coverage_by_bookmaker": {}, "bookmakers": {},
            "pairing": {}, "pass_reasons": {},
            "arb": {
                "rejection_funnel": {"quote_sets_examined": 10, "mathematical_arbs": 0, "rejected_stale": 8},
                "opportunities": [],
            },
        }
        specs = detector.detect(snapshot)
        types = {s["weakness_type"] for s in specs}
        assert "ARB_QUOTE_STALENESS_HIGH" in types

    def test_cross_book_delta_high_detected(self):
        detector = WeaknessDetector()
        snapshot = {
            "prices": {}, "predictions": {}, "coverage_by_bookmaker": {}, "bookmakers": {},
            "pairing": {}, "pass_reasons": {},
            "arb": {
                "rejection_funnel": {"quote_sets_examined": 10, "mathematical_arbs": 0, "rejected_time_delta": 9},
                "opportunities": [],
            },
        }
        specs = detector.detect(snapshot)
        types = {s["weakness_type"] for s in specs}
        assert "ARB_CROSS_BOOK_DELTA_HIGH" in types

    def test_no_spurious_weakness_when_healthy(self):
        detector = WeaknessDetector()
        snapshot = {
            "prices": {}, "predictions": {}, "coverage_by_bookmaker": {}, "bookmakers": {},
            "pairing": {}, "pass_reasons": {},
            "arb": {
                "rejection_funnel": {"quote_sets_examined": 10, "mathematical_arbs": 3, "rejected_stale": 0, "rejected_time_delta": 0},
                "opportunities": [{"status": "ACTIVE", "classification": "MATHEMATICAL_ARB"}],
            },
        }
        specs = detector.detect(snapshot)
        arb_types = {s["weakness_type"] for s in specs if s["weakness_type"].startswith("ARB_")}
        assert arb_types == set()
