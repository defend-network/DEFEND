"""MarketsIntelligenceOrchestrator: supervised Quant Director boundary.

Owns chat orchestration, governed tool access, research journal interaction,
budget enforcement, and the deterministic mock model backend used when no
runtime AI credential is configured. It never writes production weights,
bypasses evaluation, places bets, or mutates settlements.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from defend_markets.quant.config import (
    MARKETS_RUNTIME_STATE_DEFAULT,
    MarketsRuntimeState,
    QuantDirectorSettings,
)
from defend_markets.quant.explanation import explain_m5_prediction
from defend_markets.quant.model_aliases import (
    DEEP_RESEARCH_ALIAS,
    RUNTIME_ALIAS,
    resolve_runtime_profile,
    runtime_credentials_present,
)


class DirectorModel(Protocol):
    def answer(self, context: dict[str, Any]) -> str: ...


@dataclass(frozen=True)
class PromotionVerdict:
    allowed: bool
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": "PROMOTION_ALLOWED" if self.allowed else "PROMOTION_BLOCKED",
            "reasons": self.reasons,
        }


class MockDirectorModel:
    """Deterministic, tool-grounded backend (no fabrication, no hidden CoT)."""

    def answer(self, context: dict[str, Any]) -> str:
        blocking = context.get("blocking_layers", {})
        prices = context.get("prices", {})
        provider = context.get("provider_state", {})
        evidence_lines = [
            f"events_discovered={provider.get('events_discovered', 0)}",
            f"events_matched={provider.get('events_matched', 0)}",
            f"available_m5_predictions={provider.get('available_predictions', 0)}",
            f"market_observations={prices.get('observations', 0)}",
            f"bookmakers_with_prices={prices.get('bookmakers_with_prices', 0)}",
        ]
        primary = blocking.get("primary", "unknown")
        if primary == "provider_tt_price_coverage":
            decision = "provider TT price coverage is the blocking layer for paper betting."
        elif primary == "provider_health":
            decision = "Provider health is the blocking layer for paper betting."
        elif primary == "event_discovery":
            decision = "Event discovery is the blocking layer for paper betting."
        else:
            decision = "No deterministic blocking layer was detected."
        return "\n".join(
            [
                "EVIDENCE: " + "; ".join(evidence_lines),
                "CALCULATION: deterministic tool state, no AI-prose override",
                "MAIN DRIVERS: " + str(blocking.get("primary")),
                "UNCERTAINTY: tool state reflects only persisted, current data",
                "COUNTER_THESIS: none detected in tool state",
                "DECISION: " + decision,
                "NEXT_ACTION: recheck provider bookmaker TT coverage when new prices arrive",
                "PROVENANCE: governed read-only tools",
            ]
        )


class MarketsIntelligenceOrchestrator:
    def __init__(
        self,
        *,
        store: Any,
        tools: Any,
        settings: QuantDirectorSettings | None = None,
        model: DirectorModel | None = None,
        clock: Any | None = None,
        weights_doc: dict[str, Any] | None = None,
    ) -> None:
        self._store = store
        self._tools = tools
        self._settings = settings or QuantDirectorSettings.from_env()
        self._model = model if model is not None else MockDirectorModel()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._weights_doc = weights_doc
        self._last_trigger_at: datetime | None = None

    def runtime_profile(self, *, deep: bool = False) -> dict[str, str]:
        alias = DEEP_RESEARCH_ALIAS if deep else RUNTIME_ALIAS
        if deep and not self._settings.deep_research_allowed:
            return resolve_runtime_profile(RUNTIME_ALIAS).to_dict()
        return resolve_runtime_profile(alias).to_dict()

    def live_ai_configured(self) -> bool:
        return runtime_credentials_present()

    def markets_state(self) -> str:
        return self._settings.runtime_state

    def _budget_state(self) -> dict[str, Any]:
        provider = resolve_runtime_profile(RUNTIME_ALIAS).provider
        row = self._store.budget_row(
            day=datetime.now(timezone.utc).date().isoformat(),
            provider=provider,
            model=resolve_runtime_profile(RUNTIME_ALIAS).model,
        )
        calls = int(row["call_count"]) if row else 0
        cost = float(row["cost_usd"]) if row else 0.0
        return {
            "calls_today": calls,
            "cost_today": round(cost, 6),
            "max_daily_calls": self._settings.max_daily_calls,
            "daily_cost_soft_limit": self._settings.daily_cost_soft_limit,
            "daily_cost_hard_limit": self._settings.daily_cost_hard_limit,
            "blocked": (
                calls >= self._settings.max_daily_calls
                or cost >= self._settings.daily_cost_hard_limit
            ),
        }

    def chat(self, *, thread_id: int | None, message: str) -> dict[str, Any]:
        if not self._settings.enabled:
            raise RuntimeError("MARKETS_AI_ENABLED is false")
        budget = self._budget_state()
        if budget["blocked"]:
            raise RuntimeError("AI budget hard limit reached")
        if thread_id is None:
            thread_id = self._store.create_thread(admin_account_id="owner")
        context = self._tools.all_tool_state()
        profile = self.runtime_profile()
        self._store.record_ai_call(
            provider=profile["provider"], model=profile["model"], cost=0.0
        )
        response = self._model.answer(context)
        self._store.append_message(
            thread_id=thread_id, role="user", content=message,
            provenance={"profile": profile, "grounded": True, "hidden_cot": False},
        )
        self._store.append_message(
            thread_id=thread_id, role="assistant", content=response,
            provenance={"profile": profile, "grounded": True, "hidden_cot": False},
        )
        return {
            "thread_id": thread_id,
            "response": response,
            "profile": profile,
            "budget": self._budget_state(),
        }

    def maybe_run_scheduled_review(self) -> dict[str, Any]:
        if not self._settings.markets_ready:
            return {"ran": False, "reason": f"runtime state is {self.markets_state()}; no AI spend"}
        now = self._clock()
        if self._last_trigger_at is not None:
            cooldown = self._settings.trigger_cooldown_seconds
            if (now - self._last_trigger_at).total_seconds() < cooldown:
                return {"ran": False, "reason": "cooldown"}
        budget = self._budget_state()
        if budget["blocked"]:
            return {"ran": False, "reason": "budget hard limit"}
        self._last_trigger_at = now
        profile = self.runtime_profile()
        self._store.record_ai_call(
            provider=profile["provider"], model=profile["model"], cost=0.0
        )
        return {"ran": True, "reason": "scheduled review", "profile": profile}

    def explain_prediction(self, features: dict[str, float]) -> dict[str, Any] | None:
        if self._weights_doc is None:
            return None
        version = self._weights_doc.get("model_id", "")
        sha = self._weights_doc.get("sha256", "")
        if sha:
            version = f"{version}:{sha[:12]}"
        return explain_m5_prediction(features, self._weights_doc, model_version=version)

    def evaluate_promotion(
        self,
        *,
        model_version: str,
        brier: float | None,
        log_loss: float | None,
        calibration_error: float | None,
        sample_n: int,
        champion_brier: float | None = None,
        champion_log_loss: float | None = None,
        leakage_detected: bool = False,
        min_sample: int = 100,
        metric_tolerance: float = 0.05,
    ) -> dict[str, Any]:
        reasons: list[str] = []
        allowed = True
        if leakage_detected:
            allowed = False
            reasons.append("future leakage detected")
        if sample_n < min_sample:
            allowed = False
            reasons.append(f"insufficient evidence sample {sample_n} < {min_sample}")
        if brier is None or log_loss is None or calibration_error is None:
            allowed = False
            reasons.append("metrics missing")
        if allowed and champion_brier is not None and brier > champion_brier + metric_tolerance:
            allowed = False
            reasons.append("candidate materially worse on Brier")
        if allowed and champion_log_loss is not None and log_loss > champion_log_loss + metric_tolerance:
            allowed = False
            reasons.append("candidate materially worse on log loss")
        if allowed and calibration_error is not None and calibration_error > metric_tolerance:
            allowed = False
            reasons.append("candidate calibration error exceeds tolerance")
        verdict = PromotionVerdict(allowed=allowed, reasons=reasons)
        return verdict.to_dict()

    def create_research_entry(self, *, hypothesis: str, rationale: str | None = None, data_needed: str | None = None) -> int:
        return self._store.create_research_entry(
            hypothesis=hypothesis, rationale=rationale, data_needed=data_needed
        )

    def list_research(self) -> list[dict[str, Any]]:
        return self._store.list_research_entries()
