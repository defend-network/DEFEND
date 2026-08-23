"""Pre-outcome prediction, settlement and shadow-baseline records.

Prediction records are immutable by construction: the store only ever
INSERTs them, corrections are append-only amendments, and settlements key
on ``(prediction_id, source_raw_ref)`` so a corrected provider result
produces a second settlement row instead of mutating the first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from defend_markets.domain import _require_optional_decimal, _require_optional_datetime, _require_text


@dataclass(frozen=True)
class PredictionRecord:
    prediction_id: UUID
    created_ts: datetime
    event_key: str
    sport_key: str
    player_a_name_at_prediction: str
    player_b_name_at_prediction: str
    decision: str
    reason_codes: tuple[str, ...] = ()
    model_id: str = "tt_elo"
    model_version: str = "0.0.0"
    model_p_a: Decimal | None = None
    model_p_b: Decimal | None = None
    model_uncertainty: Decimal | None = None
    market_p_a: Decimal | None = None
    market_p_b: Decimal | None = None
    consensus_p_a: Decimal | None = None
    consensus_p_b: Decimal | None = None
    best_price_a: Decimal | None = None
    best_price_b: Decimal | None = None
    overround: Decimal | None = None
    book_count: int | None = None
    edge_gross: Decimal | None = None
    edge_net: Decimal | None = None
    provider_event_id: str | None = None
    player_a_id: int | None = None
    player_b_id: int | None = None
    feature_snapshot_id: int | None = None
    market_method_version: str = "market_state.v1"
    cost_model_version: str | None = None
    data_age_seconds: Decimal | None = None
    provider_health: str | None = None
    identity_state: str | None = None
    strategy_id: str = ""
    strategy_version: int = 1
    strategy_lifecycle: str = "EXPERIMENTAL"
    risk_policy_version: int = 1
    journal_ref: UUID | None = None

    def __post_init__(self) -> None:
        _require_text("event_key", self.event_key)
        _require_text("player_a_name_at_prediction", self.player_a_name_at_prediction)
        _require_text("player_b_name_at_prediction", self.player_b_name_at_prediction)
        if self.decision not in ("OPPORTUNITY", "NO_ACTION"):
            raise ValueError("decision must be OPPORTUNITY or NO_ACTION")
        object.__setattr__(self, "created_ts", _require_optional_datetime("created_ts", self.created_ts))
        for name in (
            "model_p_a",
            "model_p_b",
            "model_uncertainty",
            "market_p_a",
            "market_p_b",
            "consensus_p_a",
            "consensus_p_b",
            "best_price_a",
            "best_price_b",
            "overround",
            "edge_gross",
            "edge_net",
            "data_age_seconds",
        ):
            object.__setattr__(self, name, _require_optional_decimal(name, getattr(self, name)))
        if self.model_p_a is not None:
            if not (Decimal("0") <= self.model_p_a <= Decimal("1")):
                raise ValueError("model_p_a must be a probability")
        if self.model_p_b is not None and self.model_p_a is not None:
            if abs((self.model_p_a + self.model_p_b) - Decimal("1")) > Decimal("0.0001"):
                raise ValueError("model probabilities must sum to 1")


@dataclass(frozen=True)
class SettlementRecord:
    prediction_id: UUID
    source_raw_ref: str
    settlement_ts: datetime
    winner_participant_key: str
    correct: bool
    settled_by: str
    residual: Decimal | None = None
    paper_stake: Decimal | None = None
    paper_pnl_gross: Decimal | None = None
    paper_costs: Decimal | None = None
    paper_pnl_net: Decimal | None = None
    closing_market_p: Decimal | None = None
    closing_best_price: Decimal | None = None
    clv: Decimal | None = None

    def __post_init__(self) -> None:
        _require_text("source_raw_ref", self.source_raw_ref)
        _require_text("winner_participant_key", self.winner_participant_key)
        _require_text("settled_by", self.settled_by)
        object.__setattr__(self, "settlement_ts", _require_optional_datetime("settlement_ts", self.settlement_ts))


@dataclass(frozen=True)
class ShadowRecord:
    event_key: str
    created_ts: datetime
    model_id: str
    model_version: str
    strategy_id: str
    strategy_version: int
    prediction_id: UUID | None = None
    market_p_a: Decimal | None = None
    market_p_b: Decimal | None = None
    elo_p_a: Decimal | None = None
    elo_p_b: Decimal | None = None
    naive_form_p_a: Decimal | None = None
    naive_form_p_b: Decimal | None = None


@dataclass(frozen=True)
class ResearchEntry:
    hypothesis: str
    change: str
    expected_mechanism: str
    decision: str
    model_id: str | None = None
    model_version: str | None = None
    strategy_id: str | None = None
    strategy_version: int | None = None
    evaluation_period: str | None = None
    results: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.decision not in ("KEEP", "REJECT", "RETEST"):
            raise ValueError("research decision must be KEEP, REJECT or RETEST")