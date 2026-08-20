"""Table tennis events, historical results and closing odds from Odds-API.io.

Network provider: reads the Odds-API.io v3 REST API (apiKey query auth) and
maps responses into canonical DEFEND Sports models. Both live/upcoming
(``/events``, ``/odds``, ``/events/live``) and historical (``/historical/events``,
``/historical/odds``) endpoints are supported; the historical surface exists
for the backfill job. Only real API data is emitted: HTTP failures surface as
provider errors (recorded UNAVAILABLE downstream) and missing credentials
must be reported by the caller before polling (UNCONFIGURED).

Provenance: canonical event keys are namespaced ``oaio:<provider_id>`` so
rows from Odds-API.io can never collide with or overwrite rows from another
provider (e.g. The Odds API). Every parsed event keeps its full provider
payload in the raw provider event row.
"""

from __future__ import annotations

import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable, Sequence

from defend_markets.feeds import FeedError, http_get_json as _markets_http_get_json

from defend_sports.domain import (
    CanonicalEvent,
    LiveObservation,
    OddsObservation,
    SourceRef,
)
from defend_sports.providers.base import ProviderBatch, RawProviderEvent, SportsProvider

_ODDS_API_IO_BASE = "https://api.odds-api.io/v3"

_TT_SLUG_HINTS = ("table-tennis", "tabletennis", "ping pong", "pingpong")

_DEFAULT_SPORT_SLUG = "table-tennis"

_ML_MARKET_NAMES = {"ml", "match_winner", "moneyline", "h2h"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class OddsApiIoProviderError(Exception):
    """Odds-API.io provider failure carrying a human detail."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def http_get_json(url: str) -> tuple[object, int]:
    try:
        return _markets_http_get_json(url)
    except FeedError as error:
        raise OddsApiIoProviderError(error.detail) from None


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_decimal_odds(value: object) -> Decimal | None:
    if not isinstance(value, (int, float, str)):
        return None
    try:
        odds = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not odds.is_finite() or odds <= Decimal("1"):
        return None
    return odds


def _normalize_selection(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in ("home", "away", "draw"):
        return normalized
    return None


def _slugify(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    lowered = value.strip().lower()
    slug = "".join(
        char if char.isalnum() else "-" for char in lowered
    ).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or None


def _parse_scores(value: object) -> tuple[int, int] | None:
    """Tolerantly parse home/away scores from Odds-API.io score payloads.

    Handles dicts (``{"home": 3, "away": 1}``), lists of dicts carrying
    home/away keys, and ``"3:1"``-style strings. Only returns a pair of
    non-negative integers.
    """

    def _as_int(item: object) -> int | None:
        if isinstance(item, bool):
            return None
        if isinstance(item, int):
            return item if item >= 0 else None
        if isinstance(item, str) and item.strip().isdigit():
            return int(item.strip())
        if isinstance(item, float) and item.is_integer() and item >= 0:
            return int(item)
        return None

    if isinstance(value, dict):
        home = _as_int(value.get("home"))
        away = _as_int(value.get("away"))
        if home is None:
            home = _as_int(value.get("homeScore"))
        if away is None:
            away = _as_int(value.get("awayScore"))
        if home is not None and away is not None:
            return home, away
        return None
    if isinstance(value, list):
        for entry in value:
            if not isinstance(entry, dict):
                continue
            home = _as_int(entry.get("home"))
            away = _as_int(entry.get("away"))
            if home is None:
                home = _as_int(entry.get("homeScore"))
            if away is None:
                away = _as_int(entry.get("awayScore"))
            if home is not None and away is not None:
                return home, away
        return None
    if isinstance(value, str):
        parts = value.strip().split(":")
        if len(parts) == 2:
            home = _as_int(parts[0])
            away = _as_int(parts[1])
            if home is not None and away is not None:
                return home, away
    return None


def _coerce_int(value: object) -> int | None:
    """Tolerantly coerce JSON numbers/strings to non-negative ints."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and value.is_integer() and value >= 0:
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


@dataclass(frozen=True)
class TTFinalResult:
    """Canonical table-tennis final result derived from an Odds-API.io payload.

    ``status`` is VERIFIED (a winner is demonstrable), VOID (the event is
    excluded from result labels; no winner can be demonstrated) or
    UNRESOLVED (no usable score data at all). VOID/UNRESOLVED rows must be
    persisted with equal home/away scores so downstream evaluation treats
    them as excluded, exactly like the provider's own equal-score rows.
    """

    status: str
    home_score: int | None
    away_score: int | None
    winner: str | None
    source: str
    reason_code: str


def _is_legal_final_game(home: int | None, away: int | None) -> bool:
    """True when a period's point score is a completed table-tennis game.

    A finished game ends at >= 11 points with a winning margin of at least
    two (deuce extends the target: 12-10, 17-15, ...). Snapshot/partial
    periods (4-5, 10-10, 9-6) are never legal finals.
    """
    if home is None or away is None or home == away:
        return False
    high, low = max(home, away), min(home, away)
    return high >= 11 and high - low >= 2


def parse_tt_final_result(payload: dict[str, object]) -> TTFinalResult:
    """Derive the canonical match result from one Odds-API.io event payload.

    Evidence hierarchy (empirically validated on the historical corpus):

    1. ``scores.periods.ft`` -- the provider's explicit final game count.
       Authoritative when present with two integer values; equal counts
       (e.g. 3-3) mean the match is not a finished result -> VOID.
    2. Completed periods -- legal final game scores (>= 11, margin >= 2).
       A strict majority across >= 2 complete games is a verified result.
    3. Single completed game -- either confirmed by a plausible top-level
       game count (0..3) or a bare legal game score with no contradicting
       top-level data (single-game format).
    4. Top-level ``scores.home/away`` -- only used as a final game count
       (0..3); the corpus shows this is reliable in ~99.99% of rows where
       the provider also reported ft. Bare legal game scores (11-8, 14-12)
       with no periods are accepted as single-game results only when no
       contradiction exists.
    5. Anything partial, tied, negative or contradictory -> VOID/UNRESOLVED.
       Never invent a winner.
    """
    scores = payload.get("scores")
    if not isinstance(scores, dict):
        return TTFinalResult("UNRESOLVED", None, None, None, "NONE", "NO_SCORE_DATA")
    top = _parse_scores(scores)
    periods = scores.get("periods")
    if not isinstance(periods, dict):
        periods = {}
    ft_raw = periods.get("ft")
    ft = (
        (_coerce_int(ft_raw.get("home")), _coerce_int(ft_raw.get("away")))
        if isinstance(ft_raw, dict)
        else None
    )
    if ft is not None and ft[0] is not None and ft[1] is not None:
        if ft[0] == ft[1]:
            return TTFinalResult("VOID", ft[0], ft[1], None, "NONE", "FT_EQUAL")
        winner = "HOME" if ft[0] > ft[1] else "AWAY"
        return TTFinalResult("VERIFIED", ft[0], ft[1], winner, "PERIODS_FT", "FT_PRESENT")

    games: list[tuple[int, int]] = []
    partial: list[str] = []
    for key, period in periods.items():
        if key == "ft" or not isinstance(period, dict):
            continue
        ph = _coerce_int(period.get("home"))
        pa = _coerce_int(period.get("away"))
        if _is_legal_final_game(ph, pa):
            games.append((ph, pa))
        else:
            partial.append(key)

    home_wins = sum(1 for ph, pa in games if ph > pa)
    away_wins = len(games) - home_wins

    if len(games) >= 2:
        if home_wins != away_wins:
            majority = "HOME" if home_wins > away_wins else "AWAY"
            if top is not None and top[0] != top[1] and 0 <= top[0] <= 3 and 0 <= top[1] <= 3:
                top_winner = "HOME" if top[0] > top[1] else "AWAY"
                if top_winner != majority:
                    return TTFinalResult(
                        "VOID", top[0], top[1], None, "NONE", "TOP_PERIODS_CONFLICT"
                    )
            return TTFinalResult(
                "VERIFIED", home_wins, away_wins,
                majority, "DERIVED_PERIODS", "PERIOD_MAJORITY",
            )
        return TTFinalResult(
            "VOID", top[0] if top else 0, top[1] if top else 0, None, "NONE",
            "PERIODS_TIED",
        )

    if len(games) == 1:
        game = games[0]
        game_winner = "HOME" if game[0] > game[1] else "AWAY"
        if top is None:
            return TTFinalResult(
                "VERIFIED", game[0], game[1], game_winner, "SINGLE_GAME", "GAME_ONLY"
            )
        if top[0] == top[1]:
            return TTFinalResult("VOID", top[0], top[1], None, "NONE", "TOP_EQUAL_GAME_CONFLICT")
        if 0 <= top[0] <= 3 and 0 <= top[1] <= 3:
            top_winner = "HOME" if top[0] > top[1] else "AWAY"
            if top_winner == game_winner:
                return TTFinalResult(
                    "VERIFIED", top[0], top[1], top_winner,
                    "TOP_LEVEL_FALLBACK", "TOP_GAME_CONSISTENT",
                )
            return TTFinalResult(
                "VOID", top[0], top[1], None, "NONE", "TOP_GAME_CONFLICT"
            )
        top_winner = "HOME" if top[0] > top[1] else "AWAY"
        if top_winner == game_winner:
            return TTFinalResult(
                "VERIFIED", game[0], game[1], game_winner,
                "SINGLE_GAME", "GAME_ONLY_CONSISTENT",
            )
        return TTFinalResult("VOID", top[0], top[1], None, "NONE", "TOP_GAME_CONFLICT")

    if top is None:
        return TTFinalResult("UNRESOLVED", None, None, None, "NONE", "NO_SCORE_DATA")
    if top[0] == top[1]:
        return TTFinalResult("VOID", top[0], top[1], None, "NONE", "TOP_EQUAL")
    if 0 <= top[0] <= 3 and 0 <= top[1] <= 3:
        winner = "HOME" if top[0] > top[1] else "AWAY"
        return TTFinalResult(
            "VERIFIED", top[0], top[1], winner,
            "TOP_LEVEL_FALLBACK", "TOP_GAME_COUNT",
        )
    if _is_legal_final_game(top[0], top[1]):
        winner = "HOME" if top[0] > top[1] else "AWAY"
        return TTFinalResult(
            "VERIFIED", top[0], top[1], winner, "SINGLE_GAME", "TOP_LEGAL_GAME"
        )
    return TTFinalResult("UNRESOLVED", top[0], top[1], None, "NONE", "TOP_IMPLAUSIBLE")


def _league_slug_from_payload(value: object) -> str:
    """Extract a league slug from string or ``{"name": ..., "slug": ...}``."""
    if isinstance(value, dict):
        slug = str(value.get("slug") or "").strip()
        if slug:
            return slug
        return _slugify(value.get("name") or "") or ""
    return _slugify(value) or ""


def parse_event_payload(
    match: dict[str, object],
    *,
    observed_at: datetime,
    suffix: str,
    league_slug: str | None = None,
) -> tuple[RawProviderEvent, CanonicalEvent] | None:
    """Map one Odds-API.io event payload to raw + canonical models.

    ``suffix`` is embedded in the raw event reference so the same event
    always produces the same raw reference (stable across backfill
    resumes). Event ids are namespaced ``oaio:<id>`` to guarantee they
    never collide with another provider's event keys.
    """
    event_id = str(match.get("id") or "").strip()
    home = str(match.get("home") or "").strip()
    away = str(match.get("away") or "").strip()
    if not event_id or not home or not away:
        return None
    raw_ref = f"oaio:{event_id}@{suffix}"
    league = _league_slug_from_payload(match.get("league"))
    league_key = league_slug or league or "table_tennis"
    event_external_id = f"oaio:{event_id}"
    raw_event = RawProviderEvent(
        source=SourceRef(provider="odds_api_io", external_id=league_key),
        provider_event_id=raw_ref,
        payload=dict(match),
        observed_at=observed_at,
        display_name="Odds-API.io",
    )
    event = CanonicalEvent(
        event_external_id=event_external_id,
        sport_key="table_tennis",
        league_key=league_key,
        display_name=f"{home} vs {away}",
        scheduled_at=_parse_timestamp(match.get("date"))
        or _parse_timestamp(match.get("startDate")),
        raw_event_ref=raw_ref,
    )
    return raw_event, event


def parse_odds_payload(
    payload: dict[str, object],
    *,
    event_external_id: str,
    raw_event_ref: str,
    default_observed_at: datetime,
    provider_name: str = "odds_api_io",
) -> tuple[OddsObservation, ...]:
    """Map a /historical/odds (or /odds) payload to canonical observations.

    The live API returns ``bookmakers`` as a mapping of bookmaker name to an
    odds object; list-of-mappings shapes are tolerated too. Only match-winner
    (ML) markets are emitted; handicap/totals are skipped.
    """
    observed_at = _parse_timestamp(payload.get("updatedAt")) or default_observed_at
    bookmakers = payload.get("bookmakers")
    rows: list[OddsObservation] = []
    if isinstance(bookmakers, dict):
        entries = [
            (book_key_raw, book_value)
            for book_key_raw, book_value in bookmakers.items()
        ]
    elif isinstance(bookmakers, list):
        entries = [
            (
                bookmaker.get("bookmaker")
                or bookmaker.get("name")
                or bookmaker.get("key"),
                bookmaker,
            )
            for bookmaker in bookmakers
            if isinstance(bookmaker, dict)
        ]
    else:
        return ()
    for book_key_raw, book_value in entries:
        book_key = _slugify(book_key_raw)
        if not book_key or not isinstance(book_value, dict):
            continue
        markets = book_value.get("markets")
        if isinstance(markets, dict):
            markets = [
                dict(market_value, market=market_name)
                for market_name, market_value in markets.items()
                if isinstance(market_value, dict)
            ]
        if not isinstance(markets, list):
            continue
        for market in markets:
            if not isinstance(market, dict):
                continue
            if (
                str(market.get("market") or "").strip().lower()
                not in _ML_MARKET_NAMES
            ):
                continue
            selections = {
                "home": _parse_decimal_odds(market.get("home")),
                "away": _parse_decimal_odds(market.get("away")),
                "draw": _parse_decimal_odds(market.get("draw")),
            }
            for selection_name, value in selections.items():
                if value is None:
                    continue
                rows.append(
                    OddsObservation(
                        source=SourceRef(
                            provider=provider_name, external_id=book_key
                        ),
                        event_external_id=event_external_id,
                        market_key="match_winner",
                        selection_key=selection_name,
                        decimal_odds=value,
                        observed_at=observed_at,
                        raw_event_ref=raw_event_ref,
                    )
                )
    return tuple(rows)


@dataclass(frozen=True)
class OddsApiIoSportsProvider:
    """Polls Odds-API.io v3 for table tennis events, odds and live scores.

    ``sport_slug`` may pin the sport slug (default discovery via ``/sports``
    with a fallback of ``table-tennis``). ``league_slug`` optionally narrows
    historical queries. ``http_get`` and ``sleep`` are injectable for tests;
    requests are paced to ``requests_per_second``.
    """

    provider_name: str = "odds_api_io"
    api_key: str = field(default="")
    sport_slug: str = field(default="")
    league_slug: str | None = field(default=None)
    bookmakers: tuple[str, ...] = field(default_factory=tuple)
    http_get: Callable[[str], tuple[object, int]] = field(default=http_get_json)
    clock: Callable[[], datetime] = field(default_factory=lambda: _utc_now)
    sleep: Callable[[float], None] = field(default=time.sleep)
    requests_per_second: float = 1.0
    live_odds_event_cap: int = 20
    _cached_slug: str = field(default="", init=False, repr=False)
    _cached_league: str = field(default="", init=False, repr=False)

    # ------------------------------------------------------------------ pacing

    def _pace(self) -> None:
        if self.requests_per_second > 0:
            self.sleep(1.0 / self.requests_per_second)

    def _get(self, path: str, query: dict[str, object]) -> tuple[object, int]:
        parts = [
            f"{_ODDS_API_IO_BASE}/{path}",
            f"apiKey={urllib.parse.quote(self.api_key)}",
        ]
        for name, value in query.items():
            if value is None:
                continue
            parts.append(f"{urllib.parse.quote(name)}={urllib.parse.quote(str(value))}")
        self._pace()
        url = parts[0] + "?" + "&".join(parts[1:])
        payload, status = self.http_get(url)
        return payload, status

    # ------------------------------------------------------------- sport lookup

    def resolve_sport_slug(self) -> str:
        if self.sport_slug.strip():
            return self.sport_slug.strip()
        if self._cached_slug:
            return self._cached_slug
        payload, _status = self._get("sports", {})
        if not isinstance(payload, list):
            raise OddsApiIoProviderError("unexpected /sports payload")
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            candidates = (
                str(entry.get("sportKey") or ""),
                str(entry.get("key") or ""),
                str(entry.get("name") or ""),
            )
            if any(
                hint in candidate.lower()
                for hint in _TT_SLUG_HINTS
                for candidate in candidates
                if candidate
            ):
                slug = _slugify(entry.get("sportKey") or entry.get("key") or "")
                if slug:
                    object.__setattr__(self, "_cached_slug", slug)
                    return slug
        return _DEFAULT_SPORT_SLUG

    def resolve_league_slug(self) -> str:
        """Discover the league slug via ``/v3/leagues`` (the API requires it).

        ``league_slug`` pins the choice; otherwise the league with the most
        documented events is picked and cached. Returns "" if the API
        provides no leagues.
        """
        if self.league_slug and self.league_slug.strip():
            return self.league_slug.strip()
        if self._cached_league:
            return self._cached_league
        payload, _status = self._get("leagues", {"sport": self.resolve_sport_slug()})
        if not isinstance(payload, list):
            return ""
        best: tuple[int, str] = (-1, "")
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            slug = str(entry.get("slug") or "").strip()
            if not slug:
                continue
            count = 0
            try:
                count = int(entry.get("eventsCount") or 0)
            except (TypeError, ValueError):
                count = 0
            if count > best[0]:
                best = (count, slug)
        if best[1]:
            object.__setattr__(self, "_cached_league", best[1])
        return best[1]

    # ------------------------------------------------------------ live polling

    def poll(self) -> ProviderBatch:
        if not self.api_key.strip():
            raise OddsApiIoProviderError("missing ODDS_API_IO_API_KEY")
        sport_slug = self.resolve_sport_slug()
        now = self.clock()
        suffix = now.strftime("%Y%m%dT%H%M%SZ")

        payload, _status = self._get(
            "events",
            {"sport": sport_slug, "limit": 200},
        )
        if not isinstance(payload, list):
            raise OddsApiIoProviderError("unexpected /events payload")
        if not payload:
            return ProviderBatch()

        raw_events: list[RawProviderEvent] = []
        events: list[CanonicalEvent] = []
        odds: list[OddsObservation] = []
        live: list[LiveObservation] = []
        live_refs: dict[str, str] = {}

        for match in payload:
            if not isinstance(match, dict):
                continue
            parsed = self._parse_event(match, observed_at=now, suffix=f"live:{suffix}")
            if parsed is None:
                continue
            raw_event, event = parsed
            raw_events.append(raw_event)
            events.append(event)
            live_refs[event.event_external_id] = raw_event.provider_event_id

        for event_external_id in list(live_refs)[: self.live_odds_event_cap]:
            try:
                odds_payload, _status = self._get(
                    "odds",
                    {"eventId": event_external_id.removeprefix("oaio:")},
                )
            except OddsApiIoProviderError:
                continue
            if not isinstance(odds_payload, dict):
                continue
            odds.extend(
                self._parse_odds_payload(
                    odds_payload,
                    event_external_id=event_external_id,
                    raw_event_ref=live_refs[event_external_id],
                    default_observed_at=now,
                )
            )

        try:
            live_payload, _status = self._get(
                "events/live",
                {"sport": sport_slug, "limit": 200},
            )
            if isinstance(live_payload, list):
                for match in live_payload:
                    if not isinstance(match, dict):
                        continue
                    event_external_id = "oaio:" + str(match.get("id") or "")
                    if event_external_id not in live_refs:
                        continue
                    scores = _parse_scores(match.get("scores"))
                    live.append(
                        LiveObservation(
                            source=SourceRef(
                                provider=self.provider_name, external_id=sport_slug
                            ),
                            event_external_id=event_external_id,
                            state={
                                "status": "live",
                                "sport": "table_tennis",
                                "scores": scores,
                            },
                            observed_at=now,
                            raw_event_ref=live_refs[event_external_id],
                        )
                    )
        except OddsApiIoProviderError:
            pass

        return ProviderBatch(
            raw_events=tuple(raw_events),
            events=tuple(events),
            live=tuple(live),
            odds=tuple(odds),
        )

    # ------------------------------------------------------------- historical

    def historical_events(
        self,
        from_dt: datetime,
        to_dt: datetime,
        *,
        skip: int = 0,
        limit: int = 200,
        league_slug: str | None = None,
    ) -> tuple[list[dict[str, object]], int]:
        """Return (list of SimpleEventDto payloads, status code).

        Historical windows are capped at 31 days by the provider; the caller
        splits larger ranges. The payload list is returned verbatim so the
        backfill job can page with limit+skip (provider cap 5000).
        """
        if not self.api_key.strip():
            raise OddsApiIoProviderError("missing ODDS_API_IO_API_KEY")
        sport_slug = self.resolve_sport_slug()
        league_slug = league_slug or self.resolve_league_slug()
        query: dict[str, object] = {
            "sport": sport_slug,
            "league": league_slug or _DEFAULT_SPORT_SLUG,
            "from": from_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to": to_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limit": limit,
            "skip": skip,
        }
        payload, status = self._get("historical/events", query)
        if not isinstance(payload, list):
            raise OddsApiIoProviderError("unexpected /historical/events payload")
        rows = [entry for entry in payload if isinstance(entry, dict)]
        return rows, status

    def historical_odds(
        self,
        event_id: str,
        bookmakers: Sequence[str] | None = None,
    ) -> dict[str, object]:
        """Return the /historical/odds payload for one provider event id.

        The live API requires an explicit ``bookmakers`` list (free plan
        caps it at 2 and rejects sharp/exchange books); events without odds
        come back with an empty ``bookmakers`` mapping.
        """
        if not self.api_key.strip():
            raise OddsApiIoProviderError("missing ODDS_API_IO_API_KEY")
        names = list(bookmakers or self.bookmakers)
        query: dict[str, object] = {"eventId": event_id}
        if names:
            query["bookmakers"] = ",".join(names)
        payload, _status = self._get("historical/odds", query)
        if not isinstance(payload, dict):
            raise OddsApiIoProviderError("unexpected /historical/odds payload")
        return payload

    # ---------------------------------------------------------------- parsing

    def _parse_event(
        self,
        match: dict[str, object],
        *,
        observed_at: datetime,
        suffix: str,
    ) -> tuple[RawProviderEvent, CanonicalEvent] | None:
        return parse_event_payload(
            match,
            observed_at=observed_at,
            suffix=suffix,
            league_slug=self.league_slug,
        )

    def _parse_odds_payload(
        self,
        payload: dict[str, object],
        *,
        event_external_id: str,
        raw_event_ref: str,
        default_observed_at: datetime,
    ) -> tuple[OddsObservation, ...]:
        return parse_odds_payload(
            payload,
            event_external_id=event_external_id,
            raw_event_ref=raw_event_ref,
            default_observed_at=default_observed_at,
            provider_name=self.provider_name,
        )


__all__ = [
    "OddsApiIoSportsProvider",
    "OddsApiIoProviderError",
    "http_get_json",
    "parse_event_payload",
    "parse_odds_payload",
    "parse_scores",
    "slugify",
]

parse_scores = _parse_scores
slugify = _slugify