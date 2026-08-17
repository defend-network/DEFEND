"""Persistence API for DEFENDmarkets canonical entities.

All methods run against a caller-managed psycopg connection so a whole
evaluation batch can share one transaction. Upserts are idempotent via
database uniqueness constraints; observations are append-only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from defend_markets.domain import (
    DataQualityAssessment,
    DecisionRecord,
    EventEntity,
    EventEntityLink,
    EventImpactWindow,
    MarketEvent,
    MarketInstrument,
    Opportunity,
    Outcome,
    ProvenanceStamp,
    RiskPolicy,
    StrategyDefinition,
)
from defend_markets.risk import from_params, to_params
from defend_markets.strategies import build_default_registry


def _uuid() -> UUID:
    return uuid4()


class MarketsRepository:
    def upsert_instrument(self, connection: Any, instrument: MarketInstrument) -> UUID:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO market_instruments
                    (instrument_id, instrument_key, instrument_type, display_name,
                     venue_key, status, taxonomy_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (instrument_key)
                DO UPDATE SET
                    instrument_type = EXCLUDED.instrument_type,
                    display_name = EXCLUDED.display_name,
                    venue_key = EXCLUDED.venue_key,
                    status = EXCLUDED.status,
                    taxonomy_json = EXCLUDED.taxonomy_json,
                    updated_at = now()
                RETURNING instrument_id
                """,
                (
                    _uuid(),
                    instrument.instrument_key,
                    instrument.instrument_type.value,
                    instrument.display_name,
                    instrument.venue_key,
                    instrument.status.value,
                    Jsonb(dict(instrument.taxonomy)),
                ),
            )
            return cursor.fetchone()[0]

    def link_instrument(
        self,
        connection: Any,
        *,
        instrument_id: UUID,
        source_desk: str,
        source_table: str,
        source_id: UUID,
        link_type: str,
    ) -> UUID:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO market_instrument_links
                    (link_id, instrument_id, source_desk, source_table, source_id, link_type)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (instrument_id, source_desk, source_table, source_id)
                DO UPDATE SET link_type = EXCLUDED.link_type
                RETURNING link_id
                """,
                (_uuid(), instrument_id, source_desk, source_table, source_id, link_type),
            )
            return cursor.fetchone()[0]

    def instrument_ids(self, connection: Any) -> dict[str, UUID]:
        with connection.cursor() as cursor:
            cursor.execute("SELECT instrument_key, instrument_id FROM market_instruments")
            return {row[0]: row[1] for row in cursor.fetchall()}

    def upsert_event(self, connection: Any, event: MarketEvent) -> UUID:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO market_events
                    (event_id, event_key, event_type, title, event_time,
                     announced_at, retrieved_at, source_key, status, detail_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (event_key)
                DO UPDATE SET
                    event_type = EXCLUDED.event_type,
                    title = EXCLUDED.title,
                    event_time = COALESCE(EXCLUDED.event_time, market_events.event_time),
                    announced_at = COALESCE(EXCLUDED.announced_at, market_events.announced_at),
                    retrieved_at = COALESCE(EXCLUDED.retrieved_at, market_events.retrieved_at),
                    source_key = EXCLUDED.source_key,
                    status = EXCLUDED.status,
                    detail_json = EXCLUDED.detail_json
                RETURNING event_id
                """,
                (
                    _uuid(),
                    event.event_key,
                    event.event_type,
                    event.title,
                    event.event_time,
                    event.announced_at,
                    event.retrieved_at,
                    event.source_key,
                    event.status.value,
                    Jsonb(dict(event.detail)),
                ),
            )
            return cursor.fetchone()[0]

    def upsert_entity(self, connection: Any, entity: EventEntity) -> UUID:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO market_event_entities
                    (entity_id, entity_key, entity_type, display_name, taxonomy_json)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (entity_key)
                DO UPDATE SET
                    entity_type = EXCLUDED.entity_type,
                    display_name = EXCLUDED.display_name,
                    taxonomy_json = EXCLUDED.taxonomy_json
                RETURNING entity_id
                """,
                (_uuid(), entity.entity_key, entity.entity_type, entity.display_name, Jsonb(dict(entity.taxonomy))),
            )
            return cursor.fetchone()[0]

    def link_entity(
        self,
        connection: Any,
        link: EventEntityLink,
        *,
        event_id: UUID,
        entity_id: UUID,
    ) -> UUID:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO market_event_entity_links
                    (link_id, event_id, entity_id, role, valid_from, valid_to)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (event_id, entity_id, role)
                DO UPDATE SET valid_from = EXCLUDED.valid_from, valid_to = EXCLUDED.valid_to
                RETURNING link_id
                """,
                (_uuid(), event_id, entity_id, link.role, link.valid_from, link.valid_to),
            )
            return cursor.fetchone()[0]

    def upsert_impact(
        self,
        connection: Any,
        impact: EventImpactWindow,
        *,
        event_id: UUID,
        instrument_id: UUID,
    ) -> UUID:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO market_event_impacts
                    (impact_id, event_id, instrument_id, window_start, window_end,
                     direction, strength, evidence_ref, note)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING impact_id
                """,
                (
                    _uuid(),
                    event_id,
                    instrument_id,
                    impact.window_start,
                    impact.window_end,
                    impact.direction,
                    impact.strength,
                    impact.evidence_ref,
                    impact.note,
                ),
            )
            return cursor.fetchone()[0]

    def upsert_strategy(self, connection: Any, strategy: StrategyDefinition) -> UUID:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO market_strategies
                    (strategy_id, strategy_key, version, display_name, hypothesis,
                     lifecycle, params_json, source_ref)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (strategy_key, version)
                DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    hypothesis = EXCLUDED.hypothesis,
                    lifecycle = EXCLUDED.lifecycle,
                    params_json = EXCLUDED.params_json,
                    source_ref = EXCLUDED.source_ref
                RETURNING strategy_id
                """,
                (
                    _uuid(),
                    strategy.strategy_key,
                    strategy.version,
                    strategy.display_name,
                    strategy.hypothesis,
                    strategy.lifecycle.value,
                    Jsonb(dict(strategy.params)),
                    strategy.source_ref,
                ),
            )
            return cursor.fetchone()[0]

    def upsert_policy(self, connection: Any, policy: RiskPolicy) -> UUID:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO market_risk_policies (policy_id, policy_key, version, tier, params_json)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (policy_key, version)
                DO UPDATE SET tier = EXCLUDED.tier, params_json = EXCLUDED.params_json
                RETURNING policy_id
                """,
                (_uuid(), policy.policy_key, policy.version, policy.tier.value, Jsonb(to_params(policy))),
            )
            return cursor.fetchone()[0]

    def strategy_id(self, connection: Any, strategy_key: str) -> UUID:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT strategy_id FROM market_strategies
                WHERE strategy_key = %s ORDER BY version DESC LIMIT 1
                """,
                (strategy_key,),
            )
            row = cursor.fetchone()
            if row is None:
                raise KeyError(f"strategy not seeded: {strategy_key}")
            return row[0]

    def policy_id(self, connection: Any, policy_key: str) -> UUID:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT policy_id FROM market_risk_policies
                WHERE policy_key = %s ORDER BY version DESC LIMIT 1
                """,
                (policy_key,),
            )
            row = cursor.fetchone()
            if row is None:
                raise KeyError(f"policy not seeded: {policy_key}")
            return row[0]

    def load_policy(self, connection: Any, policy_key: str, version: int = 1) -> RiskPolicy:
        from defend_markets.domain import RiskTier

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT tier, params_json
                FROM market_risk_policies
                WHERE policy_key = %s AND version = %s
                """,
                (policy_key, version),
            )
            row = cursor.fetchone()
            if row is None:
                raise KeyError(f"risk policy not found: {policy_key}@{version}")
        return from_params(policy_key, version, RiskTier(row[0]), row[1])

    def insert_opportunity(self, connection: Any, opportunity: Opportunity) -> UUID:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO market_opportunities
                    (opportunity_id, instrument_id, strategy_id, policy_id, direction,
                     horizon, thesis, counter_thesis, evidence_json, historical_analogs_json,
                     gross_edge, net_edge, vig, spread, slippage, fees, other_costs, cost_estimate,
                     confidence, expected_value, max_loss, data_quality, data_quality_note,
                     risk_tier, model_version, invalidation, provenance_json, generated_at)
                VALUES (%s,
                        (SELECT instrument_id FROM market_instruments WHERE instrument_key = %s),
                        (SELECT strategy_id FROM market_strategies WHERE strategy_key = %s AND version = %s),
                        (SELECT policy_id FROM market_risk_policies WHERE policy_key = %s AND version = %s),
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING opportunity_id
                """,
                (
                    _uuid(),
                    opportunity.instrument_key,
                    opportunity.strategy_key,
                    opportunity.strategy_version,
                    opportunity.policy_key,
                    opportunity.policy_version,
                    opportunity.direction,
                    opportunity.horizon,
                    opportunity.thesis,
                    opportunity.counter_thesis,
                    Jsonb(list(opportunity.evidence)),
                    Jsonb(list(opportunity.historical_analogs)),
                    opportunity.gross_edge,
                    opportunity.net_edge,
                    opportunity.costs.vig,
                    opportunity.costs.spread,
                    opportunity.costs.slippage,
                    opportunity.costs.fees,
                    opportunity.costs.other_costs,
                    opportunity.cost_estimate,
                    opportunity.confidence,
                    opportunity.expected_value,
                    opportunity.max_loss,
                    opportunity.data_quality,
                    opportunity.data_quality_note,
                    opportunity.risk_tier.value,
                    opportunity.model_version,
                    opportunity.invalidation,
                    Jsonb([stamp_to_dict(stamp) for stamp in opportunity.provenance]),
                    opportunity.generated_at,
                ),
            )
            return cursor.fetchone()[0]

    def insert_decision(
        self,
        connection: Any,
        decision: DecisionRecord,
        *,
        opportunity_id: UUID | None,
        strategy_id: UUID,
        policy_id: UUID,
    ) -> UUID:
        if decision.data_cutoff_timestamp is None:
            raise ValueError(
                "persisted market decisions require data_cutoff_timestamp"
            )
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO market_decisions
                    (decision_id, opportunity_id, strategy_id, policy_id, decision_type,
                     reason_codes, thesis, counter_thesis, confidence, estimated_edge,
                     cost_estimate, data_cutoff_timestamp, invalidation, model_version,
                     created_at, amendment_of, note)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s)
                RETURNING decision_id
                """,
                (
                    _uuid(),
                    opportunity_id,
                    strategy_id,
                    policy_id,
                    decision.decision_type.value,
                    [code.value for code in decision.reason_codes],
                    decision.thesis,
                    decision.counter_thesis,
                    decision.confidence,
                    decision.estimated_edge,
                    decision.cost_estimate,
                    decision.data_cutoff_timestamp,
                    decision.invalidation,
                    decision.model_version,
                    decision.created_at or datetime.now(timezone.utc),
                    decision.amendment_of,
                    decision.note,
                ),
            )
            return cursor.fetchone()[0]

    def insert_outcome(self, connection: Any, outcome: Outcome) -> UUID:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO market_outcomes
                    (outcome_id, decision_id, resolved_at, result, pnl, clv,
                     calibration_bucket, detail_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING outcome_id
                """,
                (
                    _uuid(),
                    outcome.decision_id,
                    outcome.resolved_at or datetime.now(timezone.utc),
                    outcome.result,
                    outcome.pnl,
                    outcome.clv,
                    outcome.calibration_bucket,
                    Jsonb(dict(outcome.detail)),
                ),
            )
            return cursor.fetchone()[0]

    def attach_outcome(self, connection: Any, decision_id: UUID, outcome_id: UUID) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE market_decisions
                SET outcome_id = %s
                WHERE decision_id = %s
                """,
                (outcome_id, decision_id),
            )

    def insert_quality(self, connection: Any, assessment: DataQualityAssessment, instrument_id: UUID) -> UUID:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO market_data_quality
                    (quality_id, instrument_id, venue_key, score, freshness_ok,
                     availability, checks_json, as_of)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING quality_id
                """,
                (
                    _uuid(),
                    instrument_id,
                    assessment.venue_key,
                    assessment.score,
                    assessment.freshness_ok,
                    assessment.availability,
                    Jsonb(dict(assessment.checks)),
                    assessment.as_of or datetime.now(timezone.utc),
                ),
            )
            return cursor.fetchone()[0]

    def seed_defaults(self, connection: Any) -> dict[str, int]:
        from defend_markets.risk import default_risk_policies

        policies = 0
        for policy in default_risk_policies():
            self.upsert_policy(connection, policy)
            policies += 1

        strategies = 0
        for definition in build_default_registry().list():
            self.upsert_strategy(connection, definition)
            strategies += 1

        return {"policies": policies, "strategies": strategies}

    def list_instruments(self, connection: Any, desk: str | None = None) -> list[dict[str, object]]:
        sql = """
            SELECT instrument_key, instrument_type, display_name, venue_key, status, taxonomy_json
            FROM market_instruments
        """
        params: tuple[Any, ...] = ()
        if desk is not None:
            sql += " WHERE instrument_key LIKE %s"
            params = (f"{desk}:%",)
        sql += " ORDER BY instrument_key"
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return [
                {
                    "instrument_key": row[0],
                    "instrument_type": row[1],
                    "display_name": row[2],
                    "venue_key": row[3],
                    "status": row[4],
                    "taxonomy": row[5],
                }
                for row in cursor.fetchall()
            ]

    def list_events(self, connection: Any) -> list[dict[str, object]]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT event_key, event_type, title, event_time, announced_at, retrieved_at, source_key, status
                FROM market_events ORDER BY created_at
                """
            )
            return [
                {
                    "event_key": row[0],
                    "event_type": row[1],
                    "title": row[2],
                    "event_time": row[3],
                    "announced_at": row[4],
                    "retrieved_at": row[5],
                    "source_key": row[6],
                    "status": row[7],
                }
                for row in cursor.fetchall()
            ]

    def list_policies(self, connection: Any) -> list[dict[str, object]]:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT policy_key, version, tier, params_json FROM market_risk_policies ORDER BY policy_key, version"
            )
            return [
                {"policy_key": row[0], "version": row[1], "tier": row[2], "params": row[3]}
                for row in cursor.fetchall()
            ]

    def list_strategies(self, connection: Any) -> list[dict[str, object]]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT strategy_key, version, display_name, lifecycle, source_ref
                FROM market_strategies ORDER BY strategy_key, version
                """
            )
            return [
                {"strategy_key": row[0], "version": row[1], "display_name": row[2], "lifecycle": row[3], "source_ref": row[4]}
                for row in cursor.fetchall()
            ]

    def list_opportunities(self, connection: Any, limit: int = 50) -> list[dict[str, object]]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT o.opportunity_id, i.instrument_key, s.strategy_key, p.policy_key,
                       o.direction, o.horizon, o.thesis, o.gross_edge, o.net_edge,
                       o.cost_estimate, o.confidence, o.expected_value, o.data_quality,
                       o.risk_tier, o.generated_at
                FROM market_opportunities o
                JOIN market_instruments i ON i.instrument_id = o.instrument_id
                JOIN market_strategies s ON s.strategy_id = o.strategy_id
                JOIN market_risk_policies p ON p.policy_id = o.policy_id
                ORDER BY o.generated_at DESC LIMIT %s
                """,
                (limit,),
            )
            return [
                {
                    "opportunity_id": str(row[0]),
                    "instrument_key": row[1],
                    "strategy_key": row[2],
                    "policy_key": row[3],
                    "direction": row[4],
                    "horizon": row[5],
                    "thesis": row[6],
                    "gross_edge": row[7],
                    "net_edge": row[8],
                    "cost_estimate": row[9],
                    "confidence": row[10],
                    "expected_value": row[11],
                    "data_quality": row[12],
                    "risk_tier": row[13],
                    "generated_at": row[14],
                }
                for row in cursor.fetchall()
            ]

    def list_decisions(self, connection: Any, limit: int = 50) -> list[dict[str, object]]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT d.decision_id, d.opportunity_id, s.strategy_key, p.policy_key,
                       d.decision_type, d.reason_codes, d.thesis, d.confidence,
                       d.estimated_edge, d.cost_estimate, d.data_cutoff_timestamp,
                       d.model_version, d.created_at, d.amendment_of, d.outcome_id
                FROM market_decisions d
                JOIN market_strategies s ON s.strategy_id = d.strategy_id
                JOIN market_risk_policies p ON p.policy_id = d.policy_id
                ORDER BY d.created_at DESC LIMIT %s
                """,
                (limit,),
            )
            return [
                {
                    "decision_id": str(row[0]),
                    "opportunity_id": str(row[1]) if row[1] else None,
                    "strategy_key": row[2],
                    "policy_key": row[3],
                    "decision_type": row[4],
                    "reason_codes": list(row[5] or []),
                    "thesis": row[6],
                    "confidence": row[7],
                    "estimated_edge": row[8],
                    "cost_estimate": row[9],
                    "data_cutoff_timestamp": row[10],
                    "model_version": row[11],
                    "created_at": row[12],
                    "amendment_of": str(row[13]) if row[13] else None,
                    "outcome_id": str(row[14]) if row[14] else None,
                }
                for row in cursor.fetchall()
            ]

    def count_rows(self, connection: Any, table: str) -> int:
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM {table}")
            return int(cursor.fetchone()[0])


def stamp_to_dict(stamp: object) -> dict[str, object]:
    if not isinstance(stamp, ProvenanceStamp):
        raise TypeError("provenance entries must be ProvenanceStamp")
    return {
        "source_key": stamp.source_key,
        "observed_at": stamp.observed_at.isoformat() if stamp.observed_at else None,
        "received_at": stamp.received_at.isoformat() if stamp.received_at else None,
        "raw_ref": stamp.raw_ref,
        "normalization_version": stamp.normalization_version,
    }