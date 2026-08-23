"""In-memory fakes for hermetic DEFENDmarkets tests (no PostgreSQL needed)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Mapping
from uuid import UUID, uuid4

from defend_markets.domain import (
    CostModel,
    DecisionRecord,
    DecisionType,
    NoActionReason,
    Opportunity,
    Outcome,
    PitAvailability,
    ProvenanceStamp,
    RiskPolicy,
    RiskTier,
)
from defend_markets.journal import JournalEntry
from defend_markets.sports_adapter import SportsSelectionQuote


def _aware(hour: int = 12, day: int = 15) -> datetime:
    return datetime(2026, 8, day, hour, 0, tzinfo=timezone.utc)


def stamp(source: str, day: int = 15, hour: int = 12) -> ProvenanceStamp:
    return ProvenanceStamp(
        source_key=source,
        observed_at=_aware(hour, day),
        received_at=_aware(hour + 1, day),
        raw_ref=f"raw-{source}-{day}-{hour}",
        normalization_version=None,
    )


class FakeSportsReader:
    """Deterministic reader shaped like real Sports DB data."""

    def __init__(self, quotes: Mapping[str, list[SportsSelectionQuote]] | None = None) -> None:
        self._quotes = dict(quotes or {})
        self._history: dict[tuple[str, str], list[SportsSelectionQuote]] = {}
        self._participants: dict[str, list[str]] = {
            "tt-live-001": ["Player A", "Player B"],
        }
        self._live: dict[str, dict[str, object]] = {}
        self._health: dict[str, Mapping[str, object]] = {
            "book-a": {"status": "HEALTHY", "observed_at": _aware()},
            "book-b": {"status": "HEALTHY", "observed_at": _aware()},
        }
        self.venues_list = [
            {"venue_key": "book-a", "provider": "fixture", "display_name": "Book A", "is_active": True},
            {"venue_key": "book-b", "provider": "fixture", "display_name": "Book B", "is_active": True},
        ]

    def venues(self) -> list[dict[str, object]]:
        return list(self.venues_list)

    def tt_events(self) -> list[dict[str, object]]:
        return [
            {"event_key": "tt-live-001", "display_name": "Player A vs Player B",
             "league_key": "table_tennis"},
        ]

    def tt_event_participants(self, event_key: str) -> list[str]:
        return list(self._participants.get(event_key, []))

    def set_tt_event_participants(self, event_key: str, names: list[str]) -> None:
        self._participants[event_key] = list(names)

    def latest_live_state(self, event_key: str) -> dict[str, object] | None:
        live = self._live.get(event_key)
        if live is None:
            return None
        return dict(live)

    def set_live_state(self, event_key: str, state: dict[str, object]) -> None:
        self._live[event_key] = {
            "state": dict(state),
            "observed_at": _aware(),
            "received_at": _aware(hour=13),
        }

    def market_selections(self, event_key: str, market_key: str) -> list[SportsSelectionQuote]:
        return self._quotes.get((event_key, market_key), [])

    def latest_odds(self, event_key: str, market_key: str) -> list[SportsSelectionQuote]:
        return self._quotes.get((event_key, market_key), [])

    def set_odds_history(self, event_key: str, market_key: str, quotes: list[SportsSelectionQuote]) -> None:
        self._history[(event_key, market_key)] = list(quotes)

    def odds_history(
        self, event_key: str, market_key: str, before: object | None = None
    ) -> list[SportsSelectionQuote]:
        return list(self._history.get((event_key, market_key), []))

    def provider_health(self) -> dict[str, Mapping[str, object]]:
        return dict(self._health)

    def pit_availability(self) -> PitAvailability:
        return PitAvailability(provided=frozenset({"observed_at", "received_at", "scheduled_at", "raw_ref"}))


def arb_pair(
    day: int = 15,
    *,
    fees: str | None = None,
    selection_keys: tuple[str, str] = ("player_a", "player_b"),
) -> list[SportsSelectionQuote]:
    return [
        SportsSelectionQuote(
            selection_key=selection_keys[0],
            display_name=selection_keys[0],
            decimal_odds=Decimal("1.85"),
            provenance=stamp("book-a", day, 10),
            selection_id=str(uuid4()),
            costs=CostModel(fees=Decimal(fees)) if fees is not None else None,
        ),
        SportsSelectionQuote(
            selection_key=selection_keys[1],
            display_name=selection_keys[1],
            decimal_odds=Decimal("2.35"),
            provenance=stamp("book-b", day, 10),
            selection_id=str(uuid4()),
            costs=CostModel(fees=Decimal(fees)) if fees is not None else None,
        ),
    ]


def no_arb_pair(day: int = 15) -> list[SportsSelectionQuote]:
    return [
        SportsSelectionQuote(
            selection_key="player_a",
            display_name="Player A",
            decimal_odds=Decimal("1.85"),
            provenance=stamp("book-a", day, 10),
            selection_id=str(uuid4()),
        ),
        SportsSelectionQuote(
            selection_key="player_b",
            display_name="Player B",
            decimal_odds=Decimal("2.20"),
            provenance=stamp("book-b", day, 10),
            selection_id=str(uuid4()),
        ),
    ]


class InMemoryStore:
    def __init__(self, policies: Mapping[str, RiskPolicy] | None = None) -> None:
        self._policies = {
            policy.policy_key: policy
            for policy in (policies or {}).values()
        }
        self._strategy_ids: dict[str, UUID] = {}
        self._policy_ids: dict[str, UUID] = {}
        self._opportunities: list[Opportunity] = []
        self._instruments: list[dict[str, object]] = []
        self._decisions: list[dict[str, object]] = []
        self._outcomes: list[dict[str, object]] = []
        self._tt_results: list[dict[str, object]] = []
        self._feeds: dict[str, dict[str, object]] = {}
        self._feed_records: dict[str, list[dict[str, object]]] = {}

    def catalog_tt_results(self, limit: int = 2000, offset: int = 0) -> list[dict[str, object]]:
        return list(self._tt_results[-(limit + offset):-offset or None] if offset else self._tt_results[-limit:])

    def upsert_feed(self, definition: object) -> None:
        self._feeds[definition.provider_id] = {"provider_id": definition.provider_id}

    def record_probe(self, result: object, *, observed_at: object) -> None:
        self._feeds.setdefault(result.provider_id, {})["status"] = result.status

    def insert_records(self, provider_id: str, records: object, *, received_at: object) -> int:
        stored = [{"record_key": r.record_key} for r in records]
        self._feed_records.setdefault(provider_id, []).extend(stored)
        return len(stored)

    def record_tt_results(self, results: object) -> int:
        return len(results)

    def seed_tt_results(self, rows: list[dict[str, object]]) -> int:
        self._tt_results.extend(rows)
        return len(rows)

    def list_feeds(self) -> list[dict[str, object]]:
        return list(self._feeds.values())

    def list_records(self, provider_id: str, limit: int = 50) -> list[dict[str, object]]:
        return list(self._feed_records.get(provider_id, [])[-limit:])

    def register_strategy(self, strategy_key: str) -> None:
        self._strategy_ids.setdefault(strategy_key, uuid4())

    def register_policy(self, policy: RiskPolicy) -> None:
        self._policies.setdefault(policy.policy_key, policy)
        self._policy_ids.setdefault(policy.policy_key, uuid4())

    def load_policy(self, policy_key: str, version: int = 1) -> RiskPolicy:
        policy = self._policies.get(policy_key)
        if policy is None or policy.version != version:
            raise KeyError(f"risk policy not found: {policy_key}@{version}")
        return policy

    def strategy_id(self, strategy_key: str) -> UUID:
        strategy_id = self._strategy_ids.get(strategy_key)
        if strategy_id is None:
            raise KeyError(f"strategy not seeded: {strategy_key}")
        return strategy_id

    def policy_id(self, policy_key: str) -> UUID:
        policy_id = self._policy_ids.get(policy_key)
        if policy_id is None:
            raise KeyError(f"policy not seeded: {policy_key}")
        return policy_id

    def insert_opportunity(self, opportunity: Opportunity) -> UUID:
        self._opportunities.append(opportunity)
        return uuid4()

    def ensure_instrument(self, opportunity: Opportunity) -> None:
        self._instruments.append(
            {"instrument_key": opportunity.instrument_key, "desk": "sports"}
        )

    def catalog_instruments(self, desk: str | None = None) -> list[dict[str, object]]:
        return list(self._instruments)

    def catalog_events(self) -> list[dict[str, object]]:
        return []

    def catalog_policies(self) -> list[dict[str, object]]:
        return [
            {"policy_key": key, "version": policy.version, "tier": policy.tier.value, "params": {}}
            for key, policy in self._policies.items()
        ]

    def catalog_strategies(self) -> list[dict[str, object]]:
        return [{"strategy_key": key, "version": 1} for key in self._strategy_ids]

    def catalog_opportunities(self, limit: int = 50) -> list[dict[str, object]]:
        return [
            {
                "instrument_key": item.instrument_key,
                "strategy_key": item.strategy_key,
                "gross_edge": str(item.gross_edge) if item.gross_edge is not None else None,
                "net_edge": str(item.net_edge) if item.net_edge is not None else None,
            }
            for item in self._opportunities[-limit:]
        ]

    def catalog_decisions(self, limit: int = 50) -> list[dict[str, object]]:
        return list(self._decisions[-limit:])

    def record_decision(self, decision: dict[str, object]) -> None:
        self._decisions.append(decision)

    def catalog_outcomes(self, limit: int = 500) -> list[dict[str, object]]:
        return list(self._outcomes[-limit:])

    def record_outcome(self, outcome: dict[str, object]) -> None:
        self._outcomes.append(outcome)

    def catalog_quality(self, limit: int = 50) -> list[dict[str, object]]:
        return []

    def counts(self) -> dict[str, int]:
        return {
            "market_instruments": len(self._instruments),
            "market_events": 0,
            "market_strategies": len(self._strategy_ids),
            "market_risk_policies": len(self._policies),
            "market_opportunities": len(self._opportunities),
            "market_decisions": 0,
            "market_outcomes": 0,
            "market_data_quality": 0,
        }


class InMemoryJournal:
    """Append-only journal fake with the same contract semantics."""

    def __init__(self) -> None:
        self._entries: list[JournalEntry] = []
        self._amendments: dict[UUID, list[UUID]] = {}
        self._resolved: dict[UUID, UUID] = {}

    def append(
        self,
        record: DecisionRecord,
        *,
        opportunity_id: UUID | None,
        strategy_id: UUID,
        policy_id: UUID,
    ) -> JournalEntry:
        entry = JournalEntry(decision_id=uuid4(), record=record)
        self._entries.append(entry)
        if record.amendment_of is not None:
            self._amendments.setdefault(UUID(record.amendment_of), []).append(entry.decision_id)
        return entry

    def amend(
        self,
        decision_id: UUID,
        *,
        thesis: str,
        counter_thesis: str | None = None,
        confidence: Decimal | None = None,
        estimated_edge: Decimal | None = None,
        invalidation: str | None = None,
        note: str | None = None,
        strategy_id: UUID,
        policy_id: UUID,
        opportunity_id: UUID | None = None,
    ) -> JournalEntry:
        original = self.get(decision_id)
        amended = DecisionRecord(
            opportunity_id=original.record.opportunity_id,
            strategy_key=original.record.strategy_key,
            strategy_version=original.record.strategy_version,
            policy_key=original.record.policy_key,
            policy_version=original.record.policy_version,
            decision_type=original.record.decision_type,
            reason_codes=original.record.reason_codes,
            thesis=thesis,
            counter_thesis=counter_thesis if counter_thesis is not None else original.record.counter_thesis,
            confidence=confidence if confidence is not None else original.record.confidence,
            estimated_edge=estimated_edge if estimated_edge is not None else original.record.estimated_edge,
            cost_estimate=original.record.cost_estimate,
            data_cutoff_timestamp=original.record.data_cutoff_timestamp,
            invalidation=invalidation if invalidation is not None else original.record.invalidation,
            model_version=original.record.model_version,
            amendment_of=str(decision_id),
            note=note,
        )
        return self.append(
            amended,
            opportunity_id=opportunity_id if opportunity_id is not None else (
                UUID(original.record.opportunity_id) if original.record.opportunity_id else None
            ),
            strategy_id=strategy_id,
            policy_id=policy_id,
        )

    def resolve(self, decision_id: UUID, outcome: Outcome) -> UUID:
        outcome_id = uuid4()
        self._resolved[decision_id] = outcome_id
        return outcome_id

    def get(self, decision_id: UUID) -> JournalEntry:
        for entry in self._entries:
            if entry.decision_id == decision_id:
                return entry
        raise KeyError(f"decision not found: {decision_id}")

    def latest(self, limit: int = 50) -> list[JournalEntry]:
        return self._entries[-limit:]

    @property
    def entries(self) -> list[JournalEntry]:
        return list(self._entries)

    def amendments_of(self, decision_id: UUID) -> list[UUID]:
        return list(self._amendments.get(decision_id, []))


def default_policies() -> dict[str, RiskPolicy]:
    from defend_markets.risk import default_risk_policies

    return {policy.policy_key: policy for policy in default_risk_policies()}


class InMemoryForecastStore:
    """In-memory fake for PostgresForecastStore (identity/snapshots/predictions)."""

    def __init__(self) -> None:
        self._participants: dict[int, dict[str, object]] = {}
        self._participant_seq = 0
        self._aliases: dict[tuple[int, str, str], dict[str, object]] = {}
        self._collector_state: dict[str, dict[str, object]] = {}
        self._snapshots: dict[int, dict[str, object]] = {}
        self._snapshot_seq = 0
        self._predictions: dict[UUID, dict[str, object]] = {}
        self._settlements: list[dict[str, object]] = []
        self._shadows: list[dict[str, object]] = []
        self._ledger: list[dict[str, object]] = []

    def participant_by_normalized(self, normalized_name: str) -> list[dict[str, object]]:
        direct = [
            dict(row)
            for row in self._participants.values()
            if row["normalized_name"] == normalized_name
        ]
        if direct:
            return direct
        ids = sorted(
            {pid for (pid, alias_normalized, _provider), _ in self._aliases.items()
             if alias_normalized == normalized_name}
        )
        return [dict(self._participants[pid]) for pid in ids]

    def participant_by_id(self, participant_id: int) -> dict[str, object] | None:
        row = self._participants.get(participant_id)
        return dict(row) if row is not None else None

    def insert_participant(self, *, canonical_name, normalized_name, state, seen_at) -> dict[str, object]:
        self._participant_seq += 1
        row = {
            "participant_id": self._participant_seq,
            "canonical_name": canonical_name,
            "normalized_name": normalized_name,
            "identity_state": state,
            "first_seen": seen_at,
            "last_seen": seen_at,
        }
        self._participants[self._participant_seq] = row
        return dict(row)

    def touch_participant(self, participant_id: int, seen_at) -> None:
        self._participants[participant_id]["last_seen"] = seen_at

    def set_participant_state(self, participant_id: int, state: str) -> None:
        self._participants[participant_id]["identity_state"] = state

    def add_alias(self, *, participant_id: int, alias_name: str, normalized_name: str,
                  provider: str, raw_ref, seen_at) -> None:
        self._aliases[(participant_id, normalized_name, provider)] = {
            "participant_id": participant_id,
            "alias_name": alias_name,
            "normalized_name": normalized_name,
            "provider": provider,
            "raw_ref": raw_ref,
            "first_seen": seen_at,
            "last_seen": seen_at,
        }

    def get_collector_state(self, collector_key: str = "tt_collector") -> dict[str, object] | None:
        row = self._collector_state.get(collector_key)
        return dict(row) if row is not None else None

    def set_collector_state(
        self,
        *,
        collector_key: str = "tt_collector",
        last_cycle_at=None,
        last_scores_poll_at=None,
        last_odds_poll_at=None,
        next_odds_poll_at=None,
        odds_interval_seconds=None,
        quota_status: str | None = None,
        last_quota_remaining=None,
        last_quota_used=None,
        last_quota_last=None,
        last_error=None,
    ) -> None:
        row = self._collector_state.setdefault(collector_key, {})
        row.update(
            {
                "collector_key": collector_key,
                "status": quota_status,
                "last_cycle_at": last_cycle_at,
                "last_quota_remaining": last_quota_remaining,
                "last_quota_used": last_quota_used,
                "last_quota_last": last_quota_last,
                "detail": last_error,
                "last_error": last_error,
            }
        )

    def insert_feature_snapshot(self, *, event_key, prediction_ts, feature_schema_version,
                                feature_code_version, source_observation_ids, payload) -> int:
        self._snapshot_seq += 1
        self._snapshots[self._snapshot_seq] = {
            "snapshot_id": self._snapshot_seq, "event_key": event_key,
            "prediction_ts": prediction_ts,
            "feature_schema_version": feature_schema_version,
            "feature_code_version": feature_code_version,
            "source_observation_ids": list(source_observation_ids or []),
            "payload": payload,
        }
        return self._snapshot_seq

    def feature_snapshot_by_id(self, snapshot_id: int) -> dict[str, object] | None:
        row = self._snapshots.get(snapshot_id)
        return dict(row) if row is not None else None

    def insert_prediction(self, record) -> UUID:
        self._predictions[record.prediction_id] = _asdict(record)
        return record.prediction_id

    def prediction_by_id(self, prediction_id: UUID) -> dict[str, object] | None:
        row = self._predictions.get(prediction_id)
        return dict(row) if row is not None else None

    def predictions_for_event(self, event_key: str, limit: int = 100) -> list[dict[str, object]]:
        rows = [dict(row) for row in self._predictions.values() if row["event_key"] == event_key]
        return list(reversed(rows[-limit:]))

    def catalog_predictions(self, limit: int = 200) -> list[dict[str, object]]:
        rows = list(self._predictions.values())
        return [dict(row) for row in reversed(rows[-limit:])]

    def open_predictions(self) -> list[dict[str, object]]:
        settled = {row["prediction_id"] for row in self._settlements}
        return [
            {"prediction_id": key, "event_key": row["event_key"], "decision": row["decision"]}
            for key, row in self._predictions.items()
            if key not in settled
        ]

    def insert_amendment(self, prediction_id: UUID, reason: str, payload) -> None:
        pass

    def insert_settlement(self, record) -> bool:
        key = (record.prediction_id, record.source_raw_ref)
        if any((row["prediction_id"], row["source_raw_ref"]) == key for row in self._settlements):
            return False
        self._settlements.append({**_asdict(record), "settlement_id": len(self._settlements) + 1})
        return True

    def settlements_for_prediction(self, prediction_id: UUID) -> list[dict[str, object]]:
        return [dict(row) for row in self._settlements if row["prediction_id"] == prediction_id]

    def catalog_settlements(self, limit: int = 500) -> list[dict[str, object]]:
        rows = list(self._settlements)
        return [dict(row) for row in reversed(rows[-limit:])]

    def insert_shadow(self, record) -> None:
        self._shadows.append({**_asdict(record), "shadow_id": len(self._shadows) + 1})

    def shadows_for_event(self, event_key: str) -> list[dict[str, object]]:
        return [dict(row) for row in self._shadows if row["event_key"] == event_key]

    def insert_research_entry(self, entry) -> int:
        self._ledger.append({**_asdict(entry), "entry_id": len(self._ledger) + 1})
        return len(self._ledger)

    def catalog_ledger(self, limit: int = 200) -> list[dict[str, object]]:
        rows = list(self._ledger)
        return [dict(row) for row in reversed(rows[-limit:])]


def _asdict(record) -> dict[str, object]:
    from dataclasses import asdict

    return asdict(record)