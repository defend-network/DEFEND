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
    _next_research: int = 1
    _next_thread: int = 1
    _next_message: int = 1
    _next_evaluation: int = 1
    _next_hypothesis: int = 1

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
