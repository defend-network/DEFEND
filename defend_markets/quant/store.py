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


@dataclass
class InMemoryQuantStore(QuantStore):
    research: list[dict[str, Any]] = field(default_factory=list)
    models: list[dict[str, Any]] = field(default_factory=list)
    threads: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    budget: dict[tuple[str, str, str], dict[str, Any]] = field(default_factory=dict)
    snapshots: list[dict[str, Any]] = field(default_factory=list)
    experiments: list[dict[str, Any]] = field(default_factory=list)
    reviews: list[dict[str, Any]] = field(default_factory=list)
    _next_research: int = 1
    _next_thread: int = 1
    _next_message: int = 1

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
