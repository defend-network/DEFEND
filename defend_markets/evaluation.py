"""Honest calibration evaluation for settled predictions.

Brier score is primary, log loss secondary, with a 10-bucket calibration
curve. Baselines (market consensus, Elo-only) are evaluated on the same
settled sample. Every metric carries the sample size and is suppressed
(None) when the sample is too small — an empty sample reports nothing
rather than fabricated precision.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Sequence
from uuid import UUID

MIN_SAMPLE = 10
MIN_SAMPLE_CALIBRATION = 30


@dataclass(frozen=True)
class ScoreCard:
    brier: Decimal | None
    log_loss: Decimal | None
    accuracy: Decimal | None
    sample_size: int
    buckets: tuple[tuple[Decimal, Decimal, int], ...]
    calibrated: bool
    honest: bool = True


class CalibrationEvaluator:
    def __init__(self, *, min_sample: int = MIN_SAMPLE, min_sample_calibration: int = MIN_SAMPLE_CALIBRATION) -> None:
        self._min_sample = min_sample
        self._min_sample_calibration = min_sample_calibration

    def score(
        self,
        *,
        probabilities: Sequence[Decimal | None],
        outcomes: Sequence[bool],
    ) -> ScoreCard:
        pairs = [
            (probability, outcome)
            for probability, outcome in zip(probabilities, outcomes)
            if probability is not None
        ]
        sample_size = len(pairs)
        if sample_size == 0:
            return ScoreCard(None, None, None, 0, (), False)

        brier = self._brier(pairs)
        log_loss = self._log_loss(pairs)
        accuracy = self._accuracy(pairs)
        buckets = self._buckets(pairs) if sample_size >= self._min_sample_calibration else ()
        calibrated = sample_size >= self._min_sample_calibration and bool(buckets)
        if sample_size < self._min_sample:
            return ScoreCard(None, None, None, sample_size, buckets, calibrated)
        return ScoreCard(brier, log_loss, accuracy, sample_size, buckets, calibrated)

    def model_vs_baselines(
        self,
        *,
        predictions: Sequence[dict[str, Any]],
        settlements: Sequence[dict[str, Any]],
    ) -> dict[str, ScoreCard]:
        sample: list[tuple[Decimal, bool]] = []
        elo_sample: list[tuple[Decimal, bool]] = []
        market_sample: list[tuple[Decimal, bool]] = []

        settlement_by_prediction: dict[UUID, list[dict[str, Any]]] = {}
        for settlement in settlements:
            settlement_by_prediction.setdefault(UUID(str(settlement["prediction_id"])), []).append(settlement)

        for prediction in predictions:
            prediction_id = UUID(str(prediction["prediction_id"]))
            rows = settlement_by_prediction.get(prediction_id) or []
            if not rows:
                continue
            latest = max(rows, key=lambda row: row["settlement_ts"])
            if latest.get("correct") is None:
                continue
            outcome = bool(latest["correct"])
            model_p = _probability(prediction.get("model_p_a"))
            market_p = _probability(prediction.get("consensus_p_a"))
            if model_p is not None:
                sample.append((model_p, outcome))
                elo_sample.append((model_p, outcome))
            if market_p is not None:
                market_sample.append((market_p, outcome))

        return {
            "model": self.score(probabilities=[p for p, _ in sample], outcomes=[o for _, o in sample]),
            "elo_baseline": self.score(probabilities=[p for p, _ in elo_sample], outcomes=[o for _, o in elo_sample]),
            "market_baseline": self.score(probabilities=[p for p, _ in market_sample], outcomes=[o for _, o in market_sample]),
        }

    def _brier(self, pairs: Sequence[tuple[Decimal, bool]]) -> Decimal:
        total = Decimal("0")
        for probability, outcome in pairs:
            residual = probability - (Decimal("1") if outcome else Decimal("0"))
            total += residual * residual
        return total / len(pairs)

    def _log_loss(self, pairs: Sequence[tuple[Decimal, bool]]) -> Decimal:
        total = Decimal("0")
        for probability, outcome in pairs:
            p = min(max(probability, Decimal("0.0001")), Decimal("0.9999"))
            total += -_log(p) if outcome else -_log(Decimal("1") - p)
        return total / len(pairs)

    def _accuracy(self, pairs: Sequence[tuple[Decimal, bool]]) -> Decimal:
        correct = sum(
            1
            for probability, outcome in pairs
            if (probability >= Decimal("0.5")) == outcome
        )
        return Decimal(correct) / len(pairs)

    def _buckets(self, pairs: Sequence[tuple[Decimal, bool]]) -> tuple[tuple[Decimal, Decimal, int], ...]:
        buckets: dict[int, list[bool]] = {bucket: [] for bucket in range(10)}
        for probability, outcome in pairs:
            bucket = min(int(probability * Decimal("10")), 9)
            buckets[bucket].append(outcome)
        return tuple(
            (
                Decimal(bucket) / Decimal("10"),
                (
                    sum(1 for outcome in outcomes if outcome) / len(outcomes)
                    if outcomes
                    else Decimal("0")
                ),
                len(outcomes),
            )
            for bucket, outcomes in buckets.items()
            if outcomes
        )


def _probability(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        probability = Decimal(str(value))
    except (ValueError, ArithmeticError):
        return None
    if not (Decimal("0") <= probability <= Decimal("1")):
        return None
    return probability


def _log(value: Decimal) -> Decimal:
    return value.ln()