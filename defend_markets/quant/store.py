"""Persistent storage for the Quant Director: research journal, model registry,
chat threads, and AI budget ledger. Postgres is the production surface;
InMemoryQuantStore mirrors it for unit tests. Writes are idempotent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from psycopg.types.json import Jsonb

from defend_markets.db import MarketsDatabase


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _today_utc() -> str:
    return _utcnow().date().isoformat()


class QuantStore:
    def create_research_entry(
        self,
        *,
        hypothesis: str,
        rationale: str | None = None,
        data_needed: str | None = None,
    ) -> int:
        raise NotImplementedError

    def list_research_entries(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def transition_research_entry(
        self, entry_id: int, *, status: str, result_summary: str | None = None, evidence: dict[str, Any] | None = None
    ) -> bool:
        raise NotImplementedError

    def register_model(
        self,
        *,
        model_id: str,
        model_version: str,
        role: str,
        stage: str,
        artifact_path: str | None = None,
        artifact_sha256: str | None = None,
        fit_n: int | None = None,
        cutoff: str | None = None,
        feature_schema_version: int | None = None,
    ) -> bool:
        raise NotImplementedError

    def list_models(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def champion(self) -> dict[str, Any] | None:
        raise NotImplementedError

    def create_thread(self, *, admin_account_id: str, title: str = "") -> int:
        raise NotImplementedError

    def append_message(
        self, *, thread_id: int, role: str, content: str, provenance: dict[str, Any] | None = None
    ) -> int:
        raise NotImplementedError

    def thread_messages(self, thread_id: int) -> list[dict[str, Any]]:
        raise NotImplementedError

    def budget_row(self, *, day: str, provider: str, model: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def record_ai_call(self, *, provider: str, model: str, cost: float) -> None:
        raise NotImplementedError

    def create_snapshot(self, snapshot: Any) -> bool:
        raise NotImplementedError

    def list_snapshots(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def save_experiment(self, *, spec: Any, result: Any) -> bool:
        raise NotImplementedError

    def list_experiments(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def save_review(self, outcome: Any) -> bool:
        raise NotImplementedError

    def list_reviews(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def list_champions(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def register_champion(self, *, model_id: str, model_version: str, artifact_path: str | None, artifact_sha256: str | None, fit_n: int | None, cutoff: str | None, feature_schema_version: int | None, promotion_provenance: str | None = None, dataset_provenance: str | None = None) -> str:
        raise NotImplementedError

    def upsert_job(self, job: dict[str, Any]) -> None:
        raise NotImplementedError

    def claim_job(self, job_name: str, owner: str, lease_seconds: int, now: Any = None) -> dict[str, Any] | None:
        raise NotImplementedError

    def complete_job(self, job_name: str, *, summary: str, state_hash: str | None, next_run_at: str) -> None:
        raise NotImplementedError

    def fail_job(self, job_name: str, *, error: str) -> None:
        raise NotImplementedError

    def job(self, job_name: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def record_trigger(self, trigger: dict[str, Any]) -> bool:
        raise NotImplementedError

    def list_triggers(self, limit: int = 100) -> list[dict[str, Any]]:
        raise NotImplementedError

    def insert_evaluation(self, evaluation: dict[str, Any]) -> bool:
        raise NotImplementedError

    def supersede_evaluation(self, evaluation_id: int) -> None:
        raise NotImplementedError

    def record_correction(self, correction: dict[str, Any]) -> None:
        raise NotImplementedError

    def evaluation_counts(self) -> dict[str, int]:
        raise NotImplementedError

    def list_evaluations(self, limit: int = 1000) -> list[dict[str, Any]]:
        raise NotImplementedError

    def insert_prediction_error(self, error: dict[str, Any]) -> bool:
        raise NotImplementedError

    def list_prediction_errors(self, limit: int = 1000) -> list[dict[str, Any]]:
        raise NotImplementedError

    def insert_metric_snapshot(self, snapshot: dict[str, Any]) -> None:
        raise NotImplementedError

    def latest_metric_snapshot(self) -> dict[str, Any] | None:
        raise NotImplementedError

    def record_ai_call_full(self, call: dict[str, Any]) -> None:
        raise NotImplementedError

    def list_ai_calls(self, limit: int = 200) -> list[dict[str, Any]]:
        raise NotImplementedError

    def daily_ai_usage(self, day: str) -> dict[str, Any]:
        raise NotImplementedError

    def upsert_hypothesis(self, hypothesis: dict[str, Any]) -> int:
        raise NotImplementedError

    def list_hypotheses(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def update_hypothesis_priority(self, hypothesis_id: int, *, priority_score: float, breakdown: dict[str, Any], blocked_reason: str | None) -> None:
        raise NotImplementedError

    def record_stage_transition(self, audit: dict[str, Any]) -> None:
        raise NotImplementedError

    def list_stage_transitions(self, model_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        raise NotImplementedError

    def upsert_shadow_prediction(self, spec: dict[str, Any]) -> bool:
        raise NotImplementedError

    def shadow_prediction_count(self, model_id: str | None = None) -> int:
        raise NotImplementedError

    def list_shadow_predictions(self, limit: int = 500) -> list[dict[str, Any]]:
        raise NotImplementedError

    def upsert_paper_entry(self, entry: dict[str, Any]) -> bool:
        raise NotImplementedError

    def list_paper_entries(self, limit: int = 500) -> list[dict[str, Any]]:
        raise NotImplementedError

    def upsert_weakness(self, spec: dict[str, Any]) -> int:
        raise NotImplementedError

    def list_weaknesses(self, limit: int = 500) -> list[dict[str, Any]]:
        raise NotImplementedError

    def add_weakness_evidence(self, evidence: dict[str, Any]) -> int:
        raise NotImplementedError

    def update_weakness_status(self, weakness_id: int, *, status: str) -> None:
        raise NotImplementedError

    def weakness_counts(self) -> dict[str, Any]:
        raise NotImplementedError

    def create_improvement_action(self, action: dict[str, Any]) -> int:
        raise NotImplementedError

    def list_improvement_actions(self, limit: int = 300) -> list[dict[str, Any]]:
        raise NotImplementedError

    def update_action_outcome(self, action_id: int, *, status: str, result_value: float | None, outcome: str) -> None:
        raise NotImplementedError

    def add_knowledge_finding(self, finding: dict[str, Any]) -> int:
        raise NotImplementedError

    def list_knowledge_findings(self, limit: int = 300) -> list[dict[str, Any]]:
        raise NotImplementedError

    def create_repair_packet(self, packet: dict[str, Any]) -> int:
        raise NotImplementedError

    def list_repair_packets(self, limit: int = 200) -> list[dict[str, Any]]:
        raise NotImplementedError

    def insert_decision_evaluation(self, evaluation: dict[str, Any]) -> bool:
        raise NotImplementedError

    def list_decision_evaluations(self, limit: int = 1000) -> list[dict[str, Any]]:
        raise NotImplementedError

    def decision_evaluation_counts(self) -> dict[str, int]:
        raise NotImplementedError

    def commit_paper_ticket(self, ticket: dict[str, Any]) -> bool:
        raise NotImplementedError

    def list_paper_tickets(self, limit: int = 500) -> list[dict[str, Any]]:
        raise NotImplementedError

    def upsert_bookmaker_coverage(self, entry: dict[str, Any]) -> None:
        raise NotImplementedError

    def list_bookmaker_coverage(self, limit: int = 200) -> list[dict[str, Any]]:
        raise NotImplementedError

    def upsert_official_prediction(self, spec: dict[str, Any]) -> bool:
        raise NotImplementedError

    def list_official_predictions(self, limit: int = 2000) -> list[dict[str, Any]]:
        raise NotImplementedError

    def official_prediction_counts(self) -> dict[str, int]:
        raise NotImplementedError

    def insert_settlement(self, spec: dict[str, Any]) -> bool:
        raise NotImplementedError

    def list_settlements(self, limit: int = 2000) -> list[dict[str, Any]]:
        raise NotImplementedError

    def insert_forward_score(self, spec: dict[str, Any]) -> bool:
        raise NotImplementedError

    def list_forward_scores(self, limit: int = 2000) -> list[dict[str, Any]]:
        raise NotImplementedError


class PostgresQuantStore(QuantStore):
    def __init__(self, database: MarketsDatabase) -> None:
        self._database = database

    def create_research_entry(self, *, hypothesis, rationale=None, data_needed=None):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_research_journal (hypothesis, rationale, data_needed) "
                "VALUES (%s, %s, %s) RETURNING entry_id",
                (hypothesis, rationale, data_needed),
            )
            return int(cursor.fetchone()[0])

    def list_research_entries(self):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT entry_id, hypothesis, rationale, status, data_needed, "
                "result_summary, decision, model_version, created_at, updated_at "
                "FROM quant_research_journal ORDER BY entry_id DESC"
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def transition_research_entry(self, entry_id, *, status, result_summary=None, evidence=None):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE quant_research_journal SET status = %s, "
                "result_summary = COALESCE(%s, result_summary), "
                "evidence = COALESCE(%s, evidence), updated_at = now() "
                "WHERE entry_id = %s RETURNING entry_id",
                (status, result_summary, Jsonb(evidence or {}), entry_id),
            )
            return cursor.fetchone() is not None

    def register_model(self, *, model_id, model_version, role, stage, artifact_path=None, artifact_sha256=None, fit_n=None, cutoff=None, feature_schema_version=None):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_model_registry "
                "(model_id, model_version, role, stage, artifact_path, artifact_sha256, fit_n, cutoff, feature_schema_version) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (model_id, model_version) DO UPDATE SET "
                "role = EXCLUDED.role, stage = EXCLUDED.stage, updated_at = now() "
                "RETURNING model_id",
                (model_id, model_version, role, stage, artifact_path, artifact_sha256, fit_n, cutoff, feature_schema_version),
            )
            return cursor.fetchone() is not None

    def list_models(self):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT model_id, model_version, role, stage, artifact_path, "
                "artifact_sha256, fit_n, cutoff, feature_schema_version, created_at, updated_at "
                "FROM quant_model_registry ORDER BY model_id, model_version"
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def champion(self):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT model_id, model_version, role, stage, artifact_path, artifact_sha256, "
                "fit_n, cutoff, feature_schema_version, updated_at "
                "FROM quant_model_registry WHERE role = %s ORDER BY updated_at DESC LIMIT 1",
                ("CHAMPION",),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [column.name for column in cursor.description]
            return dict(zip(columns, row))

    def create_thread(self, *, admin_account_id, title=""):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_chat_threads (admin_account_id, title) VALUES (%s, %s) RETURNING thread_id",
                (admin_account_id, title),
            )
            return int(cursor.fetchone()[0])

    def append_message(self, *, thread_id, role, content, provenance=None):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_chat_messages (thread_id, role, content, provenance) VALUES (%s, %s, %s, %s) "
                "RETURNING message_id",
                (thread_id, role, content, Jsonb(provenance or {})),
            )
            cursor.execute("UPDATE quant_chat_threads SET updated_at = now() WHERE thread_id = %s", (thread_id,))
            return int(cursor.fetchone()[0])

    def thread_messages(self, thread_id):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT message_id, role, content, provenance, created_at "
                "FROM quant_chat_messages WHERE thread_id = %s ORDER BY message_id",
                (thread_id,),
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def budget_row(self, *, day, provider, model):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT day, provider, model, call_count, cost_usd, updated_at "
                "FROM quant_ai_budget_ledger WHERE day = %s AND provider = %s AND model = %s",
                (day, provider, model),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [column.name for column in cursor.description]
            return dict(zip(columns, row))

    def record_ai_call(self, *, provider, model, cost):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_ai_budget_ledger (day, provider, model, call_count, cost_usd) "
                "VALUES (%s, %s, %s, 1, %s) "
                "ON CONFLICT (day, provider, model) DO UPDATE SET "
                "call_count = quant_ai_budget_ledger.call_count + 1, "
                "cost_usd = quant_ai_budget_ledger.cost_usd + EXCLUDED.cost_usd, "
                "updated_at = now()",
                (_today_utc(), provider, model, cost),
            )

    def create_snapshot(self, snapshot):
        document = snapshot.to_dict()
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_dataset_snapshots "
                "(snapshot_id, created_at, cutoff, target_definition, source_query_version, "
                "feature_schema_version, row_count, event_count, player_count, date_min, date_max, "
                "content_hash, excluded_row_counts, leakage_checks, provenance) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (snapshot_id) DO NOTHING RETURNING snapshot_id",
                (
                    document["snapshot_id"],
                    document["created_at"],
                    document["cutoff"],
                    document["target_definition"],
                    document["source_query_version"],
                    document["feature_schema_version"],
                    document["row_count"],
                    document["event_count"],
                    document["player_count"],
                    document["date_min"],
                    document["date_max"],
                    document["content_hash"],
                    Jsonb(document["excluded_row_counts"]),
                    Jsonb(document["leakage_checks"]),
                    Jsonb(document["provenance"]),
                ),
            )
            return cursor.fetchone() is not None

    def list_snapshots(self):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT snapshot_id, created_at, cutoff, target_definition, source_query_version, "
                "feature_schema_version, row_count, event_count, player_count, date_min, date_max, "
                "content_hash, excluded_row_counts, leakage_checks, provenance "
                "FROM quant_dataset_snapshots ORDER BY created_at DESC"
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def save_experiment(self, *, spec, result):
        spec_doc = spec.to_dict()
        result_doc = result.to_dict()
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_experiments "
                "(experiment_id, hypothesis_id, dataset_snapshot_id, champion_version, challenger_name, "
                "feature_set, algorithm, hyperparameters, seed, training_window, validation_windows, "
                "calibration_method, metrics_requested, created_by, code_commit, result, decision) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (experiment_id) DO UPDATE SET result = EXCLUDED.result, "
                "decision = EXCLUDED.decision",
                (
                    spec_doc["experiment_id"],
                    spec_doc["hypothesis_id"],
                    spec_doc["dataset_snapshot_id"],
                    spec_doc["champion_version"],
                    spec_doc["challenger_name"],
                    Jsonb(spec_doc["feature_set"]),
                    spec_doc["algorithm"],
                    Jsonb(spec_doc["hyperparameters"]),
                    spec_doc["seed"],
                    Jsonb(spec_doc["training_window"]),
                    Jsonb(spec_doc["validation_windows"]),
                    spec_doc["calibration_method"],
                    Jsonb(spec_doc["metrics_requested"]),
                    spec_doc["created_by"],
                    spec_doc["code_commit"],
                    Jsonb(result_doc),
                    result_doc["decision"],
                ),
            )
            for fold in result_doc.get("folds", []):
                cursor.execute(
                    "INSERT INTO quant_experiment_folds "
                    "(experiment_id, fold_index, train_start, train_end, val_start, val_end, "
                    "train_rows, val_rows, brier, log_loss, calibration_error, metrics) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (experiment_id, fold_index) DO UPDATE SET metrics = EXCLUDED.metrics",
                    (
                        spec_doc["experiment_id"],
                        fold["index"],
                        fold.get("train_start"),
                        fold.get("train_end"),
                        fold.get("val_start"),
                        fold.get("val_end"),
                        fold.get("train_rows"),
                        fold.get("val_rows"),
                        fold.get("brier"),
                        fold.get("log_loss"),
                        fold.get("calibration_error"),
                        Jsonb(fold.get("metrics", {})),
                    ),
                )
            return True

    def list_experiments(self):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT experiment_id, hypothesis_id, dataset_snapshot_id, champion_version, "
                "challenger_name, feature_set, algorithm, created_at, decision, result "
                "FROM quant_experiments ORDER BY created_at DESC"
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def save_review(self, outcome):
        document = outcome.to_dict()
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_review_runs (kind, started_at, completed_at, ran, reason, report) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING review_id",
                (
                    document["kind"],
                    document["started_at"],
                    document["completed_at"],
                    document["ran"],
                    document["reason"],
                    Jsonb(document["report"]),
                ),
            )
            return cursor.fetchone() is not None

    def list_reviews(self):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT review_id, kind, started_at, completed_at, ran, reason, report "
                "FROM quant_review_runs ORDER BY review_id DESC LIMIT 100"
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def list_champions(self):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT model_id, model_version, stage, artifact_path, artifact_sha256, fit_n, cutoff, "
                "feature_schema_version, created_at, updated_at "
                "FROM quant_model_registry WHERE role = 'CHAMPION' ORDER BY updated_at DESC"
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def register_champion(self, *, model_id, model_version, artifact_path, artifact_sha256, fit_n, cutoff, feature_schema_version, promotion_provenance=None, dataset_provenance=None):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_model_registry "
                "(model_id, model_version, role, stage, artifact_path, artifact_sha256, fit_n, cutoff, feature_schema_version) "
                "VALUES (%s, %s, 'CHAMPION', 'CHAMPION', %s, %s, %s, %s, %s) "
                "ON CONFLICT (model_id, model_version) DO UPDATE SET "
                "stage = 'CHAMPION', role = 'CHAMPION', artifact_path = EXCLUDED.artifact_path, "
                "artifact_sha256 = EXCLUDED.artifact_sha256, updated_at = now() "
                "RETURNING model_id",
                (model_id, model_version, artifact_path, artifact_sha256, fit_n, cutoff, feature_schema_version),
            )
            return cursor.fetchone()[0]

    def upsert_job(self, job):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_scheduler_jobs "
                "(job_name, enabled, schedule_interval_seconds, next_run_at, status, last_result_summary, last_state_hash) "
                "VALUES (%s, %s, %s, %s, 'IDLE', %s, %s) "
                "ON CONFLICT (job_name) DO UPDATE SET enabled = EXCLUDED.enabled, "
                "schedule_interval_seconds = EXCLUDED.schedule_interval_seconds",
                (
                    job["job_name"],
                    bool(job.get("enabled", True)),
                    int(job["schedule_interval_seconds"]),
                    job["next_run_at"],
                    job.get("last_result_summary"),
                    job.get("last_state_hash"),
                ),
            )

    def claim_job(self, job_name, owner, lease_seconds, now=None):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE quant_scheduler_jobs SET "
                "lease_owner = %s, lease_expires_at = now() + make_interval(secs => %s), "
                "status = 'RUNNING', attempt_count = attempt_count + 1, last_started_at = now() "
                "WHERE job_name = %s AND enabled = TRUE "
                "AND next_run_at <= now() "
                "AND (status <> 'RUNNING' OR lease_expires_at IS NULL OR lease_expires_at < now()) "
                "RETURNING job_name, enabled, schedule_interval_seconds, next_run_at, status, attempt_count",
                (owner, lease_seconds, job_name),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [column.name for column in cursor.description]
            return dict(zip(columns, row))

    def complete_job(self, job_name, *, summary, state_hash, next_run_at):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE quant_scheduler_jobs SET status = 'COMPLETED', last_completed_at = now(), "
                "last_result_summary = %s, last_state_hash = %s, next_run_at = %s, "
                "lease_owner = NULL, lease_expires_at = NULL WHERE job_name = %s",
                (summary, state_hash, next_run_at, job_name),
            )

    def fail_job(self, job_name, *, error):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE quant_scheduler_jobs SET status = 'FAILED', last_error = %s, "
                "lease_owner = NULL, lease_expires_at = NULL, "
                "next_run_at = now() + interval '1 hour' WHERE job_name = %s",
                (error, job_name),
            )

    def job(self, job_name):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT job_name, enabled, schedule_interval_seconds, last_started_at, last_completed_at, "
                "next_run_at, status, last_result_summary, last_error, last_state_hash, lease_owner, "
                "lease_expires_at, attempt_count FROM quant_scheduler_jobs WHERE job_name = %s",
                (job_name,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [column.name for column in cursor.description]
            return dict(zip(columns, row))

    def record_trigger(self, trigger):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_trigger_events "
                "(trigger_type, severity, trigger_evidence, state_hash, first_seen_at, last_seen_at, last_invoked_at, invocation_result) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (trigger_type, state_hash) DO UPDATE SET "
                "last_seen_at = EXCLUDED.last_seen_at, "
                "suppressed_count = quant_trigger_events.suppressed_count + 1 "
                "RETURNING trigger_id",
                (
                    trigger["trigger_type"],
                    trigger["severity"],
                    Jsonb(trigger.get("trigger_evidence", {})),
                    trigger["state_hash"],
                    trigger["first_seen_at"],
                    trigger["last_seen_at"],
                    trigger.get("last_invoked_at"),
                    trigger.get("invocation_result"),
                ),
            )
            return cursor.fetchone() is not None

    def list_triggers(self, limit=100):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT trigger_id, trigger_type, severity, trigger_evidence, state_hash, first_seen_at, "
                "last_seen_at, last_invoked_at, invocation_result, suppressed_count "
                "FROM quant_trigger_events ORDER BY last_seen_at DESC LIMIT %s",
                (limit,),
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def insert_evaluation(self, evaluation):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_evaluations "
                "(prediction_id, event_id, model_id, model_version, prediction_ts, predicted_probability, actual, outcome_version, "
                "brier_contribution, logloss_contribution, abs_probability_error) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (prediction_id, event_id, model_id, model_version, prediction_ts, outcome_version) DO NOTHING "
                "RETURNING evaluation_id",
                (
                    evaluation["prediction_id"],
                    evaluation["event_id"],
                    evaluation["model_id"],
                    evaluation["model_version"],
                    evaluation["prediction_ts"],
                    evaluation["predicted_probability"],
                    evaluation["actual"],
                    evaluation["outcome_version"],
                    evaluation.get("brier_contribution"),
                    evaluation.get("logloss_contribution"),
                    evaluation.get("abs_probability_error"),
                ),
            )
            return cursor.fetchone() is not None

    def supersede_evaluation(self, evaluation_id):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE quant_evaluations SET status = 'SUPERSEDED' WHERE evaluation_id = %s",
                (evaluation_id,),
            )

    def record_correction(self, correction):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_result_corrections "
                "(event_id, evaluation_id, previous_actual, new_actual, source) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    correction["event_id"],
                    correction["evaluation_id"],
                    correction["previous_actual"],
                    correction["new_actual"],
                    correction["source"],
                ),
            )

    def evaluation_counts(self):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM quant_evaluations WHERE status = 'ACTIVE'")
            active = int(cursor.fetchone()[0])
            cursor.execute("SELECT count(*) FROM quant_evaluations WHERE status = 'SUPERSEDED'")
            superseded = int(cursor.fetchone()[0])
        return {"active": active, "superseded": superseded}

    def list_evaluations(self, limit=1000):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT evaluation_id, prediction_id, event_id, model_id, model_version, prediction_ts, "
                "predicted_probability, actual, outcome_version, brier_contribution, logloss_contribution, "
                "abs_probability_error, status, created_at "
                "FROM quant_evaluations ORDER BY evaluation_id DESC LIMIT %s",
                (limit,),
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def insert_prediction_error(self, error):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_prediction_errors "
                "(evaluation_id, event_id, prediction_id, prediction_ts, model_id, model_version, predicted_probability, "
                "predicted_side, actual, abs_probability_error, brier_contribution, logloss_contribution, confidence_band, "
                "feature_vector_ref, history_depth_metadata, league, market_data_available) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (evaluation_id) DO NOTHING RETURNING error_id",
                (
                    error["evaluation_id"],
                    error["event_id"],
                    error["prediction_id"],
                    error["prediction_ts"],
                    error["model_id"],
                    error["model_version"],
                    error["predicted_probability"],
                    error.get("predicted_side"),
                    error["actual"],
                    error["abs_probability_error"],
                    error["brier_contribution"],
                    error["logloss_contribution"],
                    error.get("confidence_band"),
                    error.get("feature_vector_ref"),
                    Jsonb(error.get("history_depth_metadata", {})),
                    error.get("league"),
                    error.get("market_data_available"),
                ),
            )
            return cursor.fetchone() is not None

    def list_prediction_errors(self, limit=1000):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT error_id, evaluation_id, event_id, prediction_id, prediction_ts, model_id, model_version, "
                "predicted_probability, predicted_side, actual, abs_probability_error, brier_contribution, "
                "logloss_contribution, confidence_band, history_depth_metadata, league, market_data_available, created_at "
                "FROM quant_prediction_errors ORDER BY error_id DESC LIMIT %s",
                (limit,),
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def insert_metric_snapshot(self, snapshot):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_metric_snapshots "
                "(metric_calculation_version, computed_at, state_hash, brier, log_loss, ece, evaluation_rows, drift_state, detail) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    snapshot["metric_calculation_version"],
                    snapshot["computed_at"],
                    snapshot["state_hash"],
                    snapshot.get("brier"),
                    snapshot.get("log_loss"),
                    snapshot.get("ece"),
                    snapshot["evaluation_rows"],
                    snapshot["drift_state"],
                    Jsonb(snapshot.get("detail", {})),
                ),
            )

    def latest_metric_snapshot(self):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT snapshot_id, metric_calculation_version, computed_at, state_hash, brier, log_loss, ece, "
                "evaluation_rows, drift_state, detail FROM quant_metric_snapshots ORDER BY snapshot_id DESC LIMIT 1"
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [column.name for column in cursor.description]
            return dict(zip(columns, row))

    def record_ai_call_full(self, call):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_ai_calls "
                "(trigger_type, state_hash, profile_alias, actual_provider, actual_model, reason_for_route, "
                "input_tokens, cached_input_tokens, output_tokens, estimated_cost_usd, latency_ms, retry_count, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    call.get("trigger_type"),
                    call.get("state_hash"),
                    call["profile_alias"],
                    call["actual_provider"],
                    call["actual_model"],
                    call.get("reason_for_route"),
                    call.get("input_tokens"),
                    call.get("cached_input_tokens"),
                    call.get("output_tokens"),
                    call.get("estimated_cost_usd", 0.0),
                    call.get("latency_ms"),
                    call.get("retry_count", 0),
                    call["status"],
                ),
            )

    def list_ai_calls(self, limit=200):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT call_id, trigger_type, state_hash, profile_alias, actual_provider, actual_model, "
                "reason_for_route, input_tokens, cached_input_tokens, output_tokens, estimated_cost_usd, "
                "latency_ms, retry_count, status, created_at FROM quant_ai_calls ORDER BY call_id DESC LIMIT %s",
                (limit,),
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def daily_ai_usage(self, day):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*), COALESCE(sum(estimated_cost_usd), 0) FROM quant_ai_calls "
                "WHERE created_at::date = %s::date",
                (day,),
            )
            row = cursor.fetchone()
        return {"calls": int(row[0]), "cost_usd": round(float(row[1]), 8)}

    def upsert_hypothesis(self, hypothesis):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_hypotheses "
                "(source, title, supporting_observation, status, rejection_reason, dependencies, data_requirements, priority_score, priority_breakdown, blocked_reason) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (title, source) DO UPDATE SET status = EXCLUDED.status, "
                "rejection_reason = COALESCE(EXCLUDED.rejection_reason, quant_hypotheses.rejection_reason) "
                "RETURNING hypothesis_id",
                (
                    hypothesis["source"],
                    hypothesis["title"],
                    hypothesis.get("supporting_observation"),
                    hypothesis.get("status", "PROPOSED"),
                    hypothesis.get("rejection_reason"),
                    Jsonb(hypothesis.get("dependencies", [])),
                    hypothesis.get("data_requirements"),
                    hypothesis.get("priority_score"),
                    Jsonb(hypothesis.get("priority_breakdown", {})),
                    hypothesis.get("blocked_reason"),
                ),
            )
            return int(cursor.fetchone()[0])

    def list_hypotheses(self):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT hypothesis_id, source, title, supporting_observation, status, rejection_reason, "
                "dependencies, data_requirements, last_evaluated_at, priority_score, priority_breakdown, "
                "blocked_reason, created_at FROM quant_hypotheses ORDER BY priority_score DESC NULLS LAST, hypothesis_id"
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def update_hypothesis_priority(self, hypothesis_id, *, priority_score, breakdown, blocked_reason):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE quant_hypotheses SET priority_score = %s, priority_breakdown = %s, blocked_reason = %s "
                "WHERE hypothesis_id = %s",
                (priority_score, Jsonb(breakdown), blocked_reason, hypothesis_id),
            )

    def record_stage_transition(self, audit):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_stage_audit "
                "(model_id, model_version, from_stage, to_stage, experiment_id, gate_version, gate_results, metric_deltas, actor, reason, code_commit) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    audit["model_id"],
                    audit["model_version"],
                    audit.get("from_stage"),
                    audit["to_stage"],
                    audit.get("experiment_id"),
                    audit.get("gate_version"),
                    Jsonb(audit.get("gate_results", {})),
                    Jsonb(audit.get("metric_deltas", {})),
                    audit["actor"],
                    audit.get("reason"),
                    audit.get("code_commit"),
                ),
            )

    def list_stage_transitions(self, model_id=None, limit=200):
        with self._database.connect() as connection, connection.cursor() as cursor:
            if model_id is None:
                cursor.execute(
                    "SELECT audit_id, model_id, model_version, from_stage, to_stage, experiment_id, gate_version, "
                    "gate_results, metric_deltas, actor, reason, code_commit, created_at "
                    "FROM quant_stage_audit ORDER BY audit_id DESC LIMIT %s",
                    (limit,),
                )
            else:
                cursor.execute(
                    "SELECT audit_id, model_id, model_version, from_stage, to_stage, experiment_id, gate_version, "
                    "gate_results, metric_deltas, actor, reason, code_commit, created_at "
                    "FROM quant_stage_audit WHERE model_id = %s ORDER BY audit_id DESC LIMIT %s",
                    (model_id, limit),
                )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def upsert_shadow_prediction(self, spec):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_shadow_predictions "
                "(canonical_event_id, model_id, model_version, feature_snapshot_id, generated_at, p_a, availability) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (canonical_event_id, model_id, model_version) DO NOTHING "
                "RETURNING shadow_prediction_id",
                (
                    spec["canonical_event_id"],
                    spec["model_id"],
                    spec["model_version"],
                    spec["feature_snapshot_id"],
                    spec["generated_at"],
                    spec["p_a"],
                    spec["availability"],
                ),
            )
            return cursor.fetchone() is not None

    def shadow_prediction_count(self, model_id=None):
        with self._database.connect() as connection, connection.cursor() as cursor:
            if model_id is None:
                cursor.execute("SELECT count(*) FROM quant_shadow_predictions")
            else:
                cursor.execute(
                    "SELECT count(*) FROM quant_shadow_predictions WHERE model_id = %s",
                    (model_id,),
                )
            return int(cursor.fetchone()[0])

    def list_shadow_predictions(self, limit=500):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT shadow_prediction_id, canonical_event_id, model_id, model_version, "
                "feature_snapshot_id, generated_at, p_a, availability, created_at "
                "FROM quant_shadow_predictions ORDER BY shadow_prediction_id DESC LIMIT %s",
                (limit,),
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def upsert_paper_entry(self, entry):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_paper_ledger "
                "(canonical_event_id, provider_event_id, decision, reason, model_p_a, market_p_a, "
                "bookmaker, price, observation_id, model_id, model_version) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (canonical_event_id) DO NOTHING RETURNING entry_id",
                (
                    entry["canonical_event_id"],
                    entry.get("provider_event_id"),
                    entry["decision"],
                    entry["reason"],
                    entry.get("model_p_a"),
                    entry.get("market_p_a"),
                    entry.get("bookmaker"),
                    entry.get("price"),
                    entry.get("observation_id"),
                    entry.get("model_id"),
                    entry.get("model_version"),
                ),
            )
            return cursor.fetchone() is not None

    def list_paper_entries(self, limit=500):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT entry_id, canonical_event_id, provider_event_id, decision, reason, model_p_a, "
                "market_p_a, bookmaker, price, observation_id, model_id, model_version, created_at "
                "FROM quant_paper_ledger ORDER BY entry_id DESC LIMIT %s",
                (limit,),
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def upsert_weakness(self, spec):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_weaknesses "
                "(weakness_type, category, title, description, status, severity, confidence, progress_impact, "
                "first_detected_at, last_observed_at, affected_scope, affected_competition, affected_players, "
                "affected_market, affected_model, blocking_capability, root_cause_state, recommended_action_type, "
                "auto_action_allowed, priority_score, state_hash) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (weakness_type, state_hash) DO UPDATE SET "
                "last_observed_at = EXCLUDED.last_observed_at, "
                "evidence_count = quant_weaknesses.evidence_count + 1, "
                "sample_size = EXCLUDED.sample_size, "
                "severity = EXCLUDED.severity, "
                "updated_at = now() "
                "RETURNING weakness_id",
                (
                    spec["weakness_type"],
                    spec["category"],
                    spec["title"],
                    spec.get("description"),
                    spec.get("status", "DETECTED"),
                    spec.get("severity", "LOW"),
                    spec.get("confidence", "EARLY_SIGNAL"),
                    spec.get("progress_impact"),
                    spec["first_detected_at"],
                    spec["last_observed_at"],
                    spec.get("affected_scope"),
                    spec.get("affected_competition"),
                    spec.get("affected_players"),
                    spec.get("affected_market"),
                    spec.get("affected_model"),
                    spec.get("blocking_capability"),
                    spec.get("root_cause_state"),
                    spec.get("recommended_action_type"),
                    spec.get("auto_action_allowed", False),
                    spec.get("priority_score"),
                    spec["state_hash"],
                ),
            )
            return int(cursor.fetchone()[0])

    def list_weaknesses(self, limit=500):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT weakness_id, weakness_type, category, title, description, status, severity, confidence, "
                "progress_impact, first_detected_at, last_observed_at, evidence_count, sample_size, affected_scope, "
                "affected_competition, affected_players, affected_market, affected_model, blocking_capability, "
                "root_cause_state, recommended_action_type, auto_action_allowed, priority_score, state_hash, "
                "prior_resolution, reopened_at, created_at, updated_at "
                "FROM quant_weaknesses ORDER BY priority_score DESC NULLS LAST, weakness_id"
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()][:limit]

    def add_weakness_evidence(self, evidence):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_weakness_evidence "
                "(weakness_id, evidence_type, metric_name, metric_value, sample_size, comparison_value, time_window, "
                "competition, model, market, source_ref, observed_at, payload_hash) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING evidence_id",
                (
                    evidence["weakness_id"],
                    evidence["evidence_type"],
                    evidence["metric_name"],
                    evidence.get("metric_value"),
                    evidence.get("sample_size"),
                    evidence.get("comparison_value"),
                    evidence.get("time_window"),
                    evidence.get("competition"),
                    evidence.get("model"),
                    evidence.get("market"),
                    evidence.get("source_ref"),
                    evidence["observed_at"],
                    evidence.get("payload_hash"),
                ),
            )
            return int(cursor.fetchone()[0])

    def update_weakness_status(self, weakness_id, *, status):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE quant_weaknesses SET status = %s, updated_at = now() WHERE weakness_id = %s",
                (status, weakness_id),
            )

    def weakness_counts(self):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT status, count(*) FROM quant_weaknesses GROUP BY status ORDER BY status"
            )
            by_status = {str(row[0]): int(row[1]) for row in cursor.fetchall()}
            cursor.execute("SELECT count(*) FROM quant_weaknesses")
            total = int(cursor.fetchone()[0])
        return {"total": total, "by_status": by_status}

    def create_improvement_action(self, action):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_improvement_actions "
                "(weakness_id, action_type, description, expected_effect, status, risk, estimated_cost, "
                "requires_owner, verification_metric, baseline_value) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING action_id",
                (
                    action["weakness_id"],
                    action["action_type"],
                    action.get("description"),
                    action.get("expected_effect"),
                    action.get("status", "PROPOSED"),
                    action.get("risk"),
                    action.get("estimated_cost"),
                    action.get("requires_owner", False),
                    action.get("verification_metric"),
                    action.get("baseline_value"),
                ),
            )
            return int(cursor.fetchone()[0])

    def list_improvement_actions(self, limit=300):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT action_id, weakness_id, action_type, description, expected_effect, status, risk, "
                "estimated_cost, requires_owner, created_at, started_at, completed_at, verification_metric, "
                "baseline_value, result_value, outcome "
                "FROM quant_improvement_actions ORDER BY action_id DESC LIMIT %s",
                (limit,),
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def update_action_outcome(self, action_id, *, status, result_value, outcome):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE quant_improvement_actions SET status = %s, result_value = %s, outcome = %s, "
                "completed_at = now() WHERE action_id = %s",
                (status, result_value, outcome, action_id),
            )

    def add_knowledge_finding(self, finding):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_knowledge_findings "
                "(research_task_id, weakness_id, claim, source, source_type, retrieved_at, confidence, scope, "
                "valid_from, valid_until, point_in_time_safe, approved_for_feature_use, notes) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING finding_id",
                (
                    finding.get("research_task_id"),
                    finding.get("weakness_id"),
                    finding["claim"],
                    finding.get("source"),
                    finding.get("source_type"),
                    finding["retrieved_at"],
                    finding.get("confidence", "EARLY_SIGNAL"),
                    finding.get("scope"),
                    finding.get("valid_from"),
                    finding.get("valid_until"),
                    finding.get("point_in_time_safe", False),
                    finding.get("approved_for_feature_use", False),
                    finding.get("notes"),
                ),
            )
            return int(cursor.fetchone()[0])

    def list_knowledge_findings(self, limit=300):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT finding_id, research_task_id, weakness_id, claim, source, source_type, retrieved_at, "
                "confidence, scope, valid_from, valid_until, point_in_time_safe, approved_for_feature_use, notes, created_at "
                "FROM quant_knowledge_findings ORDER BY finding_id DESC LIMIT %s",
                (limit,),
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def create_repair_packet(self, packet):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_repair_packets "
                "(weakness_id, symptom, reproduction, evidence, suspected_boundary, failing_invariant, "
                "expected_behavior, suggested_test, likely_files, risk, acceptance_criteria, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING packet_id",
                (
                    packet.get("weakness_id"),
                    packet["symptom"],
                    packet.get("reproduction"),
                    Jsonb(packet.get("evidence", {})),
                    packet.get("suspected_boundary"),
                    packet.get("failing_invariant"),
                    packet.get("expected_behavior"),
                    packet.get("suggested_test"),
                    Jsonb(packet.get("likely_files", [])),
                    packet.get("risk"),
                    packet.get("acceptance_criteria"),
                    packet.get("status", "PENDING"),
                ),
            )
            return int(cursor.fetchone()[0])

    def list_repair_packets(self, limit=200):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT packet_id, weakness_id, symptom, reproduction, evidence, suspected_boundary, "
                "failing_invariant, expected_behavior, suggested_test, likely_files, risk, acceptance_criteria, "
                "status, created_at FROM quant_repair_packets ORDER BY packet_id DESC LIMIT %s",
                (limit,),
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def insert_decision_evaluation(self, evaluation):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_decision_evaluations "
                "(canonical_event_id, provider_event_id, model_id, model_version, strategy, decision, reason, "
                "decision_ts, model_p_a, market_p_a, bookmaker, price, observation_id, feature_snapshot_id, legacy_ledger_entry_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING evaluation_id",
                (
                    evaluation["canonical_event_id"],
                    evaluation.get("provider_event_id"),
                    evaluation["model_id"],
                    evaluation["model_version"],
                    evaluation["strategy"],
                    evaluation["decision"],
                    evaluation["reason"],
                    evaluation["decision_ts"],
                    evaluation.get("model_p_a"),
                    evaluation.get("market_p_a"),
                    evaluation.get("bookmaker"),
                    evaluation.get("price"),
                    evaluation.get("observation_id"),
                    evaluation.get("feature_snapshot_id"),
                    evaluation.get("legacy_ledger_entry_id"),
                ),
            )
            return cursor.fetchone() is not None

    def list_decision_evaluations(self, limit=1000):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT evaluation_id, canonical_event_id, provider_event_id, model_id, model_version, strategy, "
                "decision, reason, decision_ts, model_p_a, market_p_a, bookmaker, price, observation_id, "
                "feature_snapshot_id, legacy_ledger_entry_id, created_at "
                "FROM quant_decision_evaluations ORDER BY evaluation_id DESC LIMIT %s",
                (limit,),
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def decision_evaluation_counts(self):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM quant_decision_evaluations")
            total = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT decision, count(*) FROM quant_decision_evaluations GROUP BY decision"
            )
            by_decision = {str(row[0]): int(row[1]) for row in cursor.fetchall()}
        return {"total": total, "by_decision": by_decision}

    def commit_paper_ticket(self, ticket):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_paper_tickets "
                "(canonical_event_id, provider_event_id, strategy, model_id, model_version, side, selection, price, "
                "stake, model_p_a, market_p_a, market_observation_id, feature_snapshot_id, decision_ts) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (canonical_event_id, strategy, model_id, decision_ts) DO NOTHING "
                "RETURNING ticket_id",
                (
                    ticket["canonical_event_id"],
                    ticket.get("provider_event_id"),
                    ticket["strategy"],
                    ticket["model_id"],
                    ticket["model_version"],
                    ticket["side"],
                    ticket.get("selection"),
                    ticket["price"],
                    ticket.get("stake"),
                    ticket.get("model_p_a"),
                    ticket.get("market_p_a"),
                    ticket.get("market_observation_id"),
                    ticket.get("feature_snapshot_id"),
                    ticket["decision_ts"],
                ),
            )
            return cursor.fetchone() is not None

    def list_paper_tickets(self, limit=500):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT ticket_id, canonical_event_id, provider_event_id, strategy, model_id, model_version, side, "
                "selection, price, stake, model_p_a, market_p_a, market_observation_id, feature_snapshot_id, "
                "decision_ts, committed_at, result_actual, paper_pnl, created_at "
                "FROM quant_paper_tickets ORDER BY ticket_id DESC LIMIT %s",
                (limit,),
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def upsert_bookmaker_coverage(self, entry):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_bookmaker_coverage "
                "(bookmaker_id, sport_slug, attestation_state, selected, filtered_events, pending_events, live_events, "
                "priced_events, observations, competitions, market_types, coverage_window_start, coverage_window_end, "
                "first_observation_at, last_observation_at, last_attested_at, error_state, evidence_refs) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    entry["bookmaker_id"],
                    entry.get("sport_slug", "table-tennis"),
                    entry["attestation_state"],
                    entry.get("selected", False),
                    entry.get("filtered_events", 0),
                    entry.get("pending_events", 0),
                    entry.get("live_events", 0),
                    entry.get("priced_events", 0),
                    entry.get("observations", 0),
                    Jsonb(entry.get("competitions", {})),
                    Jsonb(entry.get("market_types", [])),
                    entry["coverage_window_start"],
                    entry["coverage_window_end"],
                    entry.get("first_observation_at"),
                    entry.get("last_observation_at"),
                    entry["last_attested_at"],
                    entry.get("error_state"),
                    Jsonb(entry.get("evidence_refs", [])),
                ),
            )

    def list_bookmaker_coverage(self, limit=200):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT coverage_id, bookmaker_id, sport_slug, attestation_state, selected, filtered_events, "
                "pending_events, live_events, priced_events, observations, competitions, market_types, "
                "coverage_window_start, coverage_window_end, first_observation_at, last_observation_at, "
                "last_attested_at, error_state, evidence_refs, created_at "
                "FROM quant_bookmaker_coverage ORDER BY bookmaker_id, last_attested_at DESC"
            )
            columns = [column.name for column in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            bookmaker_id = str(row["bookmaker_id"])
            if bookmaker_id not in latest:
                latest[bookmaker_id] = row
        return list(latest.values())[:limit]

    def upsert_official_prediction(self, spec):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_official_forward_predictions "
                "(canonical_event_id, model_id, model_version, model_hash, prediction_id, prediction_role, "
                "generated_at, commence_at, probability_a, feature_snapshot_id, frozen_forward, policy_version) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (canonical_event_id, model_id) DO NOTHING RETURNING official_prediction_id",
                (
                    spec["canonical_event_id"],
                    spec["model_id"],
                    spec["model_version"],
                    spec.get("model_hash"),
                    spec["prediction_id"],
                    spec["prediction_role"],
                    spec["generated_at"],
                    spec["commence_at"],
                    spec["probability_a"],
                    spec.get("feature_snapshot_id"),
                    spec.get("frozen_forward", True),
                    spec.get("policy_version", 1),
                ),
            )
            return cursor.fetchone() is not None

    def list_official_predictions(self, limit=2000):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT official_prediction_id, canonical_event_id, model_id, model_version, model_hash, "
                "prediction_id, prediction_role, generated_at, commence_at, probability_a, feature_snapshot_id, "
                "frozen_forward, policy_version, created_at "
                "FROM quant_official_forward_predictions ORDER BY official_prediction_id DESC LIMIT %s",
                (limit,),
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def official_prediction_counts(self):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT prediction_role, count(DISTINCT canonical_event_id) FROM quant_official_forward_predictions "
                "GROUP BY prediction_role"
            )
            by_role = {str(row[0]): int(row[1]) for row in cursor.fetchall()}
            cursor.execute("SELECT count(*) FROM quant_official_forward_predictions")
            total_rows = int(cursor.fetchone()[0])
        return {"total_rows": total_rows, "unique_events_by_role": by_role}

    def insert_settlement(self, spec):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_settlements "
                "(canonical_event_id, provider_event_id, competition, participant_a, participant_b, status, "
                "actual_a, actual_b, winner_side, source_result_id, source_provider, observed_at, raw_payload_hash, "
                "orientation_verified, revision, provider_result_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (canonical_event_id, source_result_id) DO NOTHING RETURNING settlement_id",
                (
                    spec["canonical_event_id"],
                    spec.get("provider_event_id"),
                    spec.get("competition"),
                    spec.get("participant_a"),
                    spec.get("participant_b"),
                    spec.get("status", "FINAL"),
                    spec.get("actual_a"),
                    spec.get("actual_b"),
                    spec.get("winner_side"),
                    spec["source_result_id"],
                    spec.get("source_provider", "odds_api_io"),
                    spec.get("observed_at"),
                    spec.get("raw_payload_hash"),
                    spec.get("orientation_verified", False),
                    spec.get("revision", 1),
                    spec.get("provider_result_id"),
                ),
            )
            return cursor.fetchone() is not None

    def list_settlements(self, limit=2000):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT settlement_id, canonical_event_id, provider_event_id, competition, participant_a, "
                "participant_b, status, actual_a, actual_b, winner_side, source_result_id, source_provider, "
                "observed_at, raw_payload_hash, orientation_verified, revision, supersedes_revision_id, "
                "provider_result_id, created_at "
                "FROM quant_settlements ORDER BY settlement_id DESC LIMIT %s",
                (limit,),
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def latest_final_settlement(self, canonical_event_id):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT settlement_id, canonical_event_id, provider_event_id, competition, participant_a, "
                "participant_b, status, actual_a, actual_b, winner_side, source_result_id, source_provider, "
                "observed_at, raw_payload_hash, orientation_verified, revision, supersedes_revision_id, "
                "provider_result_id, created_at "
                "FROM quant_settlements WHERE canonical_event_id = %s AND status = 'FINAL' "
                "ORDER BY revision DESC LIMIT 1",
                (canonical_event_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [column.name for column in cursor.description]
            return dict(zip(columns, row))

    def insert_settlement_revision(self, spec):
        """Insert a NEW settlement revision, superseding the prior FINAL.

        The old FINAL is marked SUPERSEDED with supersedes_revision_id linked;
        history is never mutated (P12/P13)."""
        with self._database.connect() as connection, connection.cursor() as cursor:
            connection.autocommit = False
            cursor.execute(
                "SELECT settlement_id FROM quant_settlements "
                "WHERE canonical_event_id = %s AND status = 'FINAL' ORDER BY revision DESC LIMIT 1",
                (spec["canonical_event_id"],),
            )
            row = cursor.fetchone()
            prior_id = int(row[0]) if row else None
            prior_revision = 0
            if prior_id is not None:
                cursor.execute(
                    "SELECT revision FROM quant_settlements WHERE settlement_id = %s",
                    (prior_id,),
                )
                prior_revision = int(cursor.fetchone()[0])
                cursor.execute(
                    "UPDATE quant_settlements SET status = 'SUPERSEDED', supersedes_revision_id = NULL "
                    "WHERE settlement_id = %s",
                    (prior_id,),
                )
            new_revision = prior_revision + 1
            cursor.execute(
                "INSERT INTO quant_settlements "
                "(canonical_event_id, provider_event_id, competition, participant_a, participant_b, status, "
                "actual_a, actual_b, winner_side, source_result_id, source_provider, observed_at, raw_payload_hash, "
                "orientation_verified, revision, supersedes_revision_id, provider_result_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "RETURNING settlement_id",
                (
                    spec["canonical_event_id"],
                    spec.get("provider_event_id"),
                    spec.get("competition"),
                    spec.get("participant_a"),
                    spec.get("participant_b"),
                    spec.get("status", "FINAL"),
                    spec.get("actual_a"),
                    spec.get("actual_b"),
                    spec.get("winner_side"),
                    spec["source_result_id"],
                    spec.get("source_provider", "odds_api_io"),
                    spec.get("observed_at"),
                    spec.get("raw_payload_hash"),
                    spec.get("orientation_verified", False),
                    new_revision,
                    prior_id,
                    spec.get("provider_result_id"),
                ),
            )
            new_id = int(cursor.fetchone()[0])
            connection.commit()
            connection.autocommit = True
            return new_id

    def record_result_request_evidence(self, row):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_result_request_evidence "
                "(request_id, provider, request_kind, requested_at, window_start, window_end, target_event_count, "
                "http_status, provider_request_status, response_schema_status, events_returned, events_matched, "
                "raw_payload_hash, error_class, successful_search_scope) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (request_id) DO NOTHING RETURNING request_evidence_id",
                (
                    row["request_id"],
                    row.get("provider", "odds_api_io"),
                    row["request_kind"],
                    row.get("requested_at"),
                    row.get("window_start"),
                    row.get("window_end"),
                    row.get("target_event_count", 0),
                    row.get("http_status"),
                    row.get("provider_request_status"),
                    row.get("response_schema_status", "UNKNOWN"),
                    row.get("events_returned", 0),
                    row.get("events_matched", 0),
                    row.get("raw_payload_hash"),
                    row.get("error_class"),
                    row.get("successful_search_scope"),
                ),
            )
            return cursor.fetchone() is not None

    def list_result_request_evidence(self, limit=500):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT request_evidence_id, request_id, provider, request_kind, requested_at, window_start, "
                "window_end, target_event_count, http_status, provider_request_status, response_schema_status, "
                "events_returned, events_matched, raw_payload_hash, error_class, successful_search_scope, created_at "
                "FROM quant_result_request_evidence ORDER BY request_evidence_id DESC LIMIT %s",
                (limit,),
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def insert_arb_verification(self, row):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_arb_opportunity_verification "
                "(opportunity_id, verified_at, still_valid, quote_age_seconds, cross_book_delta_seconds, classification) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    row["opportunity_id"],
                    row["verified_at"],
                    row.get("still_valid", False),
                    Jsonb(row.get("quote_age_seconds", {})),
                    row.get("cross_book_delta_seconds"),
                    row["classification"],
                ),
            )

    def list_arb_verifications(self, opportunity_id=None, limit=5000):
        with self._database.connect() as connection, connection.cursor() as cursor:
            if opportunity_id:
                cursor.execute(
                    "SELECT verification_id, opportunity_id, verified_at, still_valid, quote_age_seconds, "
                    "cross_book_delta_seconds, classification, created_at "
                    "FROM quant_arb_opportunity_verification WHERE opportunity_id = %s "
                    "ORDER BY verified_at DESC LIMIT %s",
                    (opportunity_id, limit),
                )
            else:
                cursor.execute(
                    "SELECT verification_id, opportunity_id, verified_at, still_valid, quote_age_seconds, "
                    "cross_book_delta_seconds, classification, created_at "
                    "FROM quant_arb_opportunity_verification ORDER BY verified_at DESC LIMIT %s",
                    (limit,),
                )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def insert_forward_score(self, spec):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_forward_scores "
                "(canonical_event_id, official_prediction_id, model_id, settlement_id, probability_a, actual_outcome, "
                "brier, logloss, logloss_eps_policy, effective_clipped_p, scoring_policy_version) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (canonical_event_id, model_id, settlement_id) DO NOTHING RETURNING score_id",
                (
                    spec["canonical_event_id"],
                    spec["official_prediction_id"],
                    spec["model_id"],
                    spec["settlement_id"],
                    spec["probability_a"],
                    spec["actual_outcome"],
                    spec["brier"],
                    spec["logloss"],
                    spec.get("logloss_eps_policy", "LOGLOSS_EPSILON_POLICY_V1"),
                    spec.get("effective_clipped_p"),
                    spec.get("scoring_policy_version", 1),
                ),
            )
            return cursor.fetchone() is not None

    def list_forward_scores(self, limit=2000):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT score_id, canonical_event_id, official_prediction_id, model_id, settlement_id, "
                "probability_a, actual_outcome, brier, logloss, logloss_eps_policy, effective_clipped_p, "
                "scoring_policy_version, created_at "
                "FROM quant_forward_scores ORDER BY score_id DESC LIMIT %s",
                (limit,),
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def upsert_result_acquisition(self, row):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_result_acquisition "
                "(canonical_event_id, provider, provider_event_id, commence_at, acquisition_state, result_status, "
                "actual_a, actual_b, winner_side, orientation, raw_provenance_hash, evidence_ref, request_count, "
                "last_requested_at, next_poll_at, last_error, settled) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (canonical_event_id) DO UPDATE SET "
                "provider = EXCLUDED.provider, provider_event_id = EXCLUDED.provider_event_id, "
                "acquisition_state = EXCLUDED.acquisition_state, result_status = EXCLUDED.result_status, "
                "actual_a = EXCLUDED.actual_a, actual_b = EXCLUDED.actual_b, winner_side = EXCLUDED.winner_side, "
                "orientation = EXCLUDED.orientation, raw_provenance_hash = EXCLUDED.raw_provenance_hash, "
                "evidence_ref = EXCLUDED.evidence_ref, request_count = EXCLUDED.request_count, "
                "last_requested_at = EXCLUDED.last_requested_at, next_poll_at = EXCLUDED.next_poll_at, "
                "last_error = EXCLUDED.last_error, settled = EXCLUDED.settled, updated_at = now() "
                "RETURNING acquisition_id",
                (
                    row["canonical_event_id"],
                    row.get("provider", "odds_api_io"),
                    row.get("provider_event_id"),
                    row.get("commence_at"),
                    row["acquisition_state"],
                    row.get("result_status"),
                    row.get("actual_a"),
                    row.get("actual_b"),
                    row.get("winner_side"),
                    row.get("orientation"),
                    row.get("raw_provenance_hash"),
                    row.get("evidence_ref"),
                    row.get("request_count", 0),
                    row.get("last_requested_at"),
                    row.get("next_poll_at"),
                    row.get("last_error"),
                    row.get("settled", False),
                ),
            )
            return cursor.fetchone() is not None

    def list_result_acquisition(self, limit=2000):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT acquisition_id, canonical_event_id, provider, provider_event_id, commence_at, "
                "acquisition_state, result_status, actual_a, actual_b, winner_side, orientation, "
                "raw_provenance_hash, evidence_ref, request_count, last_requested_at, next_poll_at, "
                "last_error, settled, created_at, updated_at "
                "FROM quant_result_acquisition ORDER BY acquisition_id DESC LIMIT %s",
                (limit,),
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def record_result_request(self, row):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_result_request_ledger "
                "(provider, request_kind, events_requested, events_returned, status_code, ok, error, cost_estimate) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    row.get("provider", "odds_api_io"),
                    row["request_kind"],
                    row.get("events_requested", 0),
                    row.get("events_returned", 0),
                    row.get("status_code"),
                    row.get("ok", False),
                    row.get("error"),
                    row.get("cost_estimate"),
                ),
            )

    def list_result_requests(self, limit=500):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT ledger_id, provider, request_kind, events_requested, events_returned, status_code, "
                "ok, error, cost_estimate, observed_at "
                "FROM quant_result_request_ledger ORDER BY ledger_id DESC LIMIT %s",
                (limit,),
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def upsert_market_reference(self, row):
        """Insert a market reference; frozen references are never overwritten.

        P18: once an official event reference is frozen for evaluation, a later
        (prettier) quote must not replace it. The unique key keeps one row per
        (event, policy, market, side); DO UPDATE only touches non-frozen rows.
        """
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_market_reference "
                "(canonical_event_id, policy_version, market, side, bookmaker, price, observation_id, referenced_at, frozen) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (canonical_event_id, policy_version, market, side) DO UPDATE SET "
                "bookmaker = EXCLUDED.bookmaker, price = EXCLUDED.price, "
                "observation_id = EXCLUDED.observation_id, referenced_at = EXCLUDED.referenced_at "
                "WHERE quant_market_reference.frozen = FALSE "
                "RETURNING reference_id",
                (
                    row["canonical_event_id"],
                    row["policy_version"],
                    row["market"],
                    row["side"],
                    row["bookmaker"],
                    row["price"],
                    row.get("observation_id"),
                    row.get("referenced_at"),
                    row.get("frozen", True),
                ),
            )
            return cursor.fetchone() is not None

    def freeze_market_reference(self, canonical_event_id):
        """Mark all references for an event as frozen (immutable)."""
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE quant_market_reference SET frozen = TRUE WHERE canonical_event_id = %s",
                (canonical_event_id,),
            )
            return True

    def list_market_reference(self, canonical_event_id=None, limit=2000):
        with self._database.connect() as connection, connection.cursor() as cursor:
            if canonical_event_id is not None:
                cursor.execute(
                    "SELECT reference_id, canonical_event_id, policy_version, market, side, bookmaker, price, "
                    "observation_id, referenced_at, frozen, created_at "
                    "FROM quant_market_reference WHERE canonical_event_id = %s ORDER BY reference_id DESC LIMIT %s",
                    (canonical_event_id, limit),
                )
            else:
                cursor.execute(
                    "SELECT reference_id, canonical_event_id, policy_version, market, side, bookmaker, price, "
                    "observation_id, referenced_at, frozen, created_at "
                    "FROM quant_market_reference ORDER BY reference_id DESC LIMIT %s",
                    (limit,),
                )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_circuit_breaker(self, provider, function_name):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT circuit_id, provider, function_name, state, consecutive_failures, opened_at, "
                "cooldown_until, last_error, policy_version, updated_at "
                "FROM quant_provider_circuit_breaker WHERE provider = %s AND function_name = %s",
                (provider, function_name),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [column.name for column in cursor.description]
            return dict(zip(columns, row))

    def upsert_circuit_breaker(self, row):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_provider_circuit_breaker "
                "(provider, function_name, state, consecutive_failures, opened_at, cooldown_until, last_error, policy_version) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (provider, function_name) DO UPDATE SET "
                "state = EXCLUDED.state, consecutive_failures = EXCLUDED.consecutive_failures, "
                "opened_at = EXCLUDED.opened_at, cooldown_until = EXCLUDED.cooldown_until, "
                "last_error = EXCLUDED.last_error, policy_version = EXCLUDED.policy_version, updated_at = now() "
                "RETURNING circuit_id",
                (
                    row["provider"],
                    row["function_name"],
                    row["state"],
                    row.get("consecutive_failures", 0),
                    row.get("opened_at"),
                    row.get("cooldown_until"),
                    row.get("last_error"),
                    row.get("policy_version", "PROVIDER_CIRCUIT_BREAKER_V1"),
                ),
            )
            return cursor.fetchone() is not None

    def try_claim_half_open_probe(self, provider, function_name, lease_seconds=10):
        """P22: atomically claim the HALF_OPEN probe lease.

        Exactly one concurrent caller may win; others are deferred. The lease is
        released on success (CLOSED) or failure (OPEN), and expires after
        ``lease_seconds`` so a crashed prober never wedges the circuit.
        """
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE quant_provider_circuit_breaker SET "
                "probe_lease_until = now() + make_interval(secs => %s) "
                "WHERE provider = %s AND function_name = %s AND state = 'HALF_OPEN' "
                "AND (probe_lease_until IS NULL OR probe_lease_until < now()) "
                "RETURNING circuit_id",
                (lease_seconds, provider, function_name),
            )
            return cursor.fetchone() is not None

    def quota_used(self, request_class, period_start):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT used, budget, reserved FROM quant_request_quota "
                "WHERE request_class = %s AND period_start = %s",
                (request_class, period_start),
            )
            row = cursor.fetchone()
            if row is None:
                return {"used": 0, "budget": 0, "reserved": 0}
            return {"used": int(row[0]), "budget": int(row[1]), "reserved": int(row[2])}

    def upsert_quota_budget(self, request_class, period_start, budget, reserved=0):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_request_quota (period_start, request_class, reserved, used, budget) "
                "VALUES (%s, %s, %s, 0, %s) "
                "ON CONFLICT (period_start, request_class) DO UPDATE SET budget = GREATEST(quant_request_quota.budget, EXCLUDED.budget), "
                "reserved = GREATEST(quant_request_quota.reserved, EXCLUDED.reserved), updated_at = now() "
                "RETURNING quota_id",
                (period_start, request_class, reserved, budget),
            )
            return cursor.fetchone() is not None

    def reserve_quota(self, request_class, period_start, budget):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_request_quota (period_start, request_class, reserved, used, budget) "
                "VALUES (%s, %s, %s, 0, %s) "
                "ON CONFLICT (period_start, request_class) DO UPDATE SET budget = GREATEST(quant_request_quota.budget, EXCLUDED.budget), "
                "reserved = GREATEST(quant_request_quota.reserved, EXCLUDED.reserved), updated_at = now() "
                "RETURNING quota_id",
                (period_start, request_class, budget, budget),
            )
            return cursor.fetchone() is not None

    def consume_quota(self, request_class, period_start, amount=1):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE quant_request_quota SET used = used + %s, updated_at = now() "
                "WHERE request_class = %s AND period_start = %s RETURNING quota_id",
                (amount, request_class, period_start),
            )
            return cursor.fetchone() is not None

    def consume_quota_atomic(self, request_class, period_start, amount=1):
        """P20: atomic quota consumption (used + amount must stay within budget)."""
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE quant_request_quota SET used = used + %s, updated_at = now() "
                "WHERE request_class = %s AND period_start = %s AND used + %s <= budget "
                "RETURNING quota_id",
                (amount, request_class, period_start, amount),
            )
            return cursor.fetchone() is not None

    def insert_arb_opportunity(self, opp):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_arb_opportunities "
                "(opportunity_id, fingerprint, canonical_event_id, canonical_market_key, detected_at, "
                "first_seen_at, last_verified_at, expires_at, expired_at, bookmakers, quote_ids, odds, "
                "inverse_sum, raw_margin, stake_plan, worst_case_profit, worst_case_roi, freshness_state, "
                "cross_book_time_delta, settlement_compatibility, classification, risk_flags, policy_version, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (fingerprint) DO NOTHING RETURNING opportunity_id",
                (
                    opp["opportunity_id"],
                    opp["fingerprint"],
                    opp["canonical_event_id"],
                    opp["canonical_market_key"],
                    opp["detected_at"],
                    opp["first_seen_at"],
                    opp.get("last_verified_at"),
                    opp.get("expires_at"),
                    opp.get("expired_at"),
                    Jsonb(opp.get("bookmakers", [])),
                    Jsonb(opp.get("quote_ids", [])),
                    Jsonb(opp.get("odds", [])),
                    opp["inverse_sum"],
                    opp["raw_margin"],
                    Jsonb(opp.get("stake_plan", [])),
                    opp.get("worst_case_profit"),
                    opp.get("worst_case_roi"),
                    opp.get("freshness_state"),
                    opp.get("cross_book_time_delta"),
                    opp.get("settlement_compatibility"),
                    opp["classification"],
                    Jsonb(opp.get("risk_flags", [])),
                    opp["policy_version"],
                    opp.get("status", "ACTIVE"),
                ),
            )
            return cursor.fetchone() is not None

    def list_arb_opportunities(self, limit=500, status=None):
        with self._database.connect() as connection, connection.cursor() as cursor:
            if status:
                cursor.execute(
                    "SELECT opportunity_id, fingerprint, canonical_event_id, canonical_market_key, detected_at, "
                    "first_seen_at, last_verified_at, expires_at, expired_at, bookmakers, quote_ids, odds, "
                    "inverse_sum, raw_margin, stake_plan, worst_case_profit, worst_case_roi, freshness_state, "
                    "cross_book_time_delta, settlement_compatibility, classification, risk_flags, policy_version, "
                    "status, created_at FROM quant_arb_opportunities WHERE status = %s "
                    "ORDER BY detected_at DESC LIMIT %s",
                    (status, limit),
                )
            else:
                cursor.execute(
                    "SELECT opportunity_id, fingerprint, canonical_event_id, canonical_market_key, detected_at, "
                    "first_seen_at, last_verified_at, expires_at, expired_at, bookmakers, quote_ids, odds, "
                    "inverse_sum, raw_margin, stake_plan, worst_case_profit, worst_case_roi, freshness_state, "
                    "cross_book_time_delta, settlement_compatibility, classification, risk_flags, policy_version, "
                    "status, created_at FROM quant_arb_opportunities ORDER BY detected_at DESC LIMIT %s",
                    (limit,),
                )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def expire_arb_opportunity(self, opportunity_id, *, expired_at, status="EXPIRED"):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE quant_arb_opportunities SET status = %s, expired_at = %s "
                "WHERE opportunity_id = %s RETURNING opportunity_id",
                (status, expired_at, opportunity_id),
            )
            return cursor.fetchone() is not None

    def insert_paper_arb_ticket(self, ticket):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_paper_arb_tickets "
                "(opportunity_id, canonical_event_id, canonical_market_key, strategy, decision_time, legs, "
                "bookmakers, odds, stakes, expected_return, worst_case_profit, quote_age_seconds, constraints, "
                "reason, settlement_id, settlement_revision, capital_allocated, realized_payout, realized_pnl, "
                "roi, void_state) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (opportunity_id) DO NOTHING RETURNING arb_ticket_id",
                (
                    ticket["opportunity_id"],
                    ticket["canonical_event_id"],
                    ticket["canonical_market_key"],
                    ticket.get("strategy", "PAPER_ARB"),
                    ticket["decision_time"],
                    Jsonb(ticket.get("legs", [])),
                    Jsonb(ticket.get("bookmakers", [])),
                    Jsonb(ticket.get("odds", [])),
                    Jsonb(ticket.get("stakes", [])),
                    ticket.get("expected_return"),
                    ticket.get("worst_case_profit"),
                    Jsonb(ticket.get("quote_age_seconds", {})),
                    Jsonb(ticket.get("constraints", {})),
                    ticket.get("reason"),
                    ticket.get("settlement_id"),
                    ticket.get("settlement_revision"),
                    ticket.get("capital_allocated"),
                    ticket.get("realized_payout"),
                    ticket.get("realized_pnl"),
                    ticket.get("roi"),
                    ticket.get("void_state"),
                ),
            )
            return cursor.fetchone() is not None

    def list_paper_arb_tickets(self, limit=500):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT arb_ticket_id, opportunity_id, canonical_event_id, canonical_market_key, strategy, "
                "decision_time, legs, bookmakers, odds, stakes, expected_return, worst_case_profit, "
                "quote_age_seconds, constraints, reason, settlement_id, settlement_revision, capital_allocated, "
                "realized_payout, realized_pnl, roi, void_state, created_at "
                "FROM quant_paper_arb_tickets ORDER BY arb_ticket_id DESC LIMIT %s",
                (limit,),
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def settle_paper_arb_ticket(self, opportunity_id, *, settlement_id, realized_payout, realized_pnl, roi, void_state=None, settlement_revision=1):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE quant_paper_arb_tickets SET settlement_id = %s, settlement_revision = %s, "
                "realized_payout = %s, realized_pnl = %s, roi = %s, void_state = %s "
                "WHERE opportunity_id = %s RETURNING arb_ticket_id",
                (settlement_id, settlement_revision, realized_payout, realized_pnl, roi, void_state, opportunity_id),
            )
            return cursor.fetchone() is not None

    def upsert_book_access_profile(self, row):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO quant_book_access_profile "
                "(bookmaker, owner_can_legally_access, account_available, currency, known_balance, "
                "known_stake_limits, settlement_rule_state) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (bookmaker) DO UPDATE SET "
                "owner_can_legally_access = EXCLUDED.owner_can_legally_access, "
                "account_available = EXCLUDED.account_available, currency = EXCLUDED.currency, "
                "known_balance = EXCLUDED.known_balance, known_stake_limits = EXCLUDED.known_stake_limits, "
                "settlement_rule_state = EXCLUDED.settlement_rule_state, updated_at = now() RETURNING bookmaker",
                (
                    row["bookmaker"],
                    row.get("owner_can_legally_access", "UNKNOWN"),
                    row.get("account_available", "UNKNOWN"),
                    row.get("currency"),
                    row.get("known_balance"),
                    Jsonb(row.get("known_stake_limits", {})),
                    row.get("settlement_rule_state", "UNKNOWN"),
                ),
            )
            return cursor.fetchone() is not None

    def list_book_access_profiles(self, limit=200):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT bookmaker, owner_can_legally_access, account_available, currency, known_balance, "
                "known_stake_limits, settlement_rule_state, updated_at "
                "FROM quant_book_access_profile ORDER BY bookmaker LIMIT %s",
                (limit,),
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]


@dataclass
class InMemoryQuantStore(QuantStore):
    research: list[dict[str, Any]] = field(default_factory=list)
    models: list[dict[str, Any]] = field(default_factory=list)
    threads: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    budget: dict[tuple[str, str, str], dict[str, Any]] = field(default_factory=dict)
    snapshots: list[dict[str, Any]] = field(default_factory=list)
    experiments: list[dict[str, Any]] = field(default_factory=list)
    reviews: list[dict[str, Any]] = field(default_factory=list)
    jobs: dict[str, dict[str, Any]] = field(default_factory=dict)
    triggers: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    evaluations: dict[tuple[str, str, str, str, str, str], dict[str, Any]] = field(default_factory=dict)
    corrections: list[dict[str, Any]] = field(default_factory=list)
    prediction_errors: list[dict[str, Any]] = field(default_factory=list)
    metric_snapshots: list[dict[str, Any]] = field(default_factory=list)
    ai_calls: list[dict[str, Any]] = field(default_factory=list)
    hypotheses: list[dict[str, Any]] = field(default_factory=list)
    stage_audit: list[dict[str, Any]] = field(default_factory=list)
    shadow_predictions: dict[tuple[str, str, str], dict[str, Any]] = field(default_factory=dict)
    paper_entries: list[dict[str, Any]] = field(default_factory=list)
    weaknesses: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    weakness_evidence: list[dict[str, Any]] = field(default_factory=list)
    improvement_actions: list[dict[str, Any]] = field(default_factory=list)
    knowledge_findings: list[dict[str, Any]] = field(default_factory=list)
    repair_packets: list[dict[str, Any]] = field(default_factory=list)
    decision_evaluations: list[dict[str, Any]] = field(default_factory=list)
    paper_tickets: dict[tuple[str, str, str, str], dict[str, Any]] = field(default_factory=dict)
    bookmaker_coverage: list[dict[str, Any]] = field(default_factory=list)
    official_predictions: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    settlements: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    forward_scores: dict[tuple[str, str, int], dict[str, Any]] = field(default_factory=dict)
    result_acquisition: dict[str, dict[str, Any]] = field(default_factory=dict)
    result_request_ledger: list[dict[str, Any]] = field(default_factory=list)
    market_reference: dict[tuple[str, str, str, str], dict[str, Any]] = field(default_factory=dict)
    circuit_breakers: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    request_quota: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    arb_opportunities: dict[str, dict[str, Any]] = field(default_factory=dict)
    paper_arb_tickets: dict[str, dict[str, Any]] = field(default_factory=dict)
    book_access_profiles: dict[str, dict[str, Any]] = field(default_factory=dict)
    result_request_evidence: dict[str, dict[str, Any]] = field(default_factory=dict)
    arb_verifications: list[dict[str, Any]] = field(default_factory=list)
    _next_result_request: int = 1
    _next_research: int = 1
    _next_thread: int = 1
    _next_message: int = 1
    _next_evaluation: int = 1
    _next_hypothesis: int = 1
    _next_weakness: int = 1
    _next_action: int = 1
    _next_finding: int = 1
    _next_packet: int = 1
    _next_official: int = 1
    _next_settlement: int = 1

    def create_research_entry(self, *, hypothesis, rationale=None, data_needed=None):
        entry_id = self._next_research
        self._next_research += 1
        now = _utcnow()
        self.research.append({
            "entry_id": entry_id,
            "hypothesis": hypothesis,
            "rationale": rationale,
            "status": "PROPOSED",
            "data_needed": data_needed,
            "result_summary": None,
            "evidence": {},
            "decision": None,
            "model_version": None,
            "created_at": now,
            "updated_at": now,
        })
        return entry_id

    def list_research_entries(self):
        return list(reversed(self.research))

    def transition_research_entry(self, entry_id, *, status, result_summary=None, evidence=None):
        for entry in self.research:
            if entry["entry_id"] == entry_id:
                entry["status"] = status
                if result_summary is not None:
                    entry["result_summary"] = result_summary
                if evidence is not None:
                    entry["evidence"] = evidence
                entry["updated_at"] = _utcnow()
                return True
        return False

    def register_model(self, *, model_id, model_version, role, stage, artifact_path=None, artifact_sha256=None, fit_n=None, cutoff=None, feature_schema_version=None):
        for entry in self.models:
            if entry["model_id"] == model_id and entry["model_version"] == model_version:
                entry["role"] = role
                entry["stage"] = stage
                return False
        self.models.append({
            "model_id": model_id,
            "model_version": model_version,
            "role": role,
            "stage": stage,
            "artifact_path": artifact_path,
            "artifact_sha256": artifact_sha256,
            "fit_n": fit_n,
            "cutoff": cutoff,
            "feature_schema_version": feature_schema_version,
            "created_at": _utcnow(),
            "updated_at": _utcnow(),
        })
        return True

    def list_models(self):
        return list(self.models)

    def champion(self):
        champions = [entry for entry in self.models if entry["role"] == "CHAMPION"]
        if not champions:
            return None
        return max(champions, key=lambda entry: entry["updated_at"])

    def create_thread(self, *, admin_account_id, title=""):
        thread_id = self._next_thread
        self._next_thread += 1
        self.threads[thread_id] = []
        return thread_id

    def append_message(self, *, thread_id, role, content, provenance=None):
        message_id = self._next_message
        self._next_message += 1
        self.threads.setdefault(thread_id, []).append({
            "message_id": message_id,
            "thread_id": thread_id,
            "role": role,
            "content": content,
            "provenance": provenance or {},
            "created_at": _utcnow(),
        })
        return message_id

    def thread_messages(self, thread_id):
        return list(self.threads.get(thread_id, []))

    def budget_row(self, *, day, provider, model):
        return self.budget.get((day, provider, model))

    def record_ai_call(self, *, provider, model, cost):
        key = (_today_utc(), provider, model)
        existing = self.budget.get(key)
        if existing is None:
            self.budget[key] = {
                "day": _today_utc(),
                "provider": provider,
                "model": model,
                "call_count": 1,
                "cost_usd": cost,
                "updated_at": _utcnow(),
            }
        else:
            existing["call_count"] += 1
            existing["cost_usd"] += cost

    def create_snapshot(self, snapshot):
        document = snapshot.to_dict()
        if any(snapshot["snapshot_id"] == document["snapshot_id"] for snapshot in self.snapshots):
            return False
        self.snapshots.append(document)
        return True

    def list_snapshots(self):
        return list(reversed(self.snapshots))

    def save_experiment(self, *, spec, result):
        document = {
            "experiment_id": spec.experiment_id,
            "hypothesis_id": spec.hypothesis_id,
            "dataset_snapshot_id": spec.dataset_snapshot_id,
            "champion_version": spec.champion_version,
            "challenger_name": spec.challenger_name,
            "feature_set": list(spec.feature_set),
            "algorithm": spec.algorithm,
            "created_at": result.created_at,
            "decision": result.decision,
            "result": result.to_dict(),
        }
        for existing in self.experiments:
            if existing["experiment_id"] == spec.experiment_id:
                existing.update(document)
                return False
        self.experiments.append(document)
        return True

    def list_experiments(self):
        return list(reversed(self.experiments))

    def save_review(self, outcome):
        self.reviews.append(outcome.to_dict())
        return True

    def list_reviews(self):
        return list(reversed(self.reviews))

    def list_champions(self):
        return [
            dict(entry) for entry in self.models
            if entry.get("role") == "CHAMPION"
        ]

    def register_champion(self, *, model_id, model_version, artifact_path, artifact_sha256, fit_n, cutoff, feature_schema_version, promotion_provenance=None, dataset_provenance=None):
        for entry in self.models:
            if entry["model_id"] == model_id and entry["model_version"] == model_version:
                entry["role"] = "CHAMPION"
                entry["stage"] = "CHAMPION"
                return model_id
        self.models.append({
            "model_id": model_id,
            "model_version": model_version,
            "role": "CHAMPION",
            "stage": "CHAMPION",
            "artifact_path": artifact_path,
            "artifact_sha256": artifact_sha256,
            "fit_n": fit_n,
            "cutoff": cutoff,
            "feature_schema_version": feature_schema_version,
            "created_at": _utcnow(),
            "updated_at": _utcnow(),
        })
        return model_id

    def upsert_job(self, job):
        existing = self.job(job["job_name"])
        if existing is None:
            self.jobs[job["job_name"]] = {
                "job_name": job["job_name"],
                "enabled": bool(job.get("enabled", True)),
                "schedule_interval_seconds": int(job["schedule_interval_seconds"]),
                "next_run_at": job["next_run_at"],
                "status": "IDLE",
                "last_result_summary": job.get("last_result_summary"),
                "last_state_hash": job.get("last_state_hash"),
                "last_error": None,
                "lease_owner": None,
                "lease_expires_at": None,
                "attempt_count": 0,
            }
        else:
            existing["enabled"] = bool(job.get("enabled", True))
            existing["schedule_interval_seconds"] = int(job["schedule_interval_seconds"])

    def claim_job(self, job_name, owner, lease_seconds, now=None):
        job = self.job(job_name)
        if job is None or not job["enabled"]:
            return None
        now = now or _utcnow()
        if isinstance(now, str):
            now = datetime.fromisoformat(now.replace("Z", "+00:00"))
        next_run = datetime.fromisoformat(job["next_run_at"].replace("Z", "+00:00"))
        if next_run > now:
            return None
        if job["status"] == "RUNNING" and job["lease_expires_at"] is not None:
            expiry = datetime.fromisoformat(job["lease_expires_at"].replace("Z", "+00:00"))
            if expiry > now:
                return None
        from datetime import timedelta

        job["lease_owner"] = owner
        job["lease_expires_at"] = (now + timedelta(seconds=lease_seconds)).isoformat()
        job["status"] = "RUNNING"
        job["attempt_count"] += 1
        job["last_started_at"] = now.isoformat()
        return {key: job[key] for key in ("job_name", "enabled", "schedule_interval_seconds", "next_run_at", "status", "attempt_count")}

    def complete_job(self, job_name, *, summary, state_hash, next_run_at):
        job = self.job(job_name)
        if job is None:
            return
        job.update({
            "status": "COMPLETED",
            "last_completed_at": _utcnow().isoformat(),
            "last_result_summary": summary,
            "last_state_hash": state_hash,
            "next_run_at": next_run_at,
            "lease_owner": None,
            "lease_expires_at": None,
        })

    def fail_job(self, job_name, *, error):
        job = self.job(job_name)
        if job is None:
            return
        job.update({
            "status": "FAILED",
            "last_error": error,
            "lease_owner": None,
            "lease_expires_at": None,
        })

    def job(self, job_name):
        return self.jobs.get(job_name)

    def record_trigger(self, trigger):
        key = (trigger["trigger_type"], trigger["state_hash"])
        existing = self.triggers.get(key)
        if existing is None:
            self.triggers[key] = {
                "trigger_type": trigger["trigger_type"],
                "severity": trigger["severity"],
                "trigger_evidence": trigger.get("trigger_evidence", {}),
                "state_hash": trigger["state_hash"],
                "first_seen_at": trigger["first_seen_at"],
                "last_seen_at": trigger["last_seen_at"],
                "last_invoked_at": trigger.get("last_invoked_at"),
                "invocation_result": trigger.get("invocation_result"),
                "suppressed_count": 0,
            }
            return True
        existing["last_seen_at"] = trigger["last_seen_at"]
        existing["suppressed_count"] += 1
        return False

    def list_triggers(self, limit=100):
        rows = sorted(self.triggers.values(), key=lambda item: item["last_seen_at"], reverse=True)
        return rows[:limit]

    def insert_evaluation(self, evaluation):
        key = (
            evaluation["prediction_id"], evaluation["event_id"], evaluation["model_id"],
            evaluation["model_version"], evaluation["prediction_ts"], evaluation["outcome_version"],
        )
        if key in self.evaluations:
            return False
        evaluation_id = self._next_evaluation
        self._next_evaluation += 1
        self.evaluations[key] = dict(evaluation, evaluation_id=evaluation_id, status="ACTIVE")
        return True

    def supersede_evaluation(self, evaluation_id):
        for evaluation in self.evaluations.values():
            if evaluation["evaluation_id"] == evaluation_id:
                evaluation["status"] = "SUPERSEDED"

    def record_correction(self, correction):
        self.corrections.append(dict(correction))

    def evaluation_counts(self):
        active = sum(1 for evaluation in self.evaluations.values() if evaluation["status"] == "ACTIVE")
        superseded = sum(1 for evaluation in self.evaluations.values() if evaluation["status"] == "SUPERSEDED")
        return {"active": active, "superseded": superseded}

    def list_evaluations(self, limit=1000):
        rows = sorted(self.evaluations.values(), key=lambda item: item["evaluation_id"], reverse=True)
        return rows[:limit]

    def insert_prediction_error(self, error):
        if any(existing["evaluation_id"] == error["evaluation_id"] for existing in self.prediction_errors):
            return False
        self.prediction_errors.append(dict(error))
        return True

    def list_prediction_errors(self, limit=1000):
        return list(reversed(self.prediction_errors))[:limit]

    def insert_metric_snapshot(self, snapshot):
        self.metric_snapshots.append(dict(snapshot))

    def latest_metric_snapshot(self):
        return self.metric_snapshots[-1] if self.metric_snapshots else None

    def record_ai_call_full(self, call):
        self.ai_calls.append(dict(call, created_at=_utcnow().isoformat()))

    def list_ai_calls(self, limit=200):
        return list(reversed(self.ai_calls))[:limit]

    def daily_ai_usage(self, day):
        calls = [call for call in self.ai_calls if str(call.get("created_at", ""))[:10] == day]
        return {"calls": len(calls), "cost_usd": round(sum(float(call.get("estimated_cost_usd", 0.0)) for call in calls), 8)}

    def upsert_hypothesis(self, hypothesis):
        for entry in self.hypotheses:
            if entry["title"] == hypothesis["title"] and entry["source"] == hypothesis["source"]:
                entry["status"] = hypothesis.get("status", entry["status"])
                if hypothesis.get("rejection_reason"):
                    entry["rejection_reason"] = hypothesis["rejection_reason"]
                return entry["hypothesis_id"]
        hypothesis_id = self._next_hypothesis
        self._next_hypothesis += 1
        self.hypotheses.append(dict(hypothesis, hypothesis_id=hypothesis_id))
        return hypothesis_id

    def list_hypotheses(self):
        return sorted(self.hypotheses, key=lambda item: (item.get("priority_score") is None, -(item.get("priority_score") or 0)))

    def update_hypothesis_priority(self, hypothesis_id, *, priority_score, breakdown, blocked_reason):
        for entry in self.hypotheses:
            if entry["hypothesis_id"] == hypothesis_id:
                entry["priority_score"] = priority_score
                entry["priority_breakdown"] = breakdown
                entry["blocked_reason"] = blocked_reason

    def record_stage_transition(self, audit):
        self.stage_audit.append(dict(audit, created_at=_utcnow().isoformat()))

    def list_stage_transitions(self, model_id=None, limit=200):
        rows = list(reversed(self.stage_audit))
        if model_id is not None:
            rows = [row for row in rows if row.get("model_id") == model_id]
        return rows[:limit]

    def upsert_shadow_prediction(self, spec):
        key = (spec["canonical_event_id"], spec["model_id"], spec["model_version"])
        if key in self.shadow_predictions:
            return False
        self.shadow_predictions[key] = dict(spec, created_at=_utcnow().isoformat())
        return True

    def shadow_prediction_count(self, model_id=None):
        if model_id is None:
            return len(self.shadow_predictions)
        return sum(1 for spec in self.shadow_predictions.values() if spec.get("model_id") == model_id)

    def list_shadow_predictions(self, limit=500):
        rows = sorted(self.shadow_predictions.values(), key=lambda item: item["generated_at"], reverse=True)
        return rows[:limit]

    def upsert_paper_entry(self, entry):
        for existing in self.paper_entries:
            if existing["canonical_event_id"] == entry["canonical_event_id"]:
                return False
        self.paper_entries.append(dict(entry, created_at=_utcnow().isoformat()))
        return True

    def list_paper_entries(self, limit=500):
        return list(reversed(self.paper_entries))[:limit]

    def upsert_weakness(self, spec):
        key = (spec["weakness_type"], spec["state_hash"])
        existing = self.weaknesses.get(key)
        if existing is None:
            weakness_id = self._next_weakness
            self._next_weakness += 1
            self.weaknesses[key] = dict(spec, weakness_id=weakness_id, evidence_count=1, created_at=_utcnow().isoformat(), updated_at=_utcnow().isoformat())
            return weakness_id
        existing["last_observed_at"] = spec["last_observed_at"]
        existing["evidence_count"] = existing.get("evidence_count", 0) + 1
        existing["sample_size"] = spec.get("sample_size", existing.get("sample_size", 0))
        existing["severity"] = spec.get("severity", existing.get("severity", "LOW"))
        existing["updated_at"] = _utcnow().isoformat()
        return existing["weakness_id"]

    def list_weaknesses(self, limit=500):
        rows = sorted(self.weaknesses.values(), key=lambda item: (item.get("priority_score") is None, -(item.get("priority_score") or 0)))
        return rows[:limit]

    def add_weakness_evidence(self, evidence):
        self.weakness_evidence.append(dict(evidence, created_at=_utcnow().isoformat()))
        return len(self.weakness_evidence)

    def update_weakness_status(self, weakness_id, *, status):
        for entry in self.weaknesses.values():
            if entry["weakness_id"] == weakness_id:
                entry["status"] = status
                entry["updated_at"] = _utcnow().isoformat()

    def weakness_counts(self):
        by_status = {}
        for entry in self.weaknesses.values():
            by_status[entry["status"]] = by_status.get(entry["status"], 0) + 1
        return {"total": len(self.weaknesses), "by_status": by_status}

    def create_improvement_action(self, action):
        action_id = self._next_action
        self._next_action += 1
        self.improvement_actions.append(dict(action, action_id=action_id, created_at=_utcnow().isoformat()))
        return action_id

    def list_improvement_actions(self, limit=300):
        return list(reversed(self.improvement_actions))[:limit]

    def update_action_outcome(self, action_id, *, status, result_value, outcome):
        for action in self.improvement_actions:
            if action["action_id"] == action_id:
                action.update({"status": status, "result_value": result_value, "outcome": outcome, "completed_at": _utcnow().isoformat()})

    def add_knowledge_finding(self, finding):
        finding_id = self._next_finding
        self._next_finding += 1
        self.knowledge_findings.append(dict(finding, finding_id=finding_id, created_at=_utcnow().isoformat()))
        return finding_id

    def list_knowledge_findings(self, limit=300):
        return list(reversed(self.knowledge_findings))[:limit]

    def create_repair_packet(self, packet):
        packet_id = self._next_packet
        self._next_packet += 1
        self.repair_packets.append(dict(packet, packet_id=packet_id, created_at=_utcnow().isoformat()))
        return packet_id

    def list_repair_packets(self, limit=200):
        return list(reversed(self.repair_packets))[:limit]

    def insert_decision_evaluation(self, evaluation):
        self.decision_evaluations.append(dict(evaluation, created_at=_utcnow().isoformat()))
        return True

    def list_decision_evaluations(self, limit=1000):
        return list(reversed(self.decision_evaluations))[:limit]

    def decision_evaluation_counts(self):
        by_decision = {}
        for entry in self.decision_evaluations:
            by_decision[entry["decision"]] = by_decision.get(entry["decision"], 0) + 1
        return {"total": len(self.decision_evaluations), "by_decision": by_decision}

    def commit_paper_ticket(self, ticket):
        key = (ticket["canonical_event_id"], ticket["strategy"], ticket["model_id"], ticket["decision_ts"])
        if key in self.paper_tickets:
            return False
        self.paper_tickets[key] = dict(ticket, created_at=_utcnow().isoformat())
        return True

    def list_paper_tickets(self, limit=500):
        return list(reversed(list(self.paper_tickets.values())))[:limit]

    def upsert_bookmaker_coverage(self, entry):
        self.bookmaker_coverage.append(dict(entry, created_at=_utcnow().isoformat()))

    def list_bookmaker_coverage(self, limit=200):
        latest: dict[str, dict[str, Any]] = {}
        for row in reversed(self.bookmaker_coverage):
            bookmaker_id = str(row["bookmaker_id"])
            if bookmaker_id not in latest:
                latest[bookmaker_id] = row
        return list(latest.values())[:limit]

    def upsert_official_prediction(self, spec):
        key = (spec["canonical_event_id"], spec["model_id"])
        if key in self.official_predictions:
            return False
        official_id = self._next_official
        self._next_official += 1
        self.official_predictions[key] = dict(spec, official_prediction_id=official_id, created_at=_utcnow().isoformat())
        return True

    def list_official_predictions(self, limit=2000):
        return list(reversed(list(self.official_predictions.values())))[:limit]

    def official_prediction_counts(self):
        by_role = {}
        for entry in self.official_predictions.values():
            role = entry.get("prediction_role")
            by_role[role] = by_role.get(role, 0) + 1
        return {"total_rows": len(self.official_predictions), "unique_events_by_role": by_role}

    def insert_settlement(self, spec):
        key = (spec["canonical_event_id"], spec["source_result_id"])
        if key in self.settlements:
            return False
        settlement_id = self._next_settlement
        self._next_settlement += 1
        self.settlements[key] = dict(spec, settlement_id=settlement_id, revision=spec.get("revision", 1), created_at=_utcnow().isoformat())
        return True

    def list_settlements(self, limit=2000):
        return list(reversed(list(self.settlements.values())))[:limit]

    def latest_final_settlement(self, canonical_event_id):
        finals = [s for s in self.settlements.values() if s.get("canonical_event_id") == canonical_event_id and s.get("status") == "FINAL"]
        if not finals:
            return None
        return max(finals, key=lambda s: s.get("revision", 0))

    def insert_settlement_revision(self, spec):
        prior = self.latest_final_settlement(spec["canonical_event_id"])
        prior_id = prior["settlement_id"] if prior else None
        prior_revision = prior.get("revision", 0) if prior else 0
        if prior_id is not None:
            prior["status"] = "SUPERSEDED"
            prior["supersedes_revision_id"] = None
        new_revision = prior_revision + 1
        settlement_id = self._next_settlement
        self._next_settlement += 1
        key = (spec["canonical_event_id"], f"{spec['source_result_id']}#rev{new_revision}")
        self.settlements[key] = dict(spec, settlement_id=settlement_id, revision=new_revision, supersedes_revision_id=prior_id, created_at=_utcnow().isoformat())
        return settlement_id

    def record_result_request_evidence(self, row):
        key = row["request_id"]
        self.result_request_evidence[key] = dict(row, created_at=_utcnow().isoformat())
        return True

    def list_result_request_evidence(self, limit=500):
        return list(reversed(list(self.result_request_evidence.values())))[:limit]

    def insert_arb_verification(self, row):
        self.arb_verifications.append(dict(row, created_at=_utcnow().isoformat()))

    def list_arb_verifications(self, opportunity_id=None, limit=5000):
        entries = list(self.arb_verifications)
        if opportunity_id:
            entries = [e for e in entries if e.get("opportunity_id") == opportunity_id]
        entries.sort(key=lambda e: e.get("verified_at", ""), reverse=True)
        return entries[:limit]

    def insert_forward_score(self, spec):
        key = (spec["canonical_event_id"], spec["model_id"], spec["settlement_id"])
        if key in self.forward_scores:
            return False
        self.forward_scores[key] = dict(spec, created_at=_utcnow().isoformat())
        return True

    def list_forward_scores(self, limit=2000):
        return list(reversed(list(self.forward_scores.values())))[:limit]

    def upsert_result_acquisition(self, row):
        key = row["canonical_event_id"]
        existing = self.result_acquisition.get(key, {})
        merged = dict(existing)
        merged.update(row)
        merged["updated_at"] = _utcnow().isoformat()
        self.result_acquisition[key] = merged
        return True

    def list_result_acquisition(self, limit=2000):
        return list(reversed(list(self.result_acquisition.values())))[:limit]

    def record_result_request(self, row):
        entry = dict(row, ledger_id=self._next_result_request, observed_at=_utcnow().isoformat())
        self._next_result_request += 1
        self.result_request_ledger.append(entry)
        return entry["ledger_id"]

    def list_result_requests(self, limit=500):
        return list(reversed(self.result_request_ledger))[:limit]

    def upsert_market_reference(self, row):
        key = (row["canonical_event_id"], row["policy_version"], row["market"], row["side"])
        existing = self.market_reference.get(key)
        if existing is not None and existing.get("frozen", True):
            return False
        self.market_reference[key] = dict(row, created_at=_utcnow().isoformat())
        return True

    def freeze_market_reference(self, canonical_event_id):
        for entry in self.market_reference.values():
            if entry.get("canonical_event_id") == canonical_event_id:
                entry["frozen"] = True
        return True

    def list_market_reference(self, canonical_event_id=None, limit=2000):
        entries = list(self.market_reference.values())
        if canonical_event_id is not None:
            entries = [e for e in entries if e["canonical_event_id"] == canonical_event_id]
        return list(reversed(entries))[:limit]

    def get_circuit_breaker(self, provider, function_name):
        return self.circuit_breakers.get((provider, function_name))

    def upsert_circuit_breaker(self, row):
        key = (row["provider"], row["function_name"])
        existing = self.circuit_breakers.get(key, {})
        merged = dict(existing)
        merged.update(row)
        merged["updated_at"] = _utcnow().isoformat()
        self.circuit_breakers[key] = merged
        return True

    def try_claim_half_open_probe(self, provider, function_name, lease_seconds=10):
        row = self.circuit_breakers.get((provider, function_name))
        if row is None or row.get("state") != "HALF_OPEN":
            return False
        if row.get("probe_lease_until") is not None:
            return False
        row["probe_lease_until"] = _utcnow().isoformat()
        return True

    def quota_used(self, request_class, period_start):
        row = self.request_quota.get((request_class, period_start))
        if row is None:
            return {"used": 0, "budget": 0, "reserved": 0}
        return {"used": row["used"], "budget": row["budget"], "reserved": row["reserved"]}

    def upsert_quota_budget(self, request_class, period_start, budget, reserved=0):
        key = (request_class, period_start)
        existing = self.request_quota.get(key, {"used": 0, "reserved": 0, "budget": 0})
        self.request_quota[key] = {
            "period_start": period_start,
            "request_class": request_class,
            "used": existing["used"],
            "reserved": max(int(existing["reserved"]), int(reserved)),
            "budget": max(int(existing["budget"]), int(budget)),
        }
        return True

    def reserve_quota(self, request_class, period_start, budget):
        key = (request_class, period_start)
        existing = self.request_quota.get(key, {"used": 0, "reserved": 0, "budget": 0})
        self.request_quota[key] = {
            "period_start": period_start,
            "request_class": request_class,
            "used": existing["used"],
            "reserved": max(int(existing["reserved"]), int(budget)),
            "budget": max(int(existing["budget"]), int(budget)),
        }
        return True

    def consume_quota(self, request_class, period_start, amount=1):
        key = (request_class, period_start)
        if key not in self.request_quota:
            return False
        self.request_quota[key]["used"] += amount
        return True

    def consume_quota_atomic(self, request_class, period_start, amount=1):
        key = (request_class, period_start)
        if key not in self.request_quota:
            return False
        row = self.request_quota[key]
        if row["used"] + amount > row["budget"]:
            return False
        row["used"] += amount
        return True

    def insert_arb_opportunity(self, opp):
        if opp["fingerprint"] in self.arb_opportunities:
            return False
        self.arb_opportunities[opp["fingerprint"]] = dict(opp, created_at=_utcnow().isoformat())
        return True

    def list_arb_opportunities(self, limit=500, status=None):
        entries = list(self.arb_opportunities.values())
        if status:
            entries = [e for e in entries if e.get("status") == status]
        entries.sort(key=lambda e: e.get("detected_at", ""), reverse=True)
        return entries[:limit]

    def expire_arb_opportunity(self, opportunity_id, *, expired_at, status="EXPIRED"):
        for entry in self.arb_opportunities.values():
            if entry.get("opportunity_id") == opportunity_id:
                entry["status"] = status
                entry["expired_at"] = expired_at
                return True
        return False

    def insert_paper_arb_ticket(self, ticket):
        if ticket["opportunity_id"] in self.paper_arb_tickets:
            return False
        self.paper_arb_tickets[ticket["opportunity_id"]] = dict(ticket, created_at=_utcnow().isoformat())
        return True

    def list_paper_arb_tickets(self, limit=500):
        return list(reversed(list(self.paper_arb_tickets.values())))[:limit]

    def settle_paper_arb_ticket(self, opportunity_id, *, settlement_id, realized_payout, realized_pnl, roi, void_state=None, settlement_revision=1):
        ticket = self.paper_arb_tickets.get(opportunity_id)
        if ticket is None:
            return False
        ticket["settlement_id"] = settlement_id
        ticket["settlement_revision"] = settlement_revision
        ticket["realized_payout"] = realized_payout
        ticket["realized_pnl"] = realized_pnl
        ticket["roi"] = roi
        ticket["void_state"] = void_state
        return True

    def upsert_book_access_profile(self, row):
        self.book_access_profiles[row["bookmaker"]] = dict(row, updated_at=_utcnow().isoformat())
        return True

    def list_book_access_profiles(self, limit=200):
        return list(self.book_access_profiles.values())[:limit]
