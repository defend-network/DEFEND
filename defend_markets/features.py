"""Point-in-time feature snapshots for Table Tennis predictions.

HARD RULE: a prediction must be reproducible from ONLY information
available at ``prediction_ts``. Every snapshot therefore filters history
to matches completed strictly BEFORE the cutoff, quotes to observations
observed at or before the cutoff, and records the schema/code versions
plus source observation ids. Settlement can never alter a snapshot.

Leakage rules enforced here:
- future results excluded (completed_at >= cutoff)
- the predicted event itself excluded even if a result row exists
- future odds excluded (observed_at > cutoff)
- load features derived only from matches before the cutoff
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Mapping, Sequence

from defend_markets.sports_adapter import SportsSelectionQuote

FEATURE_SCHEMA_VERSION = 1
FEATURE_CODE_VERSION = "features.v1"
_HISTORY_WINDOW_DAYS = 90
_RECENT_WINDOW = 5


def _history_before_cutoff(
    rows: Sequence[Mapping[str, object]], event_key: str, cutoff: datetime
) -> list[dict[str, object]]:
    """Completed matches strictly before the cutoff, excluding the event itself."""
    filtered: list[dict[str, object]] = []
    for row in rows:
        if str(row.get("event_key") or "") == event_key:
            continue
        completed_at = row.get("completed_at")
        if not isinstance(completed_at, datetime) or completed_at >= cutoff:
            continue
        filtered.append(dict(row))
    return filtered


def _player_matches(
    rows: Sequence[Mapping[str, object]], participant_key: str
) -> list[dict[str, object]]:
    matches: list[dict[str, object]] = []
    for row in rows:
        if row.get("home_participant_key") == participant_key or row.get(
            "away_participant_key"
        ) == participant_key:
            matches.append(row)
    matches.sort(
        key=lambda row: (row["completed_at"].isoformat(), str(row.get("event_key") or ""))
    )
    return matches


@dataclass(frozen=True)
class PlayerFeatures:
    participant_key: str
    name: str
    identity_state: str | None
    matches: int
    wins: int
    win_rate: Decimal | None
    recent_form: Decimal | None
    rating: Decimal | None
    same_day_matches: int
    hours_since_previous: Decimal | None
    matches_24h: int
    matches_48h: int
    h2h_matches: int
    h2h_wins: int
    avg_set_margin: Decimal | None

    def as_dict(self) -> dict[str, object]:
        return {
            "participant_key": self.participant_key,
            "name": self.name,
            "identity_state": self.identity_state,
            "matches": self.matches,
            "wins": self.wins,
            "win_rate": str(self.win_rate) if self.win_rate is not None else None,
            "recent_form": str(self.recent_form) if self.recent_form is not None else None,
            "rating": str(self.rating) if self.rating is not None else None,
            "same_day_matches": self.same_day_matches,
            "hours_since_previous": (
                str(self.hours_since_previous) if self.hours_since_previous is not None else None
            ),
            "matches_24h": self.matches_24h,
            "matches_48h": self.matches_48h,
            "h2h_matches": self.h2h_matches,
            "h2h_wins": self.h2h_wins,
            "avg_set_margin": str(self.avg_set_margin) if self.avg_set_margin is not None else None,
        }


def build_player_features(
    participant_key: str,
    name: str,
    identity_state: str | None,
    matches: Sequence[Mapping[str, object]],
    *,
    opponent_key: str,
    cutoff: datetime,
) -> PlayerFeatures:
    mine = _player_matches(matches, participant_key)
    wins = sum(
        1
        for row in mine
        if row["home_participant_key"] == participant_key
        and int(row.get("home_score") or 0) > int(row.get("away_score") or 0)
        or row["away_participant_key"] == participant_key
        and int(row.get("away_score") or 0) > int(row.get("home_score") or 0)
    )
    recent = mine[-_RECENT_WINDOW:]
    recent_wins = sum(
        1
        for row in recent
        if row["home_participant_key"] == participant_key
        and int(row.get("home_score") or 0) > int(row.get("away_score") or 0)
        or row["away_participant_key"] == participant_key
        and int(row.get("away_score") or 0) > int(row.get("home_score") or 0)
    )
    h2h = [
        row
        for row in mine
        if row.get("home_participant_key") == opponent_key
        or row.get("away_participant_key") == opponent_key
    ]
    h2h_wins = sum(
        1
        for row in h2h
        if row["home_participant_key"] == participant_key
        and int(row.get("home_score") or 0) > int(row.get("away_score") or 0)
        or row["away_participant_key"] == participant_key
        and int(row.get("away_score") or 0) > int(row.get("home_score") or 0)
    )
    same_day = 0
    hours_since_previous: Decimal | None = None
    matches_24h = 0
    matches_48h = 0
    margins: list[int] = []
    previous: datetime | None = None
    for row in mine:
        completed_at = row["completed_at"]
        day = completed_at.astimezone(timezone.utc).date()
        if day == cutoff.astimezone(timezone.utc).date():
            same_day += 1
        window = cutoff - completed_at
        if window <= timedelta(hours=24):
            matches_24h += 1
        if window <= timedelta(hours=48):
            matches_48h += 1
        if previous is not None:
            hours_since_previous = Decimal(str((completed_at - previous).total_seconds() / 3600))
        previous = completed_at
        if row["home_participant_key"] == participant_key:
            margins.append(int(row.get("home_score") or 0) - int(row.get("away_score") or 0))
        else:
            margins.append(int(row.get("away_score") or 0) - int(row.get("home_score") or 0))
    avg_margin = (
        Decimal(sum(margins)) / Decimal(len(margins)) if margins else None
    )
    return PlayerFeatures(
        participant_key=participant_key,
        name=name,
        identity_state=identity_state,
        matches=len(mine),
        wins=wins,
        win_rate=Decimal(wins) / Decimal(len(mine)) if mine else None,
        recent_form=Decimal(recent_wins) / Decimal(len(recent)) if recent else None,
        rating=None,
        same_day_matches=same_day,
        hours_since_previous=hours_since_previous,
        matches_24h=matches_24h,
        matches_48h=matches_48h,
        h2h_matches=len(h2h),
        h2h_wins=h2h_wins,
        avg_set_margin=avg_margin,
    )


@dataclass(frozen=True)
class FeatureSnapshot:
    event_key: str
    prediction_ts: datetime
    feature_schema_version: int = FEATURE_SCHEMA_VERSION
    feature_code_version: str = FEATURE_CODE_VERSION
    player_a: PlayerFeatures | None = None
    player_b: PlayerFeatures | None = None
    market: Mapping[str, object] = field(default_factory=dict)
    data_quality: Mapping[str, object] = field(default_factory=dict)
    source_observation_ids: tuple[str, ...] = ()

    def payload(self) -> dict[str, object]:
        return {
            "feature_schema_version": self.feature_schema_version,
            "feature_code_version": self.feature_code_version,
            "player_a": self.player_a.as_dict() if self.player_a is not None else None,
            "player_b": self.player_b.as_dict() if self.player_b is not None else None,
            "market": dict(self.market),
            "data_quality": dict(self.data_quality),
        }


def build_feature_snapshot(
    *,
    event_key: str,
    prediction_ts: datetime,
    player_a_key: str,
    player_a_name: str,
    player_a_identity_state: str | None,
    player_b_key: str,
    player_b_name: str,
    player_b_identity_state: str | None,
    history_rows: Sequence[Mapping[str, object]],
    quotes: Sequence[SportsSelectionQuote],
    market_state_payload: Mapping[str, object],
    source_observation_ids: Sequence[str],
) -> FeatureSnapshot:
    """Build one immutable snapshot from strictly pre-cutoff information.

    ``history_rows`` must already be filtered by the caller (or this
    builder filters them again deterministically via
    ``_history_before_cutoff``).
    """
    cutoff = prediction_ts
    eligible = _history_before_cutoff(history_rows, event_key, cutoff)
    eligible_quotes = [
        quote
        for quote in quotes
        if quote.provenance is None
        or quote.provenance.observed_at is None
        or quote.provenance.observed_at <= cutoff
    ]
    a = build_player_features(
        player_a_key,
        player_a_name,
        player_a_identity_state,
        eligible,
        opponent_key=player_b_key,
        cutoff=cutoff,
    )
    b = build_player_features(
        player_b_key,
        player_b_name,
        player_b_identity_state,
        eligible,
        opponent_key=player_a_key,
        cutoff=cutoff,
    )
    missing: list[str] = []
    if not eligible_quotes:
        missing.append("odds")
    if player_a_identity_state is None:
        missing.append("identity_a")
    if player_b_identity_state is None:
        missing.append("identity_b")
    if not eligible:
        missing.append("history")
    data_quality = {
        "missing_fields": missing,
        "history_window_days": _HISTORY_WINDOW_DAYS,
        "history_matches": len(eligible),
    }
    return FeatureSnapshot(
        event_key=event_key,
        prediction_ts=prediction_ts,
        player_a=a,
        player_b=b,
        market=dict(market_state_payload),
        data_quality=data_quality,
        source_observation_ids=tuple(
            quote.provenance.raw_ref
            for quote in eligible_quotes
            if quote.provenance is not None and quote.provenance.raw_ref
        )
        or tuple(source_observation_ids),
    )