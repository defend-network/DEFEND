"""Frozen M5 live inference for forward TT events (Phase D P3).

M5 is FROZEN: a single L2-regularized logistic weight vector is fit once on
all canonical TT matches strictly before a freeze cutoff (tools/defend_tt_m5_freeze.py)
and pinned in docs/operations/TT_M5_LIVE_WEIGHTS_V1.json. Inference never refits,
never touches the baseline JSON, and consumes only history strictly before the
prediction instant (no future/result leakage by construction).

The state replay here replicates tools/defend_tt_research_suite.py exactly
(same feature names, same ELO/RecencyElo/form/depth/h2h/day/degree mechanics,
same Newton-Raphson L2 fit with lam=1.0 and explicit intercept) so live
predictions are on the same footing as the frozen research baseline.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import numpy as np

_INITIAL_RATING = 1200.0
_K = 32.0

FEATURE_NAMES = [
    "home_indicator", "elo_diff", "recency_elo_diff", "form5_diff",
    "log_depth_diff", "rest_diff_days", "h2h_winrate_diff",
    "same_day_diff", "degree_diff",
]

MODEL_ID = "M5_REGULARIZED_LOGISTIC"
_LAM = 1.0


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def _fit_ridge(x: np.ndarray, y: np.ndarray, lam: float = _LAM) -> np.ndarray:
    n, d = x.shape
    xb = np.column_stack([np.ones(n), x])
    w = np.zeros(d + 1)
    for _ in range(40):
        z = xb @ w
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
        grad = xb.T @ (p - y) + np.concatenate([[0.0], lam * w[1:]])
        r = p * (1 - p)
        hess = xb.T @ (r[:, None] * xb) + np.diag(
            np.concatenate([[0.0], np.full(d, lam)])
        )
        try:
            step = np.linalg.solve(hess, grad)
        except np.linalg.LinAlgError:
            break
        w -= step
        if np.max(np.abs(step)) < 1e-7:
            break
    return w


class RecencyElo:
    def __init__(self, window: int = 100) -> None:
        self.window = window
        self.history: dict[str, list[tuple[datetime, str, float]]] = defaultdict(list)

    def rating(self, key: str) -> float:
        past = self.history.get(key, [])
        if not past:
            return _INITIAL_RATING
        recent = past[-self.window:]
        rating = _INITIAL_RATING
        for _ts, opponent, actual in recent:
            opp_rating = _INITIAL_RATING
            if self.history.get(opponent):
                opp_rating = rating
            expected = _sigmoid((rating - opp_rating) / 400.0)
            rating += _K * (actual - expected)
        return rating

    def record(self, key: str, ts: datetime, opponent: str, actual: float) -> None:
        self.history[key].append((ts, opponent, actual))


@dataclass(frozen=True)
class M5Match:
    event_key: str
    home_key: str
    away_key: str
    ts: datetime
    actual: float


class M5StateBuilder:
    """Chronological replay of canonical matches; state strictly before ts."""

    def __init__(self, matches: Iterable[M5Match]) -> None:
        self.elo: dict[str, float] = defaultdict(lambda: _INITIAL_RATING)
        self.recency = RecencyElo(100)
        self.form5: dict[str, list[float]] = defaultdict(list)
        self.depth: dict[str, int] = defaultdict(int)
        self.last_ts: dict[str, datetime] = {}
        self.day_games: dict[str, dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        self.h2h: dict[tuple[str, str], tuple[float, int]] = defaultdict(
            lambda: (0.0, 0)
        )
        self.opponents: dict[str, set[str]] = defaultdict(set)
        for match in sorted(matches, key=lambda m: (m.ts, m.event_key)):
            self._update(match)

    def _update(self, m: M5Match) -> None:
        home, away = m.home_key, m.away_key
        actual = m.actual
        e_home = _sigmoid((self.elo[home] - self.elo[away]) / 400.0)
        self.elo[home] += _K * (actual - e_home)
        self.elo[away] += _K * ((1 - actual) - (1 - e_home))
        self.recency.record(home, m.ts, away, actual)
        self.recency.record(away, m.ts, home, 1 - actual)
        for key, value in ((home, actual), (away, 1 - actual)):
            self.form5[key].append(value)
            if len(self.form5[key]) > 5:
                self.form5[key] = self.form5[key][-5:]
        self.depth[home] += 1
        self.depth[away] += 1
        self.last_ts[home] = m.ts
        self.last_ts[away] = m.ts
        day = m.ts.date().isoformat()
        self.day_games[home][day] += 1
        self.day_games[away][day] += 1
        if actual > 0.5:
            wins_a, meets_a = self.h2h[(home, away)]
            self.h2h[(home, away)] = (wins_a + 1, meets_a + 1)
        else:
            wins_b, meets_b = self.h2h[(away, home)]
            self.h2h[(away, home)] = (wins_b, meets_b + 1)
        self.opponents[home].add(away)
        self.opponents[away].add(home)

    def features(self, home: str, away: str, ts: datetime) -> dict[str, float]:
        """Features for a hypothetical (home, away) match at ts. State is the
        replay of all matches strictly before ts; no mutation happens here."""
        home_pre = self.elo[home]
        away_pre = self.elo[away]
        fh = self.form5.get(home, [])
        fa = self.form5.get(away, [])
        form_home = sum(fh) / len(fh) if fh else 0.5
        form_away = sum(fa) / len(fa) if fa else 0.5
        h2h_a = self.h2h.get((home, away), (0.0, 0))
        h2h_b = self.h2h.get((away, home), (0.0, 0))
        h2h_meetings = h2h_a[1] + h2h_b[1]
        h2h_wins_home = h2h_a[0] + (h2h_b[1] - h2h_b[0])
        h2h_rate_home = h2h_wins_home / h2h_meetings if h2h_meetings else 0.5
        rest_home = (
            (ts - self.last_ts[home]).total_seconds() / 86400.0
            if home in self.last_ts
            else None
        )
        rest_away = (
            (ts - self.last_ts[away]).total_seconds() / 86400.0
            if away in self.last_ts
            else None
        )
        rest_diff = (
            (rest_home - rest_away)
            if (rest_home is not None and rest_away is not None)
            else 0.0
        )
        day = ts.date().isoformat()
        same_day_diff = float(self.day_games[home][day] - self.day_games[away][day])
        log_depth_diff = math.log1p(self.depth.get(home, 0)) - math.log1p(
            self.depth.get(away, 0)
        )
        degree_diff = float(
            len(self.opponents.get(home, set())) - len(self.opponents.get(away, set()))
        )
        return {
            "home_indicator": 1.0,
            "elo_diff": home_pre - away_pre,
            "recency_elo_diff": self.recency.rating(home) - self.recency.rating(away),
            "form5_diff": form_home - form_away,
            "log_depth_diff": log_depth_diff,
            "rest_diff_days": rest_diff,
            "h2h_winrate_diff": 2 * h2h_rate_home - 1.0,
            "same_day_diff": same_day_diff,
            "degree_diff": degree_diff,
        }

    def history_depth(self, key: str) -> int:
        return self.depth.get(key, 0)


class FrozenM5:
    """Pinned weight vector + deterministic inference (M5 remains frozen)."""

    def __init__(self, weights: dict[str, Any], *, source_ref: str) -> None:
        names = list(weights["feature_names"])
        if names != FEATURE_NAMES:
            raise ValueError(
                f"feature schema mismatch: {names} != {FEATURE_NAMES}"
            )
        self._w = np.asarray(
            [weights["intercept"]] + [weights["weights"][n] for n in names],
            dtype=float,
        )
        self.model_version = f"{weights.get('model_id', MODEL_ID)}:{weights['sha256'][:12]}"
        self.fit_n = int(weights["fit_n"])
        self.source_ref = source_ref
        self._feature_names = tuple(names)
        self._schema_hash = str(weights["sha256"])

    @property
    def feature_snapshot_id(self) -> str:
        return self._schema_hash

    def predict(
        self, builder: M5StateBuilder, home: str, away: str, ts: datetime, *, min_games: int = 5
    ) -> tuple[float, str, dict[str, float]]:
        available = (
            builder.history_depth(home) >= min_games
            and builder.history_depth(away) >= min_games
        )
        features = builder.features(home, away, ts)
        if not available:
            return 0.5, "INSUFFICIENT_HISTORY", features
        xv = np.asarray([features[n] for n in self._feature_names], dtype=float)
        p = _sigmoid(float(self._w[0] + self._w[1:] @ xv))
        p = min(max(p, 1e-6), 1 - 1e-6)
        return p, "AVAILABLE", features

    @staticmethod
    def freeze(
        matches: list[M5Match],
        *,
        cutoff: datetime,
        min_train: int = 200,
    ) -> dict[str, Any]:
        """Fit the frozen weight vector on all matches strictly before cutoff.

        Features mirror tools/defend_tt_research_suite.py exactly: each
        training row is built from state strictly before that match, then
        state is updated (chronological single pass, no future leakage).
        """
        train = sorted(
            [m for m in matches if m.ts < cutoff],
            key=lambda m: (m.ts, m.event_key),
        )
        n_train = len(train)
        if n_train < min_train:
            raise ValueError(
                f"insufficient training data for freeze: {n_train} < {min_train}"
            )
        builder = M5StateBuilder([])
        x_rows: list[list[float]] = []
        y_rows: list[float] = []
        for m in train:
            f = builder.features(m.home_key, m.away_key, m.ts)
            x_rows.append([f[n] for n in FEATURE_NAMES])
            y_rows.append(m.actual)
            builder._update(m)
        x = np.asarray(x_rows, dtype=float)
        y = np.asarray(y_rows, dtype=float)
        w = _fit_ridge(x, y)
        w_map = {
            name: round(float(v), 6)
            for name, v in zip(["intercept"] + FEATURE_NAMES, w)
        }
        sha = hashlib.sha256(
            json.dumps(w_map, sort_keys=True).encode("utf-8")
        ).hexdigest()
        preds = 1.0 / (1.0 + np.exp(-np.clip(x @ w[1:] + w[0], -30, 30)))
        brier = float(np.mean((preds - y) ** 2))
        log_loss = float(
            np.mean(
                -(
                    y * np.log(np.clip(preds, 1e-9, 1))
                    + (1 - y) * np.log(np.clip(1 - preds, 1e-9, 1))
                )
            )
        )
        return {
            "schema": "TT_M5_LIVE_WEIGHTS",
            "model_id": MODEL_ID,
            "feature_names": FEATURE_NAMES,
            "lam": _LAM,
            "intercept": w_map["intercept"],
            "weights": {n: w_map[n] for n in FEATURE_NAMES},
            "fit_n": n_train,
            "cutoff": cutoff.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
            "fit_brier": round(float(brier), 6),
            "fit_log_loss": round(float(log_loss), 6),
            "sha256": sha,
        }


def load_frozen_weights(path: Any) -> FrozenM5:
    doc = json.loads(path.read_text(encoding="utf-8"))
    return FrozenM5(doc, source_ref=str(path))


def weights_sha256(doc: dict[str, Any]) -> str:
    return doc["sha256"]