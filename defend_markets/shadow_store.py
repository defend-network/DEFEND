"""Persistence for the Phase D shadow engine (P0-P5).

PostgresShadowStore is the production surface; InMemoryShadowStore mirrors it
for unit tests. All writes are idempotent: unique natural keys make restarting
a soak safe (no duplicated observations, ruler rows, or evaluation rows).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from psycopg.types.json import Jsonb

from defend_markets.db import MarketsDatabase
from defend_markets.m5_live import FrozenM5
from defend_markets.shadow import (
    POST_COMMENCE,
    RawPrice,
    RulerRow,
)


class ShadowStore:
    def upsert_forward_event(
        self,
        *,
        provider: str,
        provider_event_id: str,
        canonical_event_id: str | None,
        competition: str,
        player_a_key: str,
        player_b_key: str,
        player_a_name: str | None,
        player_b_name: str | None,
        scheduled_commence: datetime,
        match_level: str,
        discovered_at: datetime,
    ) -> int:
        raise NotImplementedError

    def list_forward_events(self, state: str | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError

    def set_state(self, forward_event_id: int, state: str) -> None:
        raise NotImplementedError

    def set_commence_crossed(self, forward_event_id: int, at: datetime) -> None:
        raise NotImplementedError

    def record_raw_evidence(
        self,
        *,
        evidence_sha256: str,
        provider: str,
        endpoint: str,
        fetched_at: datetime,
        status_code: int | None,
        payload: Any,
    ) -> bool:
        raise NotImplementedError

    def set_last_odds_poll(self, forward_event_id: int, at: datetime) -> None:
        raise NotImplementedError

    def forward_event(self, forward_event_id: int) -> dict[str, Any] | None:
        raise NotImplementedError

    def insert_observation(
        self,
        *,
        forward_event_id: int,
        canonical_event_id: str,
        provider: str,
        provider_event_id: str,
        bookmaker: str,
        market: str,
        provider_market_id: str,
        side: str,
        participant_key: str,
        price: float,
        observed_at: datetime,
        scheduled_commence: datetime,
        raw_provenance: str,
        raw_evidence_ref: str,
        observation_class: str,
    ) -> int:
        raise NotImplementedError

    def list_observations(self, canonical_event_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def list_observations_for_event_id(self, forward_event_id: int) -> list[dict[str, Any]]:
        raise NotImplementedError

    def promote_last_valid_prematch(
        self, canonical_event_id: str, observation_id: int
    ) -> None:
        raise NotImplementedError

    def insert_m5_prediction(
        self,
        *,
        canonical_event_id: str,
        player_a_key: str,
        player_b_key: str,
        model_id: str,
        model_version: str,
        feature_snapshot_id: str,
        generated_at: datetime,
        p_a: float,
        p_b: float,
        availability: str,
        feature_payload: dict[str, Any],
    ) -> bool:
        raise NotImplementedError

    def m5_prediction(self, canonical_event_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def insert_ruler_row(self, row: RulerRow, *, raw: dict[str, Any]) -> None:
        raise NotImplementedError

    def list_ruler_rows(self, canonical_event_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def insert_evaluation_row(self, row: dict[str, Any]) -> bool:
        raise NotImplementedError

    def evaluation_rows(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def start_soak(self, started_at: datetime) -> int:
        raise NotImplementedError

    def update_soak(
        self,
        run_id: int,
        *,
        cycle_count: int,
        api_requests: int,
        api_errors: int,
        rate_limit_events: int,
        cost_usd: float,
        metrics: dict[str, Any],
    ) -> None:
        raise NotImplementedError

    def finish_soak(self, run_id: int, finished_at: datetime) -> None:
        raise NotImplementedError

    def soak_runs(self) -> list[dict[str, Any]]:
        raise NotImplementedError


class PostgresShadowStore(ShadowStore):
    def __init__(self, database: MarketsDatabase) -> None:
        self._database = database

    def upsert_forward_event(
        self,
        *,
        provider: str,
        provider_event_id: str,
        canonical_event_id: str | None,
        competition: str,
        player_a_key: str,
        player_b_key: str,
        player_a_name: str | None,
        player_b_name: str | None,
        scheduled_commence: datetime,
        match_level: str,
        discovered_at: datetime,
    ) -> int:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tt_forward_events
                    (provider, provider_event_id, canonical_event_id, competition,
                     player_a_key, player_b_key, player_a_name, player_b_name,
                     scheduled_commence, match_level, discovered_at, last_seen_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (provider, provider_event_id)
                DO UPDATE SET canonical_event_id = COALESCE(EXCLUDED.canonical_event_id,
                                tt_forward_events.canonical_event_id),
                              player_a_key = EXCLUDED.player_a_key,
                              player_b_key = EXCLUDED.player_b_key,
                              scheduled_commence = EXCLUDED.scheduled_commence,
                              match_level = EXCLUDED.match_level,
                              last_seen_at = EXCLUDED.last_seen_at,
                              player_a_name = EXCLUDED.player_a_name,
                              player_b_name = EXCLUDED.player_b_name
                RETURNING forward_event_id
                """,
                (
                    provider, provider_event_id, canonical_event_id, competition,
                    player_a_key, player_b_key, player_a_name, player_b_name,
                    scheduled_commence, match_level, discovered_at, discovered_at,
                ),
            )
            return int(cursor.fetchone()[0])

    def list_forward_events(self, state: str | None = None) -> list[dict[str, Any]]:
        with self._database.connect() as connection, connection.cursor() as cursor:
            if state is None:
                cursor.execute("SELECT * FROM tt_forward_events ORDER BY scheduled_commence")
            else:
                cursor.execute(
                    "SELECT * FROM tt_forward_events WHERE state = %s ORDER BY scheduled_commence",
                    (state,),
                )
            return [_row_forward(columns(cursor), row) for row in cursor.fetchall()]

    def set_state(self, forward_event_id: int, state: str) -> None:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE tt_forward_events SET state = %s, updated_at = now() WHERE forward_event_id = %s",
                (state, forward_event_id),
            )

    def set_commence_crossed(self, forward_event_id: int, at: datetime) -> None:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE tt_forward_events SET commence_crossed_at = %s, state = 'LIVE' WHERE forward_event_id = %s",
                (at, forward_event_id),
            )

    def record_raw_evidence(
        self,
        *,
        evidence_sha256: str,
        provider: str,
        endpoint: str,
        fetched_at: datetime,
        status_code: int | None,
        payload: Any,
    ) -> bool:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tt_raw_evidence
                    (evidence_sha256, provider, endpoint, fetched_at, status_code, payload)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (evidence_sha256) DO NOTHING
                RETURNING evidence_id
                """,
                (
                    evidence_sha256, provider, endpoint, fetched_at, status_code,
                    Jsonb(payload),
                ),
            )
            return cursor.fetchone() is not None

    def set_last_odds_poll(self, forward_event_id: int, at: datetime) -> None:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE tt_forward_events SET last_odds_poll_at = %s WHERE forward_event_id = %s",
                (at, forward_event_id),
            )

    def forward_event(self, forward_event_id: int) -> dict[str, Any] | None:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM tt_forward_events WHERE forward_event_id = %s",
                (forward_event_id,),
            )
            row = cursor.fetchone()
            return _row_forward(columns(cursor), row) if row is not None else None

    def insert_observation(
        self,
        *,
        forward_event_id: int,
        canonical_event_id: str,
        provider: str,
        provider_event_id: str,
        bookmaker: str,
        market: str,
        provider_market_id: str,
        side: str,
        participant_key: str,
        price: float,
        observed_at: datetime,
        scheduled_commence: datetime,
        raw_provenance: str,
        raw_evidence_ref: str,
        observation_class: str,
    ) -> int:
        seconds = (scheduled_commence - observed_at).total_seconds()
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tt_market_observations
                    (forward_event_id, canonical_event_id, provider, provider_event_id,
                     bookmaker, market, provider_market_id, side, participant_key, price,
                     observed_at, scheduled_commence, seconds_to_commence,
                     raw_provenance, raw_evidence_ref, observation_class)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (provider_event_id, bookmaker, market, side, observed_at)
                DO NOTHING
                RETURNING observation_id
                """,
                (
                    forward_event_id, canonical_event_id, provider, provider_event_id,
                    bookmaker, market, provider_market_id, side, participant_key, price,
                    observed_at, scheduled_commence, seconds, raw_provenance,
                    raw_evidence_ref, observation_class,
                ),
            )
            row = cursor.fetchone()
            if row is not None:
                return int(row[0])
            cursor.execute(
                """
                SELECT observation_id FROM tt_market_observations
                WHERE provider_event_id = %s AND bookmaker = %s AND market = %s
                  AND side = %s AND observed_at = %s
                """,
                (provider_event_id, bookmaker, market, side, observed_at),
            )
            return int(cursor.fetchone()[0])

    def list_observations(self, canonical_event_id: str) -> list[dict[str, Any]]:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM tt_market_observations
                WHERE canonical_event_id = %s ORDER BY observed_at
                """,
                (canonical_event_id,),
            )
            return [_row_observation(columns(cursor), row) for row in cursor.fetchall()]

    def list_observations_for_event_id(self, forward_event_id: int) -> list[dict[str, Any]]:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM tt_market_observations
                WHERE forward_event_id = %s ORDER BY observed_at
                """,
                (forward_event_id,),
            )
            return [_row_observation(columns(cursor), row) for row in cursor.fetchall()]

    def promote_last_valid_prematch(
        self, canonical_event_id: str, observation_id: int
    ) -> None:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE tt_market_observations
                SET observation_class = 'LAST_VALID_PREMATCH'
                WHERE observation_id = %s AND canonical_event_id = %s
                """,
                (observation_id, canonical_event_id),
            )

    def insert_m5_prediction(
        self,
        *,
        canonical_event_id: str,
        player_a_key: str,
        player_b_key: str,
        model_id: str,
        model_version: str,
        feature_snapshot_id: str,
        generated_at: datetime,
        p_a: float,
        p_b: float,
        availability: str,
        feature_payload: dict[str, Any],
    ) -> bool:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tt_m5_live_predictions
                    (canonical_event_id, player_a_key, player_b_key, model_id,
                     model_version, feature_snapshot_id, generated_at, p_a, p_b,
                     availability, feature_payload)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (canonical_event_id) DO NOTHING
                RETURNING prediction_id
                """,
                (
                    canonical_event_id, player_a_key, player_b_key, model_id,
                    model_version, feature_snapshot_id, generated_at, p_a, p_b,
                    availability, Jsonb(feature_payload),
                ),
            )
            return cursor.fetchone() is not None

    def m5_prediction(self, canonical_event_id: str) -> dict[str, Any] | None:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM tt_m5_live_predictions WHERE canonical_event_id = %s",
                (canonical_event_id,),
            )
            row = cursor.fetchone()
            return _row_m5(columns(cursor), row) if row is not None else None

    def insert_ruler_row(self, row: RulerRow, *, raw: dict[str, Any]) -> None:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tt_market_ruler_rows
                    (observation_id, canonical_event_id, observation_class,
                     side_a_price, side_b_price, raw_implied_p_a, raw_implied_p_b,
                     overround, no_vig_p_a, no_vig_p_b, m5_p_a,
                     model_market_disagreement, observation_age_seconds,
                     seconds_to_commence)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (observation_id) DO NOTHING
                """,
                (
                    row.observation_id, row.canonical_event_id, row.observation_class,
                    row.side_a_price, row.side_b_price, row.raw_implied_p_a,
                    row.raw_implied_p_b, row.overround, row.no_vig_p_a, row.no_vig_p_b,
                    row.m5_p_a, row.model_market_disagreement,
                    row.observation_age_seconds, row.seconds_to_commence,
                ),
            )

    def list_ruler_rows(self, canonical_event_id: str) -> list[dict[str, Any]]:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT o.observed_at, r.* FROM tt_market_ruler_rows r
                JOIN tt_market_observations o USING (observation_id)
                WHERE r.canonical_event_id = %s ORDER BY o.observed_at
                """,
                (canonical_event_id,),
            )
            cols = [d.name for d in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]

    def insert_evaluation_row(self, row: dict[str, Any]) -> bool:
        with self._database.connect() as connection, connection.cursor() as cursor:
            market_p = row["market_no_vig_p_a"]
            cursor.execute(
                """
                INSERT INTO tt_shadow_evaluation
                    (canonical_event_id, result_id, settled_at, model_id, model_version,
                     reference_class, m5_p_a, market_no_vig_p_a, m5_brier, market_brier,
                     m5_log_loss, market_log_loss, m5_minus_market_brier, actual)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (canonical_event_id, result_id, reference_class) DO NOTHING
                RETURNING entry_id
                """,
                (
                    row["canonical_event_id"], row["result_id"], row["settled_at"],
                    row["model_id"], row["model_version"], row["reference_class"],
                    row["m5_p_a"], market_p,
                    brier(row["m5_p_a"], row["actual"]) if market_p is not None else brier(row["m5_p_a"], row["actual"]),
                    brier(market_p, row["actual"]) if market_p is not None else None,
                    log_loss(row["m5_p_a"], row["actual"]) if market_p is not None else log_loss(row["m5_p_a"], row["actual"]),
                    log_loss(market_p, row["actual"]) if market_p is not None else None,
                    (brier(row["m5_p_a"], row["actual"]) - brier(market_p, row["actual"]))
                    if market_p is not None else None,
                    row["actual"],
                ),
            )
            return cursor.fetchone() is not None

    def evaluation_rows(self) -> list[dict[str, Any]]:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM tt_shadow_evaluation ORDER BY settled_at"
            )
            return [dict(zip([d.name for d in cursor.description], row)) for row in cursor.fetchall()]

    def start_soak(self, started_at: datetime) -> int:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tt_shadow_soak_runs (started_at, status)
                VALUES (%s, 'RUNNING') RETURNING run_id
                """,
                (started_at,),
            )
            return int(cursor.fetchone()[0])

    def update_soak(
        self,
        run_id: int,
        *,
        cycle_count: int,
        api_requests: int,
        api_errors: int,
        rate_limit_events: int,
        cost_usd: float,
        metrics: dict[str, Any],
    ) -> None:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE tt_shadow_soak_runs
                SET cycle_count = %s, api_requests = %s, api_errors = %s,
                    rate_limit_events = %s, cost_usd = %s, metrics = %s
                WHERE run_id = %s
                """,
                (
                    cycle_count, api_requests, api_errors, rate_limit_events,
                    cost_usd, Jsonb(metrics), run_id,
                ),
            )

    def finish_soak(self, run_id: int, finished_at: datetime) -> None:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE tt_shadow_soak_runs SET finished_at = %s, status = 'COMPLETED' WHERE run_id = %s",
                (finished_at, run_id),
            )

    def soak_runs(self) -> list[dict[str, Any]]:
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM tt_shadow_soak_runs ORDER BY run_id")
            return [dict(zip([d.name for d in cursor.description], row)) for row in cursor.fetchall()]


def columns(cursor: Any) -> list[str]:
    return [d.name for d in cursor.description]


def _row_forward(cols: list[str], row: tuple[Any, ...]) -> dict[str, Any]:
    return dict(zip(cols, row))


def _row_observation(cols: list[str], row: tuple[Any, ...]) -> dict[str, Any]:
    return dict(zip(cols, row))


def _row_m5(cols: list[str], row: tuple[Any, ...]) -> dict[str, Any]:
    return dict(zip(cols, row))


def brier(p: float, actual: float) -> float:
    return (p - actual) ** 2


def log_loss(p: float, actual: float) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return -(actual * math.log(p) + (1 - actual) * math.log(1 - p))


# --------------------------------------------------------------------------- #
# In-memory mirror for unit tests (same idempotent semantics)
# --------------------------------------------------------------------------- #
@dataclass
class InMemoryShadowStore(ShadowStore):
    forward_events: list[dict[str, Any]] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)
    m5_predictions: dict[str, dict[str, Any]] = field(default_factory=dict)
    ruler_rows: list[dict[str, Any]] = field(default_factory=list)
    _evaluation_rows: list[dict[str, Any]] = field(default_factory=list)
    soak_runs: list[dict[str, Any]] = field(default_factory=list)
    raw_evidence: list[dict[str, Any]] = field(default_factory=list)
    _next_forward: int = 1
    _next_obs: int = 1

    def upsert_forward_event(
        self,
        *,
        provider: str,
        provider_event_id: str,
        canonical_event_id: str | None,
        competition: str,
        player_a_key: str,
        player_b_key: str,
        player_a_name: str | None,
        player_b_name: str | None,
        scheduled_commence: datetime,
        match_level: str,
        discovered_at: datetime,
    ) -> int:
        for event in self.forward_events:
            if event["provider"] == provider and event["provider_event_id"] == provider_event_id:
                event.update(
                    canonical_event_id=canonical_event_id or event["canonical_event_id"],
                    player_a_key=player_a_key,
                    player_b_key=player_b_key,
                    scheduled_commence=scheduled_commence,
                    match_level=match_level,
                    last_seen_at=discovered_at,
                )
                return int(event["forward_event_id"])
        event_id = self._next_forward
        self._next_forward += 1
        self.forward_events.append(
            {
                "forward_event_id": event_id,
                "provider": provider,
                "provider_event_id": provider_event_id,
                "canonical_event_id": canonical_event_id,
                "competition": competition,
                "player_a_key": player_a_key,
                "player_b_key": player_b_key,
                "player_a_name": player_a_name,
                "player_b_name": player_b_name,
                "scheduled_commence": scheduled_commence,
                "match_level": match_level,
                "state": "UPCOMING",
                "discovered_at": discovered_at,
                "last_seen_at": discovered_at,
                "commence_crossed_at": None,
                "settled_at": None,
            }
        )
        return event_id

    def list_forward_events(self, state: str | None = None) -> list[dict[str, Any]]:
        events = sorted(self.forward_events, key=lambda e: e["scheduled_commence"])
        return [e for e in events if state is None or e["state"] == state]

    def set_state(self, forward_event_id: int, state: str) -> None:
        for event in self.forward_events:
            if event["forward_event_id"] == forward_event_id:
                event["state"] = state

    def set_commence_crossed(self, forward_event_id: int, at: datetime) -> None:
        for event in self.forward_events:
            if event["forward_event_id"] == forward_event_id:
                event["commence_crossed_at"] = at
                event["state"] = "LIVE"

    def record_raw_evidence(
        self,
        *,
        evidence_sha256: str,
        provider: str,
        endpoint: str,
        fetched_at: datetime,
        status_code: int | None,
        payload: Any,
    ) -> bool:
        if any(e["evidence_sha256"] == evidence_sha256 for e in self.raw_evidence):
            return False
        self.raw_evidence.append(
            {
                "evidence_sha256": evidence_sha256,
                "provider": provider,
                "endpoint": endpoint,
                "fetched_at": fetched_at,
                "status_code": status_code,
                "payload": payload,
            }
        )
        return True

    def set_last_odds_poll(self, forward_event_id: int, at: datetime) -> None:
        for event in self.forward_events:
            if event["forward_event_id"] == forward_event_id:
                event["last_odds_poll_at"] = at

    def forward_event(self, forward_event_id: int) -> dict[str, Any] | None:
        for event in self.forward_events:
            if event["forward_event_id"] == forward_event_id:
                return event
        return None

    def insert_observation(
        self,
        *,
        forward_event_id: int,
        canonical_event_id: str,
        provider: str,
        provider_event_id: str,
        bookmaker: str,
        market: str,
        provider_market_id: str,
        side: str,
        participant_key: str,
        price: float,
        observed_at: datetime,
        scheduled_commence: datetime,
        raw_provenance: str,
        raw_evidence_ref: str,
        observation_class: str,
    ) -> int:
        for existing in self.observations:
            if (
                existing["provider_event_id"] == provider_event_id
                and existing["bookmaker"] == bookmaker
                and existing["market"] == market
                and existing["side"] == side
                and existing["observed_at"] == observed_at
            ):
                return int(existing["observation_id"])
        obs_id = self._next_obs
        self._next_obs += 1
        self.observations.append(
            {
                "observation_id": obs_id,
                "forward_event_id": forward_event_id,
                "canonical_event_id": canonical_event_id,
                "provider": provider,
                "provider_event_id": provider_event_id,
                "bookmaker": bookmaker,
                "market": market,
                "provider_market_id": provider_market_id,
                "side": side,
                "participant_key": participant_key,
                "price": float(price),
                "observed_at": observed_at,
                "scheduled_commence": scheduled_commence,
                "seconds_to_commence": (scheduled_commence - observed_at).total_seconds(),
                "raw_provenance": raw_provenance,
                "raw_evidence_ref": raw_evidence_ref,
                "observation_class": observation_class,
            }
        )
        return obs_id

    def list_observations(self, canonical_event_id: str) -> list[dict[str, Any]]:
        return sorted(
            (o for o in self.observations if o["canonical_event_id"] == canonical_event_id),
            key=lambda o: o["observed_at"],
        )

    def list_observations_for_event_id(self, forward_event_id: int) -> list[dict[str, Any]]:
        return sorted(
            (o for o in self.observations if o["forward_event_id"] == forward_event_id),
            key=lambda o: o["observed_at"],
        )

    def promote_last_valid_prematch(
        self, canonical_event_id: str, observation_id: int
    ) -> None:
        for obs in self.observations:
            if (
                obs["canonical_event_id"] == canonical_event_id
                and obs["observation_id"] == observation_id
            ):
                obs["observation_class"] = "LAST_VALID_PREMATCH"

    def insert_m5_prediction(
        self,
        *,
        canonical_event_id: str,
        player_a_key: str,
        player_b_key: str,
        model_id: str,
        model_version: str,
        feature_snapshot_id: str,
        generated_at: datetime,
        p_a: float,
        p_b: float,
        availability: str,
        feature_payload: dict[str, Any],
    ) -> bool:
        if canonical_event_id in self.m5_predictions:
            return False
        self.m5_predictions[canonical_event_id] = {
            "canonical_event_id": canonical_event_id,
            "player_a_key": player_a_key,
            "player_b_key": player_b_key,
            "model_id": model_id,
            "model_version": model_version,
            "feature_snapshot_id": feature_snapshot_id,
            "generated_at": generated_at,
            "p_a": float(p_a),
            "p_b": float(p_b),
            "availability": availability,
            "feature_payload": feature_payload,
        }
        return True

    def m5_prediction(self, canonical_event_id: str) -> dict[str, Any] | None:
        return self.m5_predictions.get(canonical_event_id)

    def insert_ruler_row(self, row: RulerRow, *, raw: dict[str, Any]) -> None:
        for existing in self.ruler_rows:
            if existing["observation_id"] == row.observation_id:
                return
        self.ruler_rows.append(
            {
                "observation_id": row.observation_id,
                "canonical_event_id": row.canonical_event_id,
                "observation_class": row.observation_class,
                "observed_at": row.observed_at,
                "side_a_price": row.side_a_price,
                "side_b_price": row.side_b_price,
                "raw_implied_p_a": row.raw_implied_p_a,
                "raw_implied_p_b": row.raw_implied_p_b,
                "overround": row.overround,
                "no_vig_p_a": row.no_vig_p_a,
                "no_vig_p_b": row.no_vig_p_b,
                "m5_p_a": row.m5_p_a,
                "model_market_disagreement": row.model_market_disagreement,
                "observation_age_seconds": row.observation_age_seconds,
                "seconds_to_commence": row.seconds_to_commence,
                "actual": None,
            }
        )

    def list_ruler_rows(self, canonical_event_id: str) -> list[dict[str, Any]]:
        rows = [r for r in self.ruler_rows if r["canonical_event_id"] == canonical_event_id]
        return sorted(rows, key=lambda r: r["observation_id"])

    def insert_evaluation_row(self, row: dict[str, Any]) -> bool:
        for existing in self._evaluation_rows:
            if (
                existing["canonical_event_id"] == row["canonical_event_id"]
                and existing["result_id"] == row["result_id"]
                and existing["reference_class"] == row["reference_class"]
            ):
                return False
        self._evaluation_rows.append(dict(row))
        return True

    def evaluation_rows(self) -> list[dict[str, Any]]:
        return sorted(self._evaluation_rows, key=lambda r: r["settled_at"])

    def start_soak(self, started_at: datetime) -> int:
        run_id = len(self.soak_runs) + 1
        self.soak_runs.append(
            {
                "run_id": run_id,
                "started_at": started_at,
                "finished_at": None,
                "status": "RUNNING",
                "cycle_count": 0,
                "api_requests": 0,
                "api_errors": 0,
                "rate_limit_events": 0,
                "cost_usd": 0,
                "metrics": {},
            }
        )
        return run_id

    def update_soak(
        self,
        run_id: int,
        *,
        cycle_count: int,
        api_requests: int,
        api_errors: int,
        rate_limit_events: int,
        cost_usd: float,
        metrics: dict[str, Any],
    ) -> None:
        for run in self.soak_runs:
            if run["run_id"] == run_id:
                run.update(
                    cycle_count=cycle_count,
                    api_requests=api_requests,
                    api_errors=api_errors,
                    rate_limit_events=rate_limit_events,
                    cost_usd=cost_usd,
                    metrics=metrics,
                )

    def finish_soak(self, run_id: int, finished_at: datetime) -> None:
        for run in self.soak_runs:
            if run["run_id"] == run_id:
                run["finished_at"] = finished_at
                run["status"] = "COMPLETED"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
