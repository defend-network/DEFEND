"""Quant Director V1 foundation tests: auth, grounding, budgets, lifecycle."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from admin_auth import AdminPrincipal, require_admin
from defend_markets.quant.config import MarketsRuntimeState, QuantDirectorSettings
from defend_markets.quant.explanation import explain_m5_prediction
from defend_markets.quant.model_aliases import (
    DEEP_RESEARCH_ALIAS,
    SOL_ALIAS,
    RUNTIME_ALIAS,
    DirectorProfile,
    resolve_runtime_profile,
)
from defend_markets.quant.orchestrator import MarketsIntelligenceOrchestrator, MockDirectorModel
from defend_markets.quant.routes import build_quant_router
from defend_markets.quant.store import InMemoryQuantStore
from defend_markets.quant.tools import InMemoryMarketTools

REPO = Path(__file__).resolve().parents[1]
M5_ARTIFACT = REPO / "docs" / "operations" / "TT_M5_LIVE_WEIGHTS_V1.json"

OWNER = AdminPrincipal(account_id="a1", username="owner@defend", role="owner", expires_at=9999999999)
CONSUMER = AdminPrincipal(account_id="a2", username="consumer@defend", role="consumer", expires_at=9999999999)


def _weights_doc():
    return json.loads(M5_ARTIFACT.read_text(encoding="utf-8"))


def _fixture_orchestrator(*, prices=0, events=85, matched=85, predictions=50, state="STOPPED", store=None):
    store = store or InMemoryQuantStore()
    tools = InMemoryMarketTools(
        store,
        events_discovered=events,
        events_matched=matched,
        available_predictions=predictions,
        price_observations=prices,
        bookmakers_with_prices=0 if prices == 0 else 2,
        provider_healthy=True,
    )
    settings = QuantDirectorSettings(runtime_state=state)
    return MarketsIntelligenceOrchestrator(
        store=store, tools=tools, settings=settings, weights_doc=_weights_doc()
    )


class TestM5Explanation:
    def test_feature_contribution_math_correct(self):
        doc = _weights_doc()
        features = {name: 1.0 for name in doc["feature_names"]}
        result = explain_m5_prediction(features, doc)
        expected_logit = float(doc["intercept"]) + sum(
            float(doc["weights"][name]) for name in doc["feature_names"]
        )
        import math

        expected_p = 1.0 / (1.0 + math.exp(-expected_logit))
        assert result["total_logit"] == pytest.approx(expected_logit, abs=1e-9)
        assert result["probability"] == pytest.approx(expected_p, abs=1e-9)
        assert len(result["contributions"]) == len(doc["feature_names"])
        assert sum(item["contribution"] for item in result["contributions"]) == pytest.approx(
            expected_logit - float(doc["intercept"]), abs=1e-9
        )

    def test_artifact_hash_unchanged(self):
        blob = M5_ARTIFACT.read_bytes()
        file_sha = hashlib.sha256(blob).hexdigest()
        doc = json.loads(blob)
        assert file_sha == "fe6f18d1fb5eea640fc42d904d9010470ee75f73e594b2c00a86982d3381e229"
        assert doc["sha256"] == "54affc960a3434575d1b4b7e536f9413c2b1978fd020433490ac2020d13a15f8"


class TestRuntimeAliases:
    def test_quant_director_product_identity(self):
        profile = resolve_runtime_profile(RUNTIME_ALIAS)
        assert isinstance(profile, DirectorProfile)
        assert profile.provider == "deepseek"
        assert profile.model == "deepseek-v4-flash"
        assert profile.reasoning == "default"
        assert profile.requires_approval is False

    def test_deep_research_alias_resolves_to_pro(self):
        profile = resolve_runtime_profile(DEEP_RESEARCH_ALIAS)
        assert profile.model == "deepseek-v4-pro"

    def test_sol_alias_requires_owner_approval(self):
        profile = resolve_runtime_profile(SOL_ALIAS)
        assert profile.model == "gpt-5.6-sol"
        assert profile.requires_approval is True


class TestBudgetAndState:
    def test_stopped_makes_no_scheduled_ai_calls(self):
        orchestrator = _fixture_orchestrator(state=MarketsRuntimeState.STOPPED.value)
        result = orchestrator.maybe_run_scheduled_review()
        assert result["ran"] is False
        assert "no AI spend" in result["reason"]

    def test_ready_with_cooldown_blocks_scheduled_call(self):
        orchestrator = _fixture_orchestrator(state=MarketsRuntimeState.READY.value)
        first = orchestrator.maybe_run_scheduled_review()
        assert first["ran"] is True
        second = orchestrator.maybe_run_scheduled_review()
        assert second["ran"] is False
        assert second["reason"] in ("cooldown", "no meaningful state change")

    def test_hard_budget_blocks_calls(self):
        store = InMemoryQuantStore()
        settings = QuantDirectorSettings(runtime_state="READY", max_daily_calls=1)
        orchestrator = _fixture_orchestrator(state="READY", store=store)
        orchestrator = MarketsIntelligenceOrchestrator(
            store=store,
            tools=orchestrator._tools,
            settings=settings,
        )
        orchestrator.chat(thread_id=None, message="hello")
        with pytest.raises(RuntimeError, match="budget hard limit"):
            orchestrator.chat(thread_id=None, message="again")

    def test_no_wagering_tool(self):
        orchestrator = _fixture_orchestrator()
        assert not hasattr(orchestrator, "place_bet")
        assert not hasattr(orchestrator, "execute_wager")


class TestChatGrounding:
    def test_blocker_answer_grounded_in_tool_state(self):
        orchestrator = _fixture_orchestrator(prices=0, events=85, matched=85, predictions=50)
        result = orchestrator.chat(thread_id=None, message="What is blocking paper betting?")
        assert "provider TT price coverage is the blocking layer" in result["response"]
        assert "M5 failed" not in result["response"]
        assert "identity failed" not in result["response"]
        assert "bets exist" not in result["response"]
        assert "prices exist" not in result["response"]

    def test_chat_persists_and_grounded_provenance(self):
        store = InMemoryQuantStore()
        orchestrator = _fixture_orchestrator(prices=0, store=store)
        result = orchestrator.chat(thread_id=None, message="status?")
        thread_id = result["thread_id"]
        messages = store.thread_messages(thread_id)
        assert [m["role"] for m in messages] == ["user", "assistant"]
        assert all(m["provenance"].get("hidden_cot") is False for m in messages)


class TestPromotionGates:
    def test_insufficient_evidence_blocks_promotion(self):
        orchestrator = _fixture_orchestrator()
        verdict = orchestrator.evaluate_promotion(
            model_version="c1",
            brier=0.2,
            log_loss=0.6,
            calibration_error=0.03,
            sample_n=10,
        )
        assert verdict["decision"] == "PROMOTION_BLOCKED"
        assert any("insufficient evidence" in reason for reason in verdict["reasons"])

    def test_worse_challenger_blocked(self):
        orchestrator = _fixture_orchestrator()
        verdict = orchestrator.evaluate_promotion(
            model_version="c1",
            brier=0.30,
            log_loss=0.80,
            calibration_error=0.03,
            sample_n=200,
            champion_brier=0.24,
            champion_log_loss=0.67,
        )
        assert verdict["decision"] == "PROMOTION_BLOCKED"

    def test_qualifying_fixture_may_promote_to_shadow(self):
        orchestrator = _fixture_orchestrator()
        verdict = orchestrator.evaluate_promotion(
            model_version="c1",
            brier=0.22,
            log_loss=0.65,
            calibration_error=0.02,
            sample_n=200,
            champion_brier=0.24,
            champion_log_loss=0.67,
        )
        assert verdict["decision"] == "PROMOTION_ALLOWED"


class TestChampionRegistry:
    def test_challenger_cannot_mutate_champion_artifact(self):
        store = InMemoryQuantStore()
        doc = _weights_doc()
        store.register_model(
            model_id="M5_REGULARIZED_LOGISTIC",
            model_version="M5_REGULARIZED_LOGISTIC:54affc960a34",
            role="CHAMPION",
            stage="CHAMPION",
            artifact_path="docs/operations/TT_M5_LIVE_WEIGHTS_V1.json",
            artifact_sha256="fe6f18d1fb5eea640fc42d904d9010470ee75f73e594b2c00a86982d3381e229",
            fit_n=doc["fit_n"],
            cutoff=doc["cutoff"],
            feature_schema_version=1,
        )
        store.register_model(
            model_id="challenger-x",
            model_version="challenger-x:abc123",
            role="CHALLENGER",
            stage="SHADOW",
            artifact_sha256="0000000000000000000000000000000000000000000000000000000000000000",
        )
        champion = store.champion()
        assert champion["model_id"] == "M5_REGULARIZED_LOGISTIC"
        assert champion["artifact_sha256"] == "fe6f18d1fb5eea640fc42d904d9010470ee75f73e594b2c00a86982d3381e229"
        challenger = next(m for m in store.list_models() if m["model_id"] == "challenger-x")
        assert challenger["artifact_sha256"].startswith("0000")


class TestResearchJournal:
    def test_lifecycle_persists(self):
        store = InMemoryQuantStore()
        orchestrator = _fixture_orchestrator(store=store)
        entry_id = orchestrator.create_research_entry(
            hypothesis="feature ablation of recency elo",
            rationale="measure lift on Brier",
        )
        assert store.transition_research_entry(entry_id, status="COMPLETED", result_summary="no lift")
        entries = orchestrator.list_research()
        assert any(e["entry_id"] == entry_id and e["status"] == "COMPLETED" for e in entries)


class TestAdminRoutes:
    def _app(self, principal) -> FastAPI:
        orchestrator = _fixture_orchestrator(prices=0)
        app = FastAPI()
        app.include_router(build_quant_router(orchestrator))
        app.dependency_overrides[require_admin] = lambda: principal
        return app

    def test_unauthenticated_returns_401(self):
        app = self._app(OWNER)
        app.dependency_overrides[require_admin] = require_admin
        client = TestClient(app)
        response = client.get("/api/markets/ai/state")
        assert response.status_code == 401

    def test_consumer_returns_403(self):
        client = TestClient(self._app(CONSUMER))
        response = client.get("/api/markets/ai/state")
        assert response.status_code == 403

    def test_admin_allowed_200(self):
        client = TestClient(self._app(OWNER))
        response = client.get("/api/markets/ai/state")
        assert response.status_code == 200
        body = response.json()
        assert body["markets_state"] == "STOPPED"
