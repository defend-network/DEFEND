"""L2 predictive layer for Table Tennis: Elo-based strength model.

Player strength is estimated from real completed-match history
(``tt_match_results``) using a standard logistic Elo system. The model
never fabricates history: with fewer than ``MIN_HISTORY_GAMES`` per
player it reports ``available=False`` and the decision loop abstains.

H2H results are not treated as truth; they are one optional feature.
Recent form is a simple last-N win rate. Load/rest is not modeled
because no source provides it — that stays an explicit limitation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable, Mapping, Sequence

from defend_markets.domain import TTMatchResult

_INITIAL_RATING = Decimal("1200")
_K_FACTOR = Decimal("32")
_MIN_HISTORY_GAMES = 5
_RECENT_FORM_WINDOW = 5

# Probabilities below this width are treated as fair toss-ups for
# calibration purposes; buckets are half-open intervals of p_home.
_CALIBRATION_BUCKETS: tuple[tuple[str, Decimal, Decimal], ...] = (
    ("0.50-0.60", Decimal("0.50"), Decimal("0.60")),
    ("0.60-0.70", Decimal("0.60"), Decimal("0.70")),
    ("0.70-0.80", Decimal("0.70"), Decimal("0.80")),
    ("0.80-0.90", Decimal("0.80"), Decimal("0.90")),
    ("0.90-1.00", Decimal("0.90"), Decimal("1.01")),
)


def expected_score(rating_a: Decimal, rating_b: Decimal) -> Decimal:
    """Logistic expected score for A against B."""
    exponent = Decimal((rating_b - rating_a) / Decimal("400"))
    return Decimal("1") / (Decimal("1") + (Decimal("10") ** exponent))


def update_rating(
    rating: Decimal, expected: Decimal, actual: Decimal, k: Decimal = _K_FACTOR
) -> Decimal:
    """Elo update after one match (actual = 1 win / 0.5 draw / 0 loss)."""
    return rating + k * (actual - expected)


def calibration_bucket(p_home: Decimal) -> str | None:
    """Calibration bucket label for a modeled home probability."""
    if not (Decimal("0") <= p_home <= Decimal("1")):
        return None
    for label, lower, upper in _CALIBRATION_BUCKETS:
        if lower <= p_home < upper:
            return label
    return None


@dataclass(frozen=True)
class TTPlayerProfile:
    participant_key: str
    rating: Decimal = _INITIAL_RATING
    games: int = 0
    wins: int = 0
    recent_wins: int = 0
    recent_games: int = 0

    @property
    def win_rate(self) -> Decimal | None:
        if self.games == 0:
            return None
        return Decimal(self.wins) / Decimal(self.games)

    @property
    def recent_form(self) -> Decimal | None:
        if self.recent_games == 0:
            return None
        return Decimal(self.recent_wins) / Decimal(self.recent_games)


def _sort_results(results: Iterable[TTMatchResult]) -> list[TTMatchResult]:
    return sorted(
        results,
        key=lambda result: (
            result.completed_at.isoformat() if result.completed_at is not None else "",
            result.event_key,
        ),
    )


def build_ratings(results: Iterable[TTMatchResult]) -> dict[str, TTPlayerProfile]:
    """Rate every player from completed match history, oldest first.

    A player's profile counts only matches involving that player; recent
    form is the last ``_RECENT_FORM_WINDOW`` matches in chronological
    order.
    """
    profiles: dict[str, TTPlayerProfile] = {}
    recent: dict[str, list[bool]] = {}

    for result in _sort_results(results):
        home = result.home_participant_key
        away = result.away_participant_key
        if not home or not away or home == away:
            continue
        home_won = result.home_score > result.away_score
        away_won = result.away_score > result.home_score
        drawn = not home_won and not away_won

        home_rating = profiles.get(home, TTPlayerProfile(home)).rating
        away_rating = profiles.get(away, TTPlayerProfile(away)).rating
        home_expected = expected_score(home_rating, away_rating)
        away_expected = Decimal("1") - home_expected
        home_actual = Decimal("0.5") if drawn else (Decimal("1") if home_won else Decimal("0"))
        away_actual = Decimal("0.5") if drawn else (Decimal("1") if away_won else Decimal("0"))

        profiles[home] = _with_game(profiles.get(home, TTPlayerProfile(home)), home_won, drawn, home_rating, home_expected, home_actual)
        profiles[away] = _with_game(profiles.get(away, TTPlayerProfile(away)), away_won, drawn, away_rating, away_expected, away_actual)
        recent.setdefault(home, []).append(home_won or drawn)
        recent.setdefault(away, []).append(away_won or drawn)

    for key, outcomes in recent.items():
        window = outcomes[-_RECENT_FORM_WINDOW:]
        profile = profiles[key]
        profiles[key] = TTPlayerProfile(
            participant_key=key,
            rating=profile.rating,
            games=profile.games,
            wins=profile.wins,
            recent_wins=sum(1 for outcome in window if outcome),
            recent_games=len(window),
        )
    return profiles


def _with_game(
    profile: TTPlayerProfile,
    won: bool,
    drawn: bool,
    old_rating: Decimal,
    expected: Decimal,
    actual: Decimal,
) -> TTPlayerProfile:
    return TTPlayerProfile(
        participant_key=profile.participant_key,
        rating=update_rating(old_rating, expected, actual),
        games=profile.games + 1,
        wins=profile.wins + (1 if won else 0),
        recent_wins=0,
        recent_games=0,
    )


@dataclass(frozen=True)
class TTRatingHistoryRow:
    """One chronological Elo update for one participant in one match.

    ``pre_rating``/``expected``/``actual``/``post_rating`` let a consumer
    replay a player's trajectory (or evaluate time-forward performance)
    without reimplementing the update rule. ``result`` is from the
    participant's perspective.
    """

    participant_key: str
    ts: datetime
    event_key: str
    opponent_key: str
    pre_rating: Decimal
    expected: Decimal
    actual: Decimal
    post_rating: Decimal
    result: str
    model_version: str
    source_provider: str
    raw_ref: str | None = None

    def __post_init__(self) -> None:
        if self.result not in ("win", "loss", "draw"):
            raise ValueError("result must be win, loss, or draw")


def rebuild_rating_history(
    results: Iterable[TTMatchResult],
    *,
    model_version: str = "1.0.0",
) -> tuple[TTRatingHistoryRow, ...]:
    """Replay match history chronologically into per-participant Elo rows.

    One row per participant per match (both sides). Ratings evolve in
    strict chronological order, so the table can be read as a true
    time-forward trajectory; identical timestamps tie-break on event key.
    Matches with a missing or self-vs-self participant pair are skipped.
    """
    ratings: dict[str, Decimal] = {}
    rows: list[TTRatingHistoryRow] = []

    for result in _sort_results(results):
        home = result.home_participant_key
        away = result.away_participant_key
        if not home or not away or home == away:
            continue
        home_won = result.home_score > result.away_score
        away_won = result.away_score > result.home_score
        drawn = not home_won and not away_won
        home_actual = Decimal("0.5") if drawn else (Decimal("1") if home_won else Decimal("0"))
        away_actual = Decimal("0.5") if drawn else (Decimal("1") if away_won else Decimal("0"))
        ts = result.completed_at or datetime.min.replace(tzinfo=timezone.utc)

        home_pre = ratings.get(home, _INITIAL_RATING)
        away_pre = ratings.get(away, _INITIAL_RATING)
        home_expected = expected_score(home_pre, away_pre)
        away_expected = Decimal("1") - home_expected
        home_post = update_rating(home_pre, home_expected, home_actual)
        away_post = update_rating(away_pre, away_expected, away_actual)
        ratings[home] = home_post
        ratings[away] = away_post

        rows.append(
            TTRatingHistoryRow(
                participant_key=home,
                ts=ts,
                event_key=result.event_key,
                opponent_key=away,
                pre_rating=home_pre,
                expected=home_expected,
                actual=home_actual,
                post_rating=home_post,
                result="win" if home_won else ("loss" if away_won else "draw"),
                model_version=model_version,
                source_provider=result.source_provider,
                raw_ref=result.raw_ref,
            )
        )
        rows.append(
            TTRatingHistoryRow(
                participant_key=away,
                ts=ts,
                event_key=result.event_key,
                opponent_key=home,
                pre_rating=away_pre,
                expected=away_expected,
                actual=away_actual,
                post_rating=away_post,
                result="win" if away_won else ("loss" if home_won else "draw"),
                model_version=model_version,
                source_provider=result.source_provider,
                raw_ref=result.raw_ref,
            )
        )
    return tuple(rows)


@dataclass(frozen=True)
class TimeForwardMatch:
    """One historical match evaluated from pre-match ratings only."""

    event_key: str
    league_key: str
    home_participant_key: str
    away_participant_key: str
    completed_at: datetime | None
    home_score: int
    away_score: int
    p_home: Decimal | None
    p_away: Decimal | None
    available: bool
    reason: str | None = None


@dataclass(frozen=True)
class TimeForwardEvaluation:
    """Time-forward Elo evaluation over a chronological history.

    Every evaluated match uses ratings that were built only from matches
    strictly before it (leakage-free by construction). ``brier`` is the
    mean squared error of p_home against the realized home win, and
    ``calibration`` buckets outcomes by predicted probability.
    """

    matches: tuple[TimeForwardMatch, ...] = ()
    n_available: int = 0
    brier: Decimal | None = None
    accuracy: Decimal | None = None
    calibration: tuple[tuple[str, int, int], ...] = ()

    @property
    def n_evaluated(self) -> int:
        return len(self.matches)

    def to_dict(self) -> dict[str, object]:
        return {
            "n_matches": self.n_evaluated,
            "n_available": self.n_available,
            "brier": str(self.brier) if self.brier is not None else None,
            "accuracy": str(self.accuracy) if self.accuracy is not None else None,
            "calibration": [
                {"bucket": label, "matches": total, "home_wins": wins}
                for label, total, wins in self.calibration
            ],
        }


def evaluate_time_forward(
    results: Iterable[TTMatchResult],
    *,
    min_history_games: int = _MIN_HISTORY_GAMES,
) -> TimeForwardEvaluation:
    """Evaluate pre-match Elo predictions against realized outcomes.

    Ratings are updated after every match, so a match's prediction can
    never see its own outcome or any later match. Matches with fewer than
    ``min_history_games`` per player are recorded with ``available=False``
    and excluded from the metrics.
    """
    ratings: dict[str, TTPlayerProfile] = {}
    matches: list[TimeForwardMatch] = []
    squared_errors: list[Decimal] = []
    correct: list[bool] = []
    bucket_rows: dict[str, list[bool]] = {
        label: [] for label, _, _ in _CALIBRATION_BUCKETS
    }

    def _profile(key: str) -> TTPlayerProfile:
        return ratings.get(key, TTPlayerProfile(key))

    for result in _sort_results(results):
        home = result.home_participant_key
        away = result.away_participant_key
        if not home or not away or home == away:
            continue
        home_profile = _profile(home)
        away_profile = _profile(away)
        home_won = result.home_score > result.away_score
        away_won = result.away_score > result.home_score
        drawn = not home_won and not away_won

        available = (
            home_profile.games >= min_history_games
            and away_profile.games >= min_history_games
        )
        if available:
            p_home = expected_score(home_profile.rating, away_profile.rating)
            actual_home = Decimal("0.5") if drawn else (Decimal("1") if home_won else Decimal("0"))
            squared_errors.append((p_home - actual_home) ** 2)
            correct.append(True if home_won else (False if away_won else None))
            bucket = calibration_bucket(p_home)
            if bucket is not None:
                bucket_rows.setdefault(bucket, []).append(home_won)
        else:
            p_home = None

        matches.append(
            TimeForwardMatch(
                event_key=result.event_key,
                league_key=result.league_key,
                home_participant_key=home,
                away_participant_key=away,
                completed_at=result.completed_at,
                home_score=result.home_score,
                away_score=result.away_score,
                p_home=p_home,
                p_away=(Decimal("1") - p_home) if p_home is not None else None,
                available=available,
                reason=None if available else (
                    f"insufficient history (home {home_profile.games}, away {away_profile.games})"
                ),
            )
        )

        home_expected = expected_score(home_profile.rating, away_profile.rating)
        away_expected = Decimal("1") - home_expected
        home_actual = Decimal("0.5") if drawn else (Decimal("1") if home_won else Decimal("0"))
        away_actual = Decimal("0.5") if drawn else (Decimal("1") if away_won else Decimal("0"))
        ratings[home] = _with_game(
            home_profile, home_won, drawn, home_profile.rating, home_expected, home_actual
        )
        ratings[away] = _with_game(
            away_profile, away_won, drawn, away_profile.rating, away_expected, away_actual
        )

    n_available = len(squared_errors)
    brier = None
    if n_available:
        brier = sum(squared_errors, Decimal("0")) / Decimal(n_available)
    accuracy = None
    decided = [value for value in correct if value is not None]
    if decided:
        accuracy = Decimal(sum(1 for value in decided if value)) / Decimal(len(decided))
    calibration = tuple(
        (label, len(outcomes), sum(1 for outcome in outcomes if outcome))
        for label, outcomes in bucket_rows.items()
    )
    return TimeForwardEvaluation(
        matches=tuple(matches),
        n_available=n_available,
        brier=brier,
        accuracy=accuracy,
        calibration=calibration,
    )


@dataclass(frozen=True)
class TTModelEvaluation:
    home_participant_key: str
    away_participant_key: str
    p_home: Decimal | None = None
    p_away: Decimal | None = None
    home_rating: Decimal | None = None
    away_rating: Decimal | None = None
    home_games: int = 0
    away_games: int = 0
    home_form: Decimal | None = None
    away_form: Decimal | None = None
    available: bool = False
    reason: str = "insufficient model history"
    calibration_bucket: str | None = None

    @property
    def p_away_computed(self) -> Decimal | None:
        if self.p_home is None:
            return None
        return Decimal("1") - self.p_home


class TTEloModel:
    """Elo model over the persisted ``tt_match_results`` history."""

    label = "tt_elo"
    version = "1.0.0"
    min_history_games = _MIN_HISTORY_GAMES

    def __init__(
        self,
        results: Sequence[TTMatchResult] | None = None,
        min_history_games: int = _MIN_HISTORY_GAMES,
    ) -> None:
        self._min_games = min_history_games
        self._ratings: dict[str, TTPlayerProfile] = {}
        if results:
            self._ratings = build_ratings(results)

    @classmethod
    def from_history_rows(
        cls, rows: Sequence[Mapping[str, object]], min_history_games: int = _MIN_HISTORY_GAMES
    ) -> "TTEloModel":
        results = [
            TTMatchResult(
                event_key=str(row["event_key"]),
                league_key=str(row["league_key"]),
                home_participant_key=str(row["home_participant_key"]),
                away_participant_key=str(row["away_participant_key"]),
                home_score=int(row["home_score"]),
                away_score=int(row["away_score"]),
                completed_at=row.get("completed_at"),
                source_provider=str(row.get("source_provider") or "unknown"),
                raw_ref=row.get("raw_ref"),
            )
            for row in rows
        ]
        return cls(results, min_history_games=min_history_games)

    def refresh(self, results: Sequence[TTMatchResult]) -> None:
        self._ratings = build_ratings(results)

    def profiles(self) -> Mapping[str, TTPlayerProfile]:
        return self._ratings

    def evaluate(
        self, home_participant_key: str, away_participant_key: str
    ) -> TTModelEvaluation:
        home = self._ratings.get(home_participant_key)
        away = self._ratings.get(away_participant_key)
        if home is None or away is None:
            missing = [
                key
                for key in (home_participant_key, away_participant_key)
                if key not in self._ratings
            ]
            return TTModelEvaluation(
                home_participant_key=home_participant_key,
                away_participant_key=away_participant_key,
                home_rating=home.rating if home else None,
                away_rating=away.rating if away else None,
                home_games=home.games if home else 0,
                away_games=away.games if away else 0,
                available=False,
                reason=f"no history for player(s): {', '.join(missing)}",
            )
        if home.games < self._min_games or away.games < self._min_games:
            return TTModelEvaluation(
                home_participant_key=home_participant_key,
                away_participant_key=away_participant_key,
                home_rating=home.rating,
                away_rating=away.rating,
                home_games=home.games,
                away_games=away.games,
                home_form=home.recent_form,
                away_form=away.recent_form,
                available=False,
                reason=(
                    f"insufficient history (home {home.games}, away {away.games}; "
                    f"minimum {self._min_games})"
                ),
            )
        p_home = expected_score(home.rating, away.rating)
        return TTModelEvaluation(
            home_participant_key=home_participant_key,
            away_participant_key=away_participant_key,
            p_home=p_home,
            p_away=Decimal("1") - p_home,
            home_rating=home.rating,
            away_rating=away.rating,
            home_games=home.games,
            away_games=away.games,
            home_form=home.recent_form,
            away_form=away.recent_form,
            available=True,
            reason=None,
            calibration_bucket=calibration_bucket(p_home),
        )