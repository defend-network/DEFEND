"""Idempotent settlement service.

Settlement keys on ``(prediction_id, source_raw_ref)`` where the raw ref is
``<event_key>:<result_id>``: a corrected provider result appends a second
settlement row instead of mutating the first. Closing prices are taken from
odds snapshots observed before settlement time; when no such snapshot exists
the closing columns stay NULL (never fabricated). If the prediction's side
cannot be mapped to the result's home/away keys, the prediction is left open
and reported as unmapped.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from defend_markets.feeds import participant_key
from defend_markets.forecast import SettlementRecord
from defend_markets.sports_adapter import SportsDataReader
from defend_markets.store import MarketsStore

MARKET_KEY = "match_winner"
SPORT_KEY = "table_tennis"
LEAGUE_KEY = "table_tennis"
SETTLED_BY = "tt_settlement_service.v1"
PAPER_STAKE = Decimal("1")


@dataclass(frozen=True)
class TtSettlementOutcome:
    prediction_id: UUID
    event_key: str
    settled: bool
    reason: str
    correct: bool | None = None
    raw_ref: str | None = None


class TtSettlementService:
    def __init__(
        self,
        *,
        reader: SportsDataReader,
        store: MarketsStore,
        forecast: Any,
        clock: Any | None = None,
    ) -> None:
        self._reader = reader
        self._store = store
        self._forecast = forecast
        self._clock = clock if clock is not None else (lambda: datetime.now(timezone.utc))

    def settle(self, event_key: str) -> list[TtSettlementOutcome]:
        results = [dict(row) for row in self._store.catalog_tt_results()]
        result = next(
            (row for row in results if str(row.get("event_key") or "") == event_key),
            None,
        )
        if result is None:
            return []
        raw_ref = f"{event_key}:{result['result_id']}"

        now = self._clock()
        outcomes: list[TtSettlementOutcome] = []
        for prediction in self._forecast.predictions_for_event(event_key):
            if str(prediction.get("decision")) != "OPPORTUNITY":
                continue
            prediction_id = UUID(str(prediction["prediction_id"]))
            existing = self._forecast.settlements_for_prediction(prediction_id)
            if any(str(settlement.get("source_raw_ref")) == raw_ref for settlement in existing):
                outcomes.append(
                    TtSettlementOutcome(
                        prediction_id=prediction_id,
                        event_key=event_key,
                        settled=True,
                        reason="already_settled",
                    )
                )
                continue

            side = self._map_side(prediction, result)
            if side is None:
                outcomes.append(
                    TtSettlementOutcome(
                        prediction_id=prediction_id,
                        event_key=event_key,
                        settled=False,
                        reason="unmapped",
                    )
                )
                continue

            correct = side["winner_key"] == side["predicted_key"]
            best_price = Decimal(str(prediction.get("best_price_a") or prediction.get("best_price_b") or 0))
            paper_pnl_gross = (
                (best_price - PAPER_STAKE) * PAPER_STAKE if correct else -PAPER_STAKE
            )
            closing = self._closing_prices(event_key, now)
            closing_p = (
                closing.get(side["predicted_selection"]) if closing is not None else None
            )
            consensus_p = (
                Decimal(str(prediction.get("consensus_p_a")))
                if side["predicted_is_a"]
                else Decimal(str(prediction.get("consensus_p_b")))
            )
            clv = closing_p - consensus_p if closing_p is not None and consensus_p is not None else None

            self._forecast.insert_settlement(
                SettlementRecord(
                    prediction_id=prediction_id,
                    source_raw_ref=raw_ref,
                    settlement_ts=now,
                    winner_participant_key=side["winner_key"],
                    correct=correct,
                    residual=None,
                    paper_stake=PAPER_STAKE,
                    paper_pnl_gross=paper_pnl_gross,
                    paper_costs=None,
                    paper_pnl_net=paper_pnl_gross,
                    closing_market_p=closing_p,
                    closing_best_price=None,
                    clv=clv,
                    settled_by=SETTLED_BY,
                )
            )
            outcomes.append(
                TtSettlementOutcome(
                    prediction_id=prediction_id,
                    event_key=event_key,
                    settled=True,
                    reason="settled",
                    correct=correct,
                    raw_ref=raw_ref,
                )
            )
        return outcomes

    # ------------------------------------------------------------------
    def _map_side(
        self, prediction: dict[str, object], result: dict[str, object]
    ) -> dict[str, object] | None:
        home_key = str(result.get("home_participant_key") or "")
        away_key = str(result.get("away_participant_key") or "")
        winner_key = (
            home_key
            if int(result.get("home_score") or 0) > int(result.get("away_score") or 0)
            else away_key
        )
        key_a = participant_key(LEAGUE_KEY, str(prediction.get("player_a_name_at_prediction") or ""))
        key_b = participant_key(LEAGUE_KEY, str(prediction.get("player_b_name_at_prediction") or ""))
        if key_a == home_key and key_b == away_key:
            predicted_key = key_a
            predicted_is_a = True
            predicted_selection = "home"
        elif key_a == away_key and key_b == home_key:
            predicted_key = key_a
            predicted_is_a = True
            predicted_selection = "away"
        else:
            return None
        return {
            "winner_key": winner_key,
            "predicted_key": predicted_key,
            "predicted_is_a": predicted_is_a,
            "predicted_selection": predicted_selection,
        }

    def _closing_prices(self, event_key: str, before: datetime) -> dict[str, Decimal] | None:
        quotes = self._reader.odds_history(event_key, MARKET_KEY, before=before)
        groups: dict[datetime, dict[str, Decimal]] = {}
        for quote in quotes:
            if not quote.decimal_odds:
                continue
            try:
                probability = Decimal("1") / quote.decimal_odds
            except (ValueError, ArithmeticError, ZeroDivisionError):
                continue
            observed = quote.provenance.observed_at if quote.provenance is not None else None
            if observed is None:
                continue
            group = groups.setdefault(observed, {})
            group.setdefault(quote.selection_key, probability)
        if not groups:
            return None
        newest = max(groups)
        prices = groups[newest]
        if len(prices) < 2:
            return None
        total = sum(prices.values(), Decimal("0"))
        if total == 0:
            return None
        return {key: (value / total) for key, value in prices.items()}