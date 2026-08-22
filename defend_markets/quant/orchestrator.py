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
from defend_markets.quant.health import QuantDirectorHealth, detect_health
from defend_markets.quant.intelligence import QuantIntelligence, collect_monitor_data
from defend_markets.quant.model_aliases import (
    DEEP_RESEARCH_ALIAS,
    SOL_ALIAS,
    RUNTIME_ALIAS,
    resolve_runtime_profile,
    runtime_credentials_present,
)
from defend_markets.quant.reviews import DailyReview, WeeklyReview
from defend_markets.quant.research.experiment import (
    ExperimentResult,
    ExperimentRunner,
    ExperimentSpec,
    build_spec,
)
from defend_markets.quant.research.promotion import PromotionGateSet
from defend_markets.quant.research.snapshot import DatasetSnapshot, build_snapshot
from defend_markets.quant.triggers import TriggerLedger
from defend_markets.quant.scheduler import Scheduler, SchedulerJob
from defend_markets.quant.champion import ChampionConflictError, ensure_champion
from defend_markets.quant.evaluation import EvaluationService
from defend_markets.quant.prioritization import (
    SEED_HYPOTHESES,
    ResearchPrioritizer,
    seed_hypotheses,
)
from defend_markets.quant.budget import estimate_call_cost


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
        artifact_dir: Any = None,
    ) -> None:
        self._store = store
        self._tools = tools
        self._settings = settings or QuantDirectorSettings.from_env()
        self._model = model if model is not None else MockDirectorModel()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._weights_doc = weights_doc
        self._last_trigger_at: datetime | None = None
        self._trigger_ledger = TriggerLedger(
            store, clock=self._clock,
            cooldown_seconds=self._settings.trigger_cooldown_seconds,
        )
        self._intelligence = QuantIntelligence(weights_doc=weights_doc)
        self._daily_review = DailyReview()
        self._weekly_review = WeeklyReview(artifact_dir=artifact_dir)
        self._scheduler = Scheduler(store, owner="markets-quant-director", clock=self._clock)
        self._approved_expensive = False
        self._health = detect_health(
            initialized=True,
            runtime_model=resolve_runtime_profile(RUNTIME_ALIAS).model,
        )

    def health(self) -> QuantDirectorHealth:
        return self._health

    def health_state(self) -> dict[str, Any]:
        return self._health.to_dict()

    def runtime_profile(self, *, deep: bool = False, sol: bool = False) -> dict[str, str]:
        if sol:
            return resolve_runtime_profile(SOL_ALIAS).to_dict()
        if deep and not self._settings.deep_research_allowed:
            return resolve_runtime_profile(RUNTIME_ALIAS).to_dict()
        alias = DEEP_RESEARCH_ALIAS if deep else RUNTIME_ALIAS
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

    def chat(self, *, thread_id: int | None, message: str, deep: bool = False, sol: bool = False) -> dict[str, Any]:
        if not self._settings.enabled:
            raise RuntimeError("MARKETS_AI_ENABLED is false")
        profile = self.runtime_profile(deep=deep, sol=sol)
        if profile.get("requires_approval") == "true" and not self._approved_expensive:
            raise RuntimeError("owner approval required for expensive Sol profile")
        budget = self._budget_state()
        if budget["blocked"]:
            raise RuntimeError("AI budget hard limit reached")
        if thread_id is None:
            thread_id = self._store.create_thread(admin_account_id="owner")
        context = self._tools.all_tool_state()
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

    def approve_expensive(self) -> bool:
        self._approved_expensive = True
        return True

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

    def budget_policy(self) -> dict[str, Any]:
        return {
            "max_daily_calls": self._settings.max_daily_calls,
            "daily_cost_soft_limit": self._settings.daily_cost_soft_limit,
            "daily_cost_hard_limit": self._settings.daily_cost_hard_limit,
            "trigger_cooldown_seconds": self._settings.trigger_cooldown_seconds,
            "deep_research_allowed": self._settings.deep_research_allowed,
        }

    def create_snapshot(
        self,
        *,
        rows: list[dict[str, Any]],
        cutoff: str,
        target_definition: str,
        provenance: dict[str, Any] | None = None,
    ) -> DatasetSnapshot:
        snapshot = build_snapshot(
            rows,
            cutoff=cutoff,
            target_definition=target_definition,
            feature_schema_version=1,
            provenance=provenance,
        )
        self._store.create_snapshot(snapshot)
        return snapshot

    def _stage_from_decision(self, result: ExperimentResult) -> tuple[str, str]:
        if result.decision == "PROMOTION_ALLOWED":
            return "SHADOW", "PROMOTED_TO_SHADOW"
        blockers = (result.gates or {}).get("blockers") or []
        if any("no measurable lift" in reason or "simpler model" in reason for reason in blockers):
            return "REJECTED", "REJECTED_NO_LIFT"
        if any("regression" in reason for reason in blockers):
            return "REJECTED", "REJECTED_REGRESSION"
        return "WALK_FORWARD", "WALK_FORWARD_COMPLETE"

    def evaluate_and_record_challenger(
        self,
        *,
        hypothesis_id: str,
        challenger_name: str,
        feature_set: list[str],
        snapshot: DatasetSnapshot,
        champion_version: str,
        n_windows: int = 4,
        champion_brier: float | None = None,
        champion_log_loss: float | None = None,
        market_metrics_available: bool = False,
        actor: str = "SYSTEM",
    ) -> dict[str, Any]:
        experiment_id = f"exp-{hypothesis_id}-{challenger_name}"
        spec = build_spec(
            experiment_id=experiment_id,
            hypothesis_id=hypothesis_id,
            snapshot=snapshot,
            champion_version=champion_version,
            challenger_name=challenger_name,
            feature_set=feature_set,
        )
        runner = ExperimentRunner(snapshot=snapshot, n_windows=n_windows)
        result = runner.run(
            spec,
            champion_brier=champion_brier,
            champion_log_loss=champion_log_loss,
            market_metrics_available=market_metrics_available,
        )
        self._store.save_experiment(spec=spec, result=result)

        model_id = f"challenger-{challenger_name}"
        current = [entry for entry in self._store.list_models() if entry.get("model_id") == model_id and entry.get("model_version") == experiment_id]
        from_stage = current[0].get("stage") if current else "RESEARCH"
        to_stage, conclusion = self._stage_from_decision(result)

        self._store.register_model(
            model_id=model_id,
            model_version=experiment_id,
            role="CHALLENGER",
            stage=to_stage,
            feature_schema_version=1,
        )
        self._store.record_stage_transition(
            {
                "model_id": model_id,
                "model_version": experiment_id,
                "from_stage": from_stage,
                "to_stage": to_stage,
                "experiment_id": experiment_id,
                "gate_version": result.promotion_policy_version,
                "gate_results": result.gates or {},
                "metric_deltas": result.metric_deltas,
                "actor": actor,
                "reason": conclusion,
                "code_commit": spec.code_commit,
            }
        )
        entry_id = self._store.create_research_entry(
            hypothesis=f"{hypothesis_id}: {challenger_name}",
            rationale=conclusion,
            data_needed=", ".join(feature_set),
        )
        self._store.transition_research_entry(
            entry_id,
            status="COMPLETED",
            result_summary=conclusion,
            evidence={"decision": result.decision, "stage": to_stage, "metric_deltas": result.metric_deltas},
        )
        return {
            "experiment": result.to_dict(),
            "model_id": model_id,
            "stage": to_stage,
            "conclusion": conclusion,
            "entry_id": entry_id,
        }

    def run_experiment(
        self,
        *,
        hypothesis_id: str,
        challenger_name: str,
        feature_set: list[str],
        snapshot: DatasetSnapshot,
        champion_version: str,
        n_windows: int = 4,
        champion_brier: float | None = None,
        champion_log_loss: float | None = None,
        market_metrics_available: bool = False,
    ) -> dict[str, Any]:
        return self.evaluate_and_record_challenger(
            hypothesis_id=hypothesis_id,
            challenger_name=challenger_name,
            feature_set=feature_set,
            snapshot=snapshot,
            champion_version=champion_version,
            n_windows=n_windows,
            champion_brier=champion_brier,
            champion_log_loss=champion_log_loss,
            market_metrics_available=market_metrics_available,
        )

    def advance_stage(self, *, model_id: str, model_version: str, to_stage: str) -> dict[str, Any]:
        allowed = {"RESEARCH", "BACKTEST", "WALK_FORWARD", "SHADOW", "PAPER"}
        if to_stage not in allowed:
            return {"allowed": False, "reason": f"stage {to_stage} requires owner authority"}
        self._store.register_model(
            model_id=model_id,
            model_version=model_version,
            role="CHALLENGER",
            stage=to_stage,
        )
        return {"allowed": True, "stage": to_stage}

    def monitor_m5(self) -> dict[str, Any]:
        data = collect_monitor_data(self._tools)
        return self._intelligence.monitor(data)

    def analyze_weaknesses(self) -> list[dict[str, Any]]:
        data = collect_monitor_data(self._tools)
        return [finding.to_dict() for finding in self._intelligence.find_weaknesses(data)]

    def generate_hypotheses(self, *, limit: int = 10) -> list[dict[str, Any]]:
        data = collect_monitor_data(self._tools)
        return self._intelligence.generate_hypotheses(data, limit=limit)

    def research_report(self) -> dict[str, Any]:
        data = collect_monitor_data(self._tools)
        return self._intelligence.research_report(data)

    def create_proposal(
        self,
        *,
        title: str,
        reason: str,
        supporting_data: str | None = None,
        expected_effect: str | None = None,
        risk: str | None = None,
        required_features: list[str] | None = None,
        evaluation_plan: str | None = None,
    ) -> int:
        payload = {
            "title": title,
            "reason": reason,
            "supporting_data": supporting_data,
            "expected_effect": expected_effect,
            "risk": risk,
            "required_features": required_features or [],
            "evaluation_plan": evaluation_plan,
        }
        entry_id = self._store.create_research_entry(
            hypothesis=f"{title} :: {reason}",
            rationale=supporting_data,
            data_needed="; ".join(required_features or []),
        )
        self._store.transition_research_entry(
            entry_id,
            status="PROPOSED",
            evidence={"proposal": payload},
        )
        return entry_id

    def list_proposals(self) -> list[dict[str, Any]]:
        return [
            entry for entry in self._store.list_research_entries()
            if entry.get("status") == "PROPOSED"
        ]

    def _review_gate(self) -> dict[str, Any] | None:
        if not self._settings.markets_ready:
            return {"ran": False, "reason": f"runtime state is {self.markets_state()}; no AI spend"}
        budget = self._budget_state()
        if budget["blocked"]:
            return {"ran": False, "reason": "budget hard limit"}
        now = self._clock()
        if self._last_trigger_at is not None:
            cooldown = self._settings.trigger_cooldown_seconds
            if (now - self._last_trigger_at).total_seconds() < cooldown:
                return {"ran": False, "reason": "cooldown"}
        self._last_trigger_at = now
        return None

    def run_daily_review(self) -> dict[str, Any]:
        blocked = self._review_gate()
        if blocked is not None:
            return blocked
        data = collect_monitor_data(self._tools)
        outcome = self._daily_review.run(tools=self._tools, intelligence=self._intelligence, data=data)
        self._store.save_review(outcome)
        return outcome.to_dict()

    def run_weekly_review(self) -> dict[str, Any]:
        blocked = self._review_gate()
        if blocked is not None:
            return blocked
        data = collect_monitor_data(self._tools)
        outcome = self._weekly_review.run(tools=self._tools, intelligence=self._intelligence, data=data)
        self._store.save_review(outcome)
        return outcome.to_dict()

    def list_reviews(self) -> list[dict[str, Any]]:
        return self._store.list_reviews()

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

    def list_experiments(self) -> list[dict[str, Any]]:
        return self._store.list_experiments()

    def list_snapshots(self) -> list[dict[str, Any]]:
        return self._store.list_snapshots()

    def ensure_champion(
        self,
        *,
        artifact_path: str,
        artifact_sha256: str,
        feature_schema_version: int = 1,
    ) -> dict[str, Any]:
        if self._weights_doc is None:
            import json
            from pathlib import Path

            self._weights_doc = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
        return ensure_champion(
            self._store,
            weights_doc=self._weights_doc,
            artifact_path=artifact_path,
            artifact_sha256=artifact_sha256,
            feature_schema_version=feature_schema_version,
        )

    def register_scheduler_jobs(self) -> None:
        self._scheduler.register(SchedulerJob("DAILY_LIGHT_REVIEW", 86400))
        self._scheduler.register(SchedulerJob("WEEKLY_RESEARCH_REVIEW", 604800))

    def run_scheduled_review(self, *, weekly: bool = False) -> dict[str, Any]:
        job_name = "WEEKLY_RESEARCH_REVIEW" if weekly else "DAILY_LIGHT_REVIEW"

        def handler() -> dict[str, Any]:
            review = self.run_weekly_review() if weekly else self.run_daily_review()
            return {"summary": f"{job_name}: {review.get('reason', 'ran')}", "result": review}

        return self._scheduler.run_due(job_name, handler=handler)

    def scheduler_status(self) -> dict[str, Any]:
        return {
            "leader": self._scheduler._owner,
            "daily": self._scheduler.status("DAILY_LIGHT_REVIEW"),
            "weekly": self._scheduler.status("WEEKLY_RESEARCH_REVIEW"),
        }

    def record_event_trigger(self, trigger_type: str, evidence: dict[str, Any], *, invoke: bool = False) -> dict[str, Any]:
        return self._trigger_ledger.record(trigger_type, evidence, invoke=invoke)

    def list_event_triggers(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._store.list_triggers(limit=limit)

    def _evaluation_service(self) -> EvaluationService:
        from defend_markets.quant.evaluation import PostgresOutcomeSource

        source = None
        if self._tools is not None and hasattr(self._tools, "_database"):
            source = PostgresOutcomeSource(self._tools._database)
        if source is None:

            class _EmptySource:
                def settled_predictions(self):
                    return []

                def prediction_counts(self):
                    return {"total": 0, "available": 0, "settled": 0}

            source = _EmptySource()
        return EvaluationService(self._store, outcome_source=source)

    def settle_and_evaluate(self) -> dict[str, Any]:
        service = self._evaluation_service()
        return {
            "settle": service.settle(),
            "metrics": service.compute_metrics(),
        }

    def evaluation_state(self) -> dict[str, Any]:
        return self._evaluation_service().evaluation_state()

    def prioritize_research(self) -> dict[str, Any]:
        prices = self._tools.price_observations()
        market_available = int(prices.get("observations", 0)) > 0
        hypotheses = seed_hypotheses(self._store, market_prices_available=market_available)
        selection = ResearchPrioritizer(market_prices_available=market_available).select_next(hypotheses)
        return {"hypotheses": hypotheses, "selection": selection}

    def record_ai_call_detailed(
        self,
        *,
        profile_alias: str,
        provider: str,
        model: str,
        trigger_type: str | None = None,
        state_hash: str | None = None,
        reason_for_route: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_input_tokens: int = 0,
    ) -> float:
        from defend_markets.quant.budget import record_call

        return record_call(
            self._store,
            profile_alias=profile_alias,
            provider=provider,
            model=model,
            trigger_type=trigger_type,
            state_hash=state_hash,
            reason_for_route=reason_for_route,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
        )

    def operational_tick(self) -> dict[str, Any]:
        if not self._settings.markets_ready:
            return {"executed": 0, "reason": f"runtime state is {self.markets_state()}; no operational execution"}
        executed = 0
        review_outcomes: dict[str, Any] = {}
        for weekly in (False, True):
            name = "weekly" if weekly else "daily"
            result = self.run_scheduled_review(weekly=weekly)
            review_outcomes[name] = result
            if result.get("ran"):
                executed += 1
        settle = self.settle_and_evaluate()
        inserted = int((settle.get("settle") or {}).get("inserted", 0))
        if inserted > 0:
            self.record_event_trigger("SETTLEMENT_BATCH_COMPLETED", {"inserted": inserted}, invoke=False)
        return {"executed": executed, "reviews": review_outcomes, "settlement": settle}

    def database_identity(self) -> dict[str, Any]:
        from urllib.parse import urlsplit

        info: dict[str, Any] = {"db_server": None, "db_port": None, "db_name": None, "schema_version": None}
        database = getattr(self._tools, "_database", None)
        if database is not None:
            url = getattr(database, "database_url", "")
            try:
                parsed = urlsplit(url)
                info["db_server"] = parsed.hostname
                info["db_port"] = parsed.port
                info["db_name"] = parsed.path.strip("/")
            except Exception:
                pass
            health = database.health()
            info["schema_version"] = health.get("schema_version")
        return info

    def latest_runtime_report(self) -> dict[str, Any] | None:
        artifact_dir = getattr(self._weekly_review, "_artifact_dir", None)
        if artifact_dir is None or not artifact_dir.is_dir():
            return None
        candidates = sorted(artifact_dir.glob("TT_MARKET_RESEARCH_REPORT_*.json"))
        if not candidates:
            return None
        import json as _json

        return _json.loads(candidates[-1].read_text(encoding="utf-8"))

    def operational_status(self) -> dict[str, Any]:
        prices = self._tools.price_observations()
        market_available = int(prices.get("observations", 0)) > 0
        evaluation_state = self.evaluation_state()
        metrics = self._store.latest_metric_snapshot()
        champions = self._store.list_champions()
        champion = champions[0] if champions else None
        scheduler = self.scheduler_status()
        usage = self._store.daily_ai_usage(datetime.now(timezone.utc).date().isoformat())
        return {
            "markets_state": self.markets_state(),
            "quant_director": self.health_state(),
            "database": self.database_identity(),
            "scheduler_leader": scheduler["leader"],
            "daily_job": scheduler["daily"],
            "weekly_job": scheduler["weekly"],
            "default_profile": self.runtime_profile(),
            "champion": {
                "model_id": champion["model_id"] if champion else None,
                "version": champion["model_version"] if champion else None,
                "hash": (champion["artifact_sha256"] or "")[:12] if champion else None,
            },
            "evaluation_state": evaluation_state,
            "metrics": {
                "brier": metrics.get("brier") if metrics else None,
                "log_loss": metrics.get("log_loss") if metrics else None,
                "ece": metrics.get("ece") if metrics else None,
                "drift_state": metrics.get("drift_state") if metrics else None,
            },
            "tt_market_coverage": "AVAILABLE" if market_available else "EMPTY",
            "ai_daily_calls": usage["calls"],
            "ai_daily_spend": usage["cost_usd"],
            "ai_hard_limit": self._settings.daily_cost_hard_limit,
            "last_triggers": self.list_event_triggers(limit=5),
        }
