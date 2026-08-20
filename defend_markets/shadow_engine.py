"""Phase D shadow engine: one cycle = discovery + odds poll + gate + M5 +
ruler rows + settlement. SHADOW ONLY.

The engine is deterministic and idempotent: every persisted row is keyed by a
natural unique key, so restarts never duplicate observations. Raw provider
payloads are stored immutable (sha256-keyed) before any normalization.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol

from defend_integrations.matching import compact_name
from defend_markets.m5_live import FrozenM5, M5Match, M5StateBuilder, MODEL_ID
from defend_markets.shadow import (
    INTERMEDIATE,
    LAST_VALID_PREMATCH,
    OPEN,
    POST_COMMENCE,
    RulerRow,
    build_evaluation_rows,
    build_ruler_row,
    classify_observation,
    forward_fixtures_from_oddspapi,
    last_valid_prematch,
    parse_oddspapi_odds,
    poll_delay_for,
    schedule_label_for,
)
from defend_markets.shadow_store import ShadowStore


class OddsClient(Protocol):
    def fetch_fixtures(self, *, from_iso: str, to_iso: str) -> tuple[int | None, Any]:
        ...

    def fetch_odds(self, provider_event_id: str) -> tuple[int | None, Any]:
        ...


class SettledResult(Protocol):
    def __call__(self, canonical_event_id: str) -> dict[str, Any] | None:
        ...


@dataclass(frozen=True)
class ShadowConfig:
    providers: tuple[str, ...] = ("oddspapi",)
    discovery_window_hours: float = 72.0
    discovery_interval_seconds: float = 1800.0
    max_poll_events_per_cycle: int = 40
    m5_min_games: int = 5
    price_min: float = 1.01


@dataclass
class CycleMetrics:
    api_requests: int = 0
    api_errors: int = 0
    rate_limit_events: int = 0
    truncated_responses: int = 0
    events_discovered: int = 0
    events_matched: int = 0
    ambiguous_events: int = 0
    events_with_odds: int = 0
    prematch_observations: int = 0
    postcommence_observations: int = 0
    m5_predictions: int = 0
    m5_insufficient: int = 0
    ruler_rows: int = 0
    settlements: int = 0
    bookmakers_seen: set[str] = field(default_factory=set)
    raw_evidence_rows: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_requests": self.api_requests,
            "api_errors": self.api_errors,
            "rate_limit_events": self.rate_limit_events,
            "truncated_responses": self.truncated_responses,
            "events_discovered": self.events_discovered,
            "events_matched": self.events_matched,
            "ambiguous_events": self.ambiguous_events,
            "events_with_odds": self.events_with_odds,
            "prematch_observations": self.prematch_observations,
            "postcommence_observations": self.postcommence_observations,
            "m5_predictions": self.m5_predictions,
            "m5_insufficient": self.m5_insufficient,
            "ruler_rows": self.ruler_rows,
            "settlements": self.settlements,
            "bookmakers_seen": sorted(self.bookmakers_seen),
        }


class ShadowEngine:
    def __init__(
        self,
        *,
        store: ShadowStore,
        m5: FrozenM5,
        client: OddsClient,
        settled: SettledResult | None = None,
        config: ShadowConfig | None = None,
        now: Callable[[], datetime] | None = None,
        provider_label: str = "oddspapi",
    ) -> None:
        self._store = store
        self._m5 = m5
        self._client = client
        self._settled = settled or (lambda _key: None)
        self._config = config or ShadowConfig()
        self._provider_label = provider_label
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._state_builder: M5StateBuilder | None = None
        self._last_discovery_at: datetime | None = None

    def set_state_builder(self, builder: M5StateBuilder | None) -> None:
        """Inject the frozen-state replay (matches strictly before cycle)."""
        self._state_builder = builder

    # ------------------------------------------------------------------ #
    # P0 forward discovery
    # ------------------------------------------------------------------ #
    def _discovery_due(self, now: datetime) -> bool:
        if self._last_discovery_at is None:
            return True
        return (now - self._last_discovery_at).total_seconds() >= (
            self._config.discovery_interval_seconds
        )

    def _canonicalize(
        self,
        fixture: Any,
        *,
        canonical_events: dict[str, dict[str, Any]],
    ) -> tuple[str | None, str]:
        from defend_integrations.matching import match_event

        match = match_event(
            provider_event_id=fixture.provider_event_id,
            provider_prefix=fixture.provider,
            participants=[fixture.player_a, fixture.player_b],
            competition=fixture.competition,
            commence_at=fixture.scheduled_commence.isoformat().replace("+00:00", "Z"),
            canonical_events=list(canonical_events.values()),
            window_hours=3.0,
        )
        return match.matched_event_key, match.level.value

    def discover(self, *, canonical_events: dict[str, dict[str, Any]]) -> CycleMetrics:
        metrics = CycleMetrics()
        now = self._now()
        if not self._discovery_due(now):
            return metrics
        from_iso = now.isoformat().replace("+00:00", "Z")
        to_iso = (now + timedelta(hours=self._config.discovery_window_hours)).isoformat().replace("+00:00", "Z")
        status, payload, truncated = self._client.fetch_fixtures(from_iso=from_iso, to_iso=to_iso)
        metrics.api_requests += 1
        if truncated:
            metrics.truncated_responses += 1
        if status is not None and status >= 400:
            metrics.api_errors += 1
            if status == 429:
                metrics.rate_limit_events += 1
            self._last_discovery_at = now
            return metrics
        self._record_raw(self._provider_label, "fixtures", now, status, payload, metrics)
        fixtures = forward_fixtures_from_oddspapi(payload, provider=self._provider_label)
        for fixture in fixtures:
            canonical_key, match_level = self._canonicalize(
                fixture, canonical_events=canonical_events
            )
            if match_level == "AMBIGUOUS":
                metrics.ambiguous_events += 1
            if canonical_key:
                metrics.events_matched += 1
            self._store.upsert_forward_event(
                provider=fixture.provider,
                provider_event_id=fixture.provider_event_id,
                canonical_event_id=canonical_key,
                competition=fixture.competition,
                player_a_key=compact_name(fixture.player_a),
                player_b_key=compact_name(fixture.player_b),
                player_a_name=fixture.player_a,
                player_b_name=fixture.player_b,
                scheduled_commence=fixture.scheduled_commence,
                match_level=match_level,
                discovered_at=now,
            )
            metrics.events_discovered += 1
        self._last_discovery_at = now
        return metrics

    # ------------------------------------------------------------------ #
    # P1 odds polling + P2 gate
    # ------------------------------------------------------------------ #
    def _due_events(self, now: datetime) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for event in self._store.list_forward_events():
            if event["state"] not in ("UPCOMING", "LIVE"):
                continue
            if event["match_level"] == "AMBIGUOUS":
                continue
            commence = event["scheduled_commence"]
            if commence < now - timedelta(hours=2):
                continue  # finished long ago; settlement path owns it
            last_poll = event.get("last_odds_poll_at")
            delay = poll_delay_for((commence - now).total_seconds(), now=now)
            if last_poll is None or (now - last_poll).total_seconds() >= delay:
                events.append(event)
            if len(events) >= self._config.max_poll_events_per_cycle:
                break
        return events

    def _side_for(self, participant_key: str, event: dict[str, Any]) -> str | None:
        a = compact_name(event.get("player_a_name") or "")
        b = compact_name(event.get("player_b_name") or "")
        key = compact_name(participant_key)
        if key == a:
            return "A"
        if key == b:
            return "B"
        return None

    def poll_odds(self) -> CycleMetrics:
        metrics = CycleMetrics()
        now = self._now()
        for event in self._due_events(now):
            status, payload, truncated = self._client.fetch_odds(event["provider_event_id"])
            metrics.api_requests += 1
            if truncated:
                metrics.truncated_responses += 1
            if status is not None and status >= 400:
                metrics.api_errors += 1
                if status == 429:
                    metrics.rate_limit_events += 1
                continue
            self._record_raw(
                "oddspapi", f"odds:{event['provider_event_id']}", now, status, payload, metrics
            )
            self._ingest_odds(event, payload, now, metrics)
            self._store.set_last_odds_poll(int(event["forward_event_id"]), now)
        return metrics

    def _ingest_odds(
        self, event: dict[str, Any], payload: Any, now: datetime, metrics: CycleMetrics
    ) -> None:
        prices = parse_oddspapi_odds(
            payload,
            provider_event_id=event["provider_event_id"],
            ingested_at=now,
        )
        if not prices:
            return
        evidence_ref = self._evidence_sha(payload)
        forward_event_id = int(event["forward_event_id"])
        canonical_id = event.get("canonical_event_id")
        commence = event["scheduled_commence"]
        existing = {
            o["observation_id"]: o
            for o in self._store.list_observations_for_event_id(forward_event_id)
        }
        first_prematch = not any(
            o["observation_class"] != POST_COMMENCE for o in existing.values()
        )
        events_with_odds = False
        for price in prices:
            side = self._side_for(price.participant_key, event)
            if side is None:
                continue
            observed_at = now
            obs_class = classify_observation(
                observed_at, commence, is_first_prematch=first_prematch
            )
            observation_id = self._store.insert_observation(
                forward_event_id=forward_event_id,
                canonical_event_id=canonical_id or "",
                provider=event["provider"],
                provider_event_id=event["provider_event_id"],
                bookmaker=price.bookmaker,
                market=price.market,
                provider_market_id=price.provider_market_id,
                side=side,
                participant_key=price.participant_key,
                price=price.price,
                observed_at=observed_at,
                scheduled_commence=commence,
                raw_provenance="oddspapi:/v4/odds",
                raw_evidence_ref=f"tt_raw_evidence:{evidence_ref}",
                observation_class=obs_class,
            )
            if observation_id not in existing:
                if obs_class == POST_COMMENCE:
                    metrics.postcommence_observations += 1
                else:
                    metrics.prematch_observations += 1
                    first_prematch = False
                events_with_odds = True
                metrics.bookmakers_seen.add(price.bookmaker)
        if events_with_odds and canonical_id:
            metrics.events_with_odds += 1

    @staticmethod
    def _evidence_sha(payload: Any) -> str:
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

    # ------------------------------------------------------------------ #
    # P2 freeze of LAST_VALID_PREMATCH at commence crossing
    # ------------------------------------------------------------------ #
    def freeze_last_valid_prematch(self) -> int:
        now = self._now()
        promoted = 0
        for event in self._store.list_forward_events():
            if event["state"] not in ("UPCOMING", "LIVE"):
                continue
            if event.get("commence_crossed_at"):
                continue
            if event["scheduled_commence"] <= now:
                self._store.set_commence_crossed(int(event["forward_event_id"]), now)
                canonical_id = event.get("canonical_event_id")
                if not canonical_id:
                    continue
                observations = self._store.list_observations(canonical_id)
                last = last_valid_prematch(observations)
                if last is not None:
                    self._store.promote_last_valid_prematch(
                        canonical_id, int(last["observation_id"])
                    )
                    promoted += 1
        return promoted

    # ------------------------------------------------------------------ #
    # P3 M5 live inference (frozen weights; strictly-before-now state)
    # ------------------------------------------------------------------ #
    def infer_m5(self) -> CycleMetrics:
        metrics = CycleMetrics()
        now = self._now()
        builder = self._state_builder
        if builder is None:
            return metrics
        for event in self._store.list_forward_events():
            canonical_id = event.get("canonical_event_id")
            if not canonical_id or event["match_level"] == "AMBIGUOUS":
                continue
            if self._store.m5_prediction(canonical_id) is not None:
                continue
            p_a, availability, features = self._m5.predict(
                builder,
                event["player_a_key"],
                event["player_b_key"],
                min(now, event["scheduled_commence"]),
                min_games=self._config.m5_min_games,
            )
            created = self._store.insert_m5_prediction(
                canonical_event_id=canonical_id,
                player_a_key=event["player_a_key"],
                player_b_key=event["player_b_key"],
                model_id=MODEL_ID,
                model_version=self._m5.model_version,
                feature_snapshot_id=self._m5.feature_snapshot_id,
                generated_at=now,
                p_a=round(p_a, 6),
                p_b=round(1 - p_a, 6),
                availability=availability,
                feature_payload=features,
            )
            if created:
                if availability == "AVAILABLE":
                    metrics.m5_predictions += 1
                else:
                    metrics.m5_insufficient += 1
        return metrics

    # ------------------------------------------------------------------ #
    # P4 ruler rows
    # ------------------------------------------------------------------ #
    def build_ruler_rows(self) -> CycleMetrics:
        metrics = CycleMetrics()
        now = self._now()
        for event in self._store.list_forward_events():
            canonical_id = event.get("canonical_event_id")
            if not canonical_id:
                continue
            prediction = self._store.m5_prediction(canonical_id)
            if prediction is None:
                continue
            m5_p_a = float(prediction["p_a"])
            existing_ids = {
                int(r["observation_id"]) for r in self._store.list_ruler_rows(canonical_id)
            }
            observations = self._store.list_observations(canonical_id)
            by_ts: dict[datetime, dict[str, Any]] = {}
            for obs in observations:
                if obs["observation_class"] == POST_COMMENCE:
                    continue
                by_ts.setdefault(obs["observed_at"], {})[obs["side"]] = obs
            for observed_at, pair in by_ts.items():
                if "A" not in pair or "B" not in pair:
                    continue
                obs_a = pair["A"]
                row = build_ruler_row(
                    observation_id=int(obs_a["observation_id"]),
                    canonical_event_id=canonical_id,
                    observation_class=obs_a["observation_class"],
                    price_a=float(obs_a["price"]),
                    price_b=float(pair["B"]["price"]),
                    m5_p_a=m5_p_a,
                    observed_at=observed_at,
                    commence_at=event["scheduled_commence"],
                    now=now,
                )
                if row.observation_id in existing_ids:
                    continue
                self._store.insert_ruler_row(row, raw={})
                metrics.ruler_rows += 1
        return metrics

    # ------------------------------------------------------------------ #
    # P5 settlement
    # ------------------------------------------------------------------ #
    def settle(self) -> CycleMetrics:
        metrics = CycleMetrics()
        now = self._now()
        for event in self._store.list_forward_events():
            canonical_id = event.get("canonical_event_id")
            if not canonical_id or event["state"] == "SETTLED":
                continue
            if event["state"] != "LIVE" and event["scheduled_commence"] > now:
                continue
            result = self._settled(canonical_id)
            if result is None:
                continue
            prediction = self._store.m5_prediction(canonical_id)
            if prediction is None:
                continue
            ruler_rows = self._store.list_ruler_rows(canonical_id)
            if not ruler_rows:
                continue
            actual = float(result["actual"])
            rows = build_evaluation_rows(
                canonical_event_id=canonical_id,
                result_id=int(result["result_id"]),
                settled_at=now,
                ruler_rows=ruler_rows,
                m5_p_a=float(prediction["p_a"]),
                actual=actual,
            )
            for row in rows:
                self._store.insert_evaluation_row(
                    {
                        "canonical_event_id": row.canonical_event_id,
                        "result_id": row.result_id,
                        "settled_at": row.settled_at,
                        "model_id": prediction["model_id"],
                        "model_version": prediction["model_version"],
                        "reference_class": row.reference_class,
                        "m5_p_a": row.m5_p_a,
                        "market_no_vig_p_a": row.market_no_vig_p_a,
                        "actual": row.actual,
                    }
                )
                metrics.settlements += 1
            self._store.set_state(int(event["forward_event_id"]), "SETTLED")
        return metrics

    # ------------------------------------------------------------------ #
    def _record_raw(
        self,
        provider: str,
        endpoint: str,
        fetched_at: datetime,
        status_code: int | None,
        payload: Any,
        metrics: CycleMetrics,
    ) -> None:
        sha = self._evidence_sha(payload)
        if self._store.record_raw_evidence(
            evidence_sha256=sha,
            provider=provider,
            endpoint=endpoint,
            fetched_at=fetched_at,
            status_code=status_code,
            payload=payload,
        ):
            metrics.raw_evidence_rows += 1
        return sha

    def run_cycle(
        self,
        *,
        canonical_events: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """One full cycle: discovery + odds + gate + M5 + ruler + settlement."""
        now = self._now()
        metrics: dict[str, Any] = {
            "cycle_at": now.isoformat().replace("+00:00", "Z"),
            "discovery": self.discover(canonical_events=canonical_events).to_dict(),
            "odds": self.poll_odds().to_dict(),
            "freeze_promotions": self.freeze_last_valid_prematch(),
            "m5": self.infer_m5().to_dict(),
            "ruler": self.build_ruler_rows().to_dict(),
            "settlement": self.settle().to_dict(),
        }
        return metrics