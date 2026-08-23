"""Postgres persistence for the TT prediction system.

All writes are INSERT-only or idempotent upserts: prediction records are
immutable, corrections are append-only amendments, settlements are keyed
by ``(prediction_id, source_raw_ref)`` and collector state is a single
upserted row. Feature snapshots are stored whole as JSONB so a replay can
reconstruct a prediction without recomputing anything.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence
from uuid import UUID

from psycopg.types.json import Jsonb

from defend_markets.db import MarketsDatabase
from defend_markets.forecast import (
    PredictionRecord,
    ResearchEntry,
    SettlementRecord,
    ShadowRecord,
)

_SENTINEL = object()


class PostgresForecastStore:
    """Persistence surface for identity, snapshots, predictions and metrics."""

    def __init__(self, database: MarketsDatabase) -> None:
        self._database = database

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------
    def participant_by_normalized(self, normalized_name: str) -> list[dict[str, object]]:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT participant_id, canonical_name, normalized_name, identity_state,
                       first_seen, last_seen
                FROM tt_participants
                WHERE normalized_name = %s
                ORDER BY participant_id
                """,
                (normalized_name,),
            )
            rows = [self._participant_row(row) for row in cursor.fetchall()]
            if rows:
                return rows
            cursor.execute(
                """
                SELECT p.participant_id, p.canonical_name, p.normalized_name,
                       p.identity_state, p.first_seen, p.last_seen
                FROM tt_participant_aliases a
                JOIN tt_participants p ON p.participant_id = a.participant_id
                WHERE a.normalized_name = %s
                ORDER BY p.participant_id
                """,
                (normalized_name,),
            )
            return [self._participant_row(row) for row in cursor.fetchall()]

    def participant_by_id(self, participant_id: int) -> dict[str, object] | None:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT participant_id, canonical_name, normalized_name, identity_state,
                       first_seen, last_seen
                FROM tt_participants
                WHERE participant_id = %s
                """,
                (participant_id,),
            )
            row = cursor.fetchone()
            return self._participant_row(row) if row is not None else None

    def insert_participant(
        self,
        *,
        canonical_name: str,
        normalized_name: str,
        state: str,
        seen_at: datetime,
    ) -> dict[str, object]:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tt_participants
                    (canonical_name, normalized_name, identity_state, first_seen, last_seen)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (normalized_name)
                DO UPDATE SET last_seen = EXCLUDED.last_seen
                RETURNING participant_id, canonical_name, normalized_name, identity_state,
                          first_seen, last_seen
                """,
                (canonical_name, normalized_name, state, seen_at, seen_at),
            )
            return self._participant_row(cursor.fetchone())

    def touch_participant(self, participant_id: int, seen_at: datetime) -> None:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE tt_participants SET last_seen = %s, updated_at = now() WHERE participant_id = %s",
                (seen_at, participant_id),
            )

    def set_participant_state(self, participant_id: int, state: str) -> None:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE tt_participants SET identity_state = %s, updated_at = now() WHERE participant_id = %s",
                (state, participant_id),
            )

    def add_alias(
        self,
        *,
        participant_id: int,
        alias_name: str,
        normalized_name: str,
        provider: str,
        raw_ref: str | None,
        seen_at: datetime,
    ) -> None:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tt_participant_aliases
                    (participant_id, alias_name, normalized_name, provider, raw_ref,
                     first_seen, last_seen)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (participant_id, normalized_name, provider)
                DO UPDATE SET last_seen = EXCLUDED.last_seen
                """,
                (participant_id, alias_name, normalized_name, provider, raw_ref, seen_at, seen_at),
            )

    def aliases_for(self, participant_id: int) -> list[dict[str, object]]:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT alias_id, alias_name, normalized_name, provider, raw_ref,
                       first_seen, last_seen
                FROM tt_participant_aliases
                WHERE participant_id = %s
                ORDER BY alias_id
                """,
                (participant_id,),
            )
            return [
                {
                    "alias_id": row[0],
                    "alias_name": row[1],
                    "normalized_name": row[2],
                    "provider": row[3],
                    "raw_ref": row[4],
                    "first_seen": row[5],
                    "last_seen": row[6],
                }
                for row in cursor.fetchall()
            ]

    def catalog_participants(self, limit: int = 500) -> list[dict[str, object]]:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT participant_id, canonical_name, normalized_name, identity_state,
                       first_seen, last_seen
                FROM tt_participants
                ORDER BY last_seen DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [self._participant_row(row) for row in cursor.fetchall()]

    def _participant_row(self, row: tuple[object, ...]) -> dict[str, object]:
        return {
            "participant_id": row[0],
            "canonical_name": row[1],
            "normalized_name": row[2],
            "identity_state": row[3],
            "first_seen": row[4],
            "last_seen": row[5],
        }

    # ------------------------------------------------------------------
    # Collector state
    # ------------------------------------------------------------------
    def get_collector_state(self, collector_key: str = "tt_collector") -> dict[str, object] | None:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT collector_key, last_cycle_at, last_scores_poll_at, last_odds_poll_at,
                       next_odds_poll_at, odds_interval_seconds, quota_status,
                       last_quota_remaining, last_quota_used, last_quota_last, last_error
                FROM tt_collector_state
                WHERE collector_key = %s
                """,
                (collector_key,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return {
            "collector_key": row[0],
            "last_cycle_at": row[1],
            "last_scores_poll_at": row[2],
            "last_odds_poll_at": row[3],
            "next_odds_poll_at": row[4],
            "odds_interval_seconds": row[5],
            "quota_status": row[6],
            "last_quota_remaining": row[7],
            "last_quota_used": row[8],
            "last_quota_last": row[9],
            "last_error": row[10],
        }

    def set_collector_state(
        self,
        *,
        collector_key: str = "tt_collector",
        last_cycle_at: datetime | None = None,
        last_scores_poll_at: datetime | None = None,
        last_odds_poll_at: datetime | None = None,
        next_odds_poll_at: datetime | None = None,
        odds_interval_seconds: int | None = None,
        quota_status: str | None = None,
        last_quota_remaining: int | None = None,
        last_quota_used: int | None = None,
        last_quota_last: str | None = None,
        last_error: str | None = None,
    ) -> None:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tt_collector_state
                    (collector_key, last_cycle_at, last_scores_poll_at, last_odds_poll_at,
                     next_odds_poll_at, odds_interval_seconds, quota_status,
                     last_quota_remaining, last_quota_used, last_quota_last, last_error)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (collector_key) DO UPDATE SET
                    last_cycle_at = EXCLUDED.last_cycle_at,
                    last_scores_poll_at = EXCLUDED.last_scores_poll_at,
                    last_odds_poll_at = EXCLUDED.last_odds_poll_at,
                    next_odds_poll_at = EXCLUDED.next_odds_poll_at,
                    odds_interval_seconds = EXCLUDED.odds_interval_seconds,
                    quota_status = EXCLUDED.quota_status,
                    last_quota_remaining = EXCLUDED.last_quota_remaining,
                    last_quota_used = EXCLUDED.last_quota_used,
                    last_quota_last = EXCLUDED.last_quota_last,
                    last_error = EXCLUDED.last_error,
                    updated_at = now()
                """,
                (
                    collector_key,
                    last_cycle_at,
                    last_scores_poll_at,
                    last_odds_poll_at,
                    next_odds_poll_at,
                    odds_interval_seconds,
                    quota_status,
                    last_quota_remaining,
                    last_quota_used,
                    last_quota_last,
                    last_error,
                ),
            )

    # ------------------------------------------------------------------
    # Feature snapshots
    # ------------------------------------------------------------------
    def insert_feature_snapshot(
        self,
        *,
        event_key: str,
        prediction_ts: datetime,
        feature_schema_version: int,
        feature_code_version: str,
        source_observation_ids: Sequence[str],
        payload: Mapping[str, object],
    ) -> int:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tt_feature_snapshots
                    (event_key, prediction_ts, feature_schema_version, feature_code_version,
                     source_observation_ids, payload)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING snapshot_id
                """,
                (
                    event_key,
                    prediction_ts,
                    feature_schema_version,
                    feature_code_version,
                    Jsonb(list(source_observation_ids)),
                    Jsonb(dict(payload)),
                ),
            )
            return int(cursor.fetchone()[0])

    def feature_snapshot_by_id(self, snapshot_id: int) -> dict[str, object] | None:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT snapshot_id, event_key, prediction_ts, feature_schema_version,
                       feature_code_version, source_observation_ids, payload
                FROM tt_feature_snapshots
                WHERE snapshot_id = %s
                """,
                (snapshot_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return {
            "snapshot_id": row[0],
            "event_key": row[1],
            "prediction_ts": row[2],
            "feature_schema_version": row[3],
            "feature_code_version": row[4],
            "source_observation_ids": row[5],
            "payload": row[6],
        }

    # ------------------------------------------------------------------
    # Predictions (immutable inserts; amendments append-only)
    # ------------------------------------------------------------------
    def insert_prediction(self, record: PredictionRecord) -> UUID:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tt_predictions
                    (prediction_id, created_ts, event_key, provider_event_id, sport_key,
                     player_a_id, player_b_id, player_a_name_at_prediction,
                     player_b_name_at_prediction, feature_snapshot_id, market_method_version,
                     market_p_a, market_p_b, best_price_a, best_price_b,
                     consensus_p_a, consensus_p_b, overround, book_count,
                     model_id, model_version, model_p_a, model_p_b, model_uncertainty,
                     edge_gross, edge_net, cost_model_version, data_age_seconds,
                     provider_health, identity_state, strategy_id, strategy_version,
                     strategy_lifecycle, decision, reason_codes, risk_policy_version,
                     journal_ref)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING prediction_id
                """,
                (
                    record.prediction_id,
                    record.created_ts,
                    record.event_key,
                    record.provider_event_id,
                    record.sport_key,
                    record.player_a_id,
                    record.player_b_id,
                    record.player_a_name_at_prediction,
                    record.player_b_name_at_prediction,
                    record.feature_snapshot_id,
                    record.market_method_version,
                    record.market_p_a,
                    record.market_p_b,
                    record.best_price_a,
                    record.best_price_b,
                    record.consensus_p_a,
                    record.consensus_p_b,
                    record.overround,
                    record.book_count,
                    record.model_id,
                    record.model_version,
                    record.model_p_a,
                    record.model_p_b,
                    record.model_uncertainty,
                    record.edge_gross,
                    record.edge_net,
                    record.cost_model_version,
                    record.data_age_seconds,
                    record.provider_health,
                    record.identity_state,
                    record.strategy_id,
                    record.strategy_version,
                    record.strategy_lifecycle,
                    record.decision,
                    Jsonb(list(record.reason_codes)),
                    record.risk_policy_version,
                    record.journal_ref,
                ),
            )
            return UUID(str(cursor.fetchone()[0]))

    def prediction_by_id(self, prediction_id: UUID) -> dict[str, object] | None:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT prediction_id, created_ts, event_key, provider_event_id, sport_key,
                       player_a_id, player_b_id, player_a_name_at_prediction,
                       player_b_name_at_prediction, feature_snapshot_id, market_method_version,
                       market_p_a, market_p_b, best_price_a, best_price_b,
                       consensus_p_a, consensus_p_b, overround, book_count,
                       model_id, model_version, model_p_a, model_p_b, model_uncertainty,
                       edge_gross, edge_net, cost_model_version, data_age_seconds,
                       provider_health, identity_state, strategy_id, strategy_version,
                       strategy_lifecycle, decision, reason_codes, risk_policy_version,
                       journal_ref
                FROM tt_predictions
                WHERE prediction_id = %s
                """,
                (prediction_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._prediction_row(row)

    def predictions_for_event(self, event_key: str, limit: int = 100) -> list[dict[str, object]]:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT prediction_id, created_ts, event_key, provider_event_id, sport_key,
                       player_a_id, player_b_id, player_a_name_at_prediction,
                       player_b_name_at_prediction, feature_snapshot_id, market_method_version,
                       market_p_a, market_p_b, best_price_a, best_price_b,
                       consensus_p_a, consensus_p_b, overround, book_count,
                       model_id, model_version, model_p_a, model_p_b, model_uncertainty,
                       edge_gross, edge_net, cost_model_version, data_age_seconds,
                       provider_health, identity_state, strategy_id, strategy_version,
                       strategy_lifecycle, decision, reason_codes, risk_policy_version,
                       journal_ref
                FROM tt_predictions
                WHERE event_key = %s
                ORDER BY created_ts DESC
                LIMIT %s
                """,
                (event_key, limit),
            )
            return [self._prediction_row(row) for row in cursor.fetchall()]

    def catalog_predictions(self, limit: int = 200) -> list[dict[str, object]]:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT prediction_id, created_ts, event_key, provider_event_id, sport_key,
                       player_a_id, player_b_id, player_a_name_at_prediction,
                       player_b_name_at_prediction, feature_snapshot_id, market_method_version,
                       market_p_a, market_p_b, best_price_a, best_price_b,
                       consensus_p_a, consensus_p_b, overround, book_count,
                       model_id, model_version, model_p_a, model_p_b, model_uncertainty,
                       edge_gross, edge_net, cost_model_version, data_age_seconds,
                       provider_health, identity_state, strategy_id, strategy_version,
                       strategy_lifecycle, decision, reason_codes, risk_policy_version,
                       journal_ref
                FROM tt_predictions
                ORDER BY created_ts DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [self._prediction_row(row) for row in cursor.fetchall()]

    def open_predictions(self) -> list[dict[str, object]]:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT p.prediction_id, p.created_ts, p.event_key, p.provider_event_id,
                       p.sport_key, p.player_a_name_at_prediction, p.player_b_name_at_prediction,
                       p.model_p_a, p.model_p_b, p.decision, p.journal_ref
                FROM tt_predictions p
                WHERE NOT EXISTS (
                    SELECT 1 FROM tt_settlements s WHERE s.prediction_id = p.prediction_id
                )
                ORDER BY p.created_ts
                """
            )
            return [
                {
                    "prediction_id": row[0],
                    "created_ts": row[1],
                    "event_key": row[2],
                    "provider_event_id": row[3],
                    "sport_key": row[4],
                    "player_a_name_at_prediction": row[5],
                    "player_b_name_at_prediction": row[6],
                    "model_p_a": row[7],
                    "model_p_b": row[8],
                    "decision": row[9],
                    "journal_ref": row[10],
                }
                for row in cursor.fetchall()
            ]

    def insert_amendment(self, prediction_id: UUID, reason: str, payload: Mapping[str, object]) -> None:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tt_prediction_amendments (prediction_id, reason, payload)
                VALUES (%s, %s, %s)
                """,
                (prediction_id, reason, Jsonb(dict(payload))),
            )

    def _prediction_row(self, row: tuple[object, ...]) -> dict[str, object]:
        return {
            "prediction_id": row[0],
            "created_ts": row[1],
            "event_key": row[2],
            "provider_event_id": row[3],
            "sport_key": row[4],
            "player_a_id": row[5],
            "player_b_id": row[6],
            "player_a_name_at_prediction": row[7],
            "player_b_name_at_prediction": row[8],
            "feature_snapshot_id": row[9],
            "market_method_version": row[10],
            "market_p_a": row[11],
            "market_p_b": row[12],
            "best_price_a": row[13],
            "best_price_b": row[14],
            "consensus_p_a": row[15],
            "consensus_p_b": row[16],
            "overround": row[17],
            "book_count": row[18],
            "model_id": row[19],
            "model_version": row[20],
            "model_p_a": row[21],
            "model_p_b": row[22],
            "model_uncertainty": row[23],
            "edge_gross": row[24],
            "edge_net": row[25],
            "cost_model_version": row[26],
            "data_age_seconds": row[27],
            "provider_health": row[28],
            "identity_state": row[29],
            "strategy_id": row[30],
            "strategy_version": row[31],
            "strategy_lifecycle": row[32],
            "decision": row[33],
            "reason_codes": list(row[34] or []),
            "risk_policy_version": row[35],
            "journal_ref": row[36],
        }

    # ------------------------------------------------------------------
    # Settlements
    # ------------------------------------------------------------------
    def insert_settlement(self, record: SettlementRecord) -> bool:
        """Idempotent per (prediction_id, source_raw_ref); returns created."""
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tt_settlements
                    (prediction_id, source_raw_ref, settlement_ts, winner_participant_key,
                     correct, residual, paper_stake, paper_pnl_gross, paper_costs,
                     paper_pnl_net, closing_market_p, closing_best_price, clv, settled_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (prediction_id, source_raw_ref) DO NOTHING
                RETURNING settlement_id
                """,
                (
                    record.prediction_id,
                    record.source_raw_ref,
                    record.settlement_ts,
                    record.winner_participant_key,
                    record.correct,
                    record.residual,
                    record.paper_stake,
                    record.paper_pnl_gross,
                    record.paper_costs,
                    record.paper_pnl_net,
                    record.closing_market_p,
                    record.closing_best_price,
                    record.clv,
                    record.settled_by,
                ),
            )
            return cursor.fetchone() is not None

    def settlements_for_prediction(self, prediction_id: UUID) -> list[dict[str, object]]:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT settlement_id, prediction_id, source_raw_ref, settlement_ts,
                       winner_participant_key, correct, residual, paper_stake,
                       paper_pnl_gross, paper_costs, paper_pnl_net,
                       closing_market_p, closing_best_price, clv, settled_by
                FROM tt_settlements
                WHERE prediction_id = %s
                ORDER BY settlement_id
                """,
                (prediction_id,),
            )
            return [self._settlement_row(row) for row in cursor.fetchall()]

    def catalog_settlements(self, limit: int = 500) -> list[dict[str, object]]:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT settlement_id, prediction_id, source_raw_ref, settlement_ts,
                       winner_participant_key, correct, residual, paper_stake,
                       paper_pnl_gross, paper_costs, paper_pnl_net,
                       closing_market_p, closing_best_price, clv, settled_by
                FROM tt_settlements
                ORDER BY settlement_ts DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [self._settlement_row(row) for row in cursor.fetchall()]

    def _settlement_row(self, row: tuple[object, ...]) -> dict[str, object]:
        return {
            "settlement_id": row[0],
            "prediction_id": row[1],
            "source_raw_ref": row[2],
            "settlement_ts": row[3],
            "winner_participant_key": row[4],
            "correct": row[5],
            "residual": row[6],
            "paper_stake": row[7],
            "paper_pnl_gross": row[8],
            "paper_costs": row[9],
            "paper_pnl_net": row[10],
            "closing_market_p": row[11],
            "closing_best_price": row[12],
            "clv": row[13],
            "settled_by": row[14],
        }

    # ------------------------------------------------------------------
    # Shadow baselines
    # ------------------------------------------------------------------
    def insert_shadow(self, record: ShadowRecord) -> None:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tt_shadow_predictions
                    (prediction_id, event_key, created_ts, market_p_a, market_p_b,
                     elo_p_a, elo_p_b, naive_form_p_a, naive_form_p_b,
                     model_id, model_version, strategy_id, strategy_version)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    record.prediction_id,
                    record.event_key,
                    record.created_ts,
                    record.market_p_a,
                    record.market_p_b,
                    record.elo_p_a,
                    record.elo_p_b,
                    record.naive_form_p_a,
                    record.naive_form_p_b,
                    record.model_id,
                    record.model_version,
                    record.strategy_id,
                    record.strategy_version,
                ),
            )

    def shadows_for_event(self, event_key: str) -> list[dict[str, object]]:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT shadow_id, prediction_id, event_key, created_ts,
                       market_p_a, market_p_b, elo_p_a, elo_p_b,
                       naive_form_p_a, naive_form_p_b, model_id, model_version,
                       strategy_id, strategy_version
                FROM tt_shadow_predictions
                WHERE event_key = %s
                ORDER BY created_ts DESC
                """,
                (event_key,),
            )
            return [
                {
                    "shadow_id": row[0],
                    "prediction_id": row[1],
                    "event_key": row[2],
                    "created_ts": row[3],
                    "market_p_a": row[4],
                    "market_p_b": row[5],
                    "elo_p_a": row[6],
                    "elo_p_b": row[7],
                    "naive_form_p_a": row[8],
                    "naive_form_p_b": row[9],
                    "model_id": row[10],
                    "model_version": row[11],
                    "strategy_id": row[12],
                    "strategy_version": row[13],
                }
                for row in cursor.fetchall()
            ]

    # ------------------------------------------------------------------
    # Rating history
    # ------------------------------------------------------------------
    def insert_rating_history(self, rows: Sequence[object]) -> int:
        """Append chronological Elo updates (idempotent per participant/event)."""
        if not rows:
            return 0
        from defend_markets.tt_rating import TTRatingHistoryRow

        written = 0
        with self._database.connect() as connection, connection.cursor() as cursor:
            for row in rows:
                if not isinstance(row, TTRatingHistoryRow):
                    raise TypeError("rows must be TTRatingHistoryRow instances")
                cursor.execute(
                    """
                    INSERT INTO tt_rating_history
                        (participant_key, ts, event_key, opponent_key,
                         pre_rating, expected, actual, post_rating, result,
                         model_version, source_provider, raw_ref)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (participant_key, ts, event_key) DO NOTHING
                    """,
                    (
                        row.participant_key,
                        row.ts,
                        row.event_key,
                        row.opponent_key,
                        row.pre_rating,
                        row.expected,
                        row.actual,
                        row.post_rating,
                        row.result,
                        row.model_version,
                        row.source_provider,
                        row.raw_ref,
                    ),
                )
                written += cursor.rowcount
        return written

    def catalog_rating_history(
        self, participant_key: str = "", limit: int = 2000
    ) -> list[dict[str, object]]:
        with self._database.connect() as connection, connection.cursor() as cursor:
            if participant_key:
                cursor.execute(
                    """
                    SELECT participant_key, ts, event_key, opponent_key,
                           pre_rating, expected, actual, post_rating, result,
                           model_version, source_provider, raw_ref
                    FROM tt_rating_history
                    WHERE participant_key = %s
                    ORDER BY ts, event_key
                    LIMIT %s
                    """,
                    (participant_key, limit),
                )
            else:
                cursor.execute(
                    """
                    SELECT participant_key, ts, event_key, opponent_key,
                           pre_rating, expected, actual, post_rating, result,
                           model_version, source_provider, raw_ref
                    FROM tt_rating_history
                    ORDER BY ts, event_key
                    LIMIT %s
                    """,
                    (limit,),
                )
            return [
                {
                    "participant_key": row[0],
                    "ts": row[1],
                    "event_key": row[2],
                    "opponent_key": row[3],
                    "pre_rating": row[4],
                    "expected": row[5],
                    "actual": row[6],
                    "post_rating": row[7],
                    "result": row[8],
                    "model_version": row[9],
                    "source_provider": row[10],
                    "raw_ref": row[11],
                }
                for row in cursor.fetchall()
            ]

    # ------------------------------------------------------------------
    # Research ledger
    # ------------------------------------------------------------------
    def insert_research_entry(self, entry: ResearchEntry) -> int:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tt_research_ledger
                    (hypothesis, change, expected_mechanism, model_id, model_version,
                     strategy_id, strategy_version, evaluation_period, results, decision)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING entry_id
                """,
                (
                    entry.hypothesis,
                    entry.change,
                    entry.expected_mechanism,
                    entry.model_id,
                    entry.model_version,
                    entry.strategy_id,
                    entry.strategy_version,
                    entry.evaluation_period,
                    Jsonb(dict(entry.results)),
                    entry.decision,
                ),
            )
            return int(cursor.fetchone()[0])

    def catalog_ledger(self, limit: int = 200) -> list[dict[str, object]]:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT entry_id, hypothesis, change, expected_mechanism, model_id,
                       model_version, strategy_id, strategy_version, evaluation_period,
                       results, decision, created_at
                FROM tt_research_ledger
                ORDER BY entry_id DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [
                {
                    "entry_id": row[0],
                    "hypothesis": row[1],
                    "change": row[2],
                    "expected_mechanism": row[3],
                    "model_id": row[4],
                    "model_version": row[5],
                    "strategy_id": row[6],
                    "strategy_version": row[7],
                    "evaluation_period": row[8],
                    "results": row[9],
                    "decision": row[10],
                    "created_at": row[11],
                }
                for row in cursor.fetchall()
            ]