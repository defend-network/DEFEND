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