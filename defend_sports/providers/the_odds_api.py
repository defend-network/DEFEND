"""Table tennis events, odds and live state from The Odds API.

Network provider: polls The Odds API v4 (sports list, h2h odds, scores)
and maps the responses into canonical DEFEND Sports models. Only real
API data is emitted: HTTP failures surface as provider errors (recorded
UNAVAILABLE downstream) and missing credentials must be reported by the
caller before polling (UNCONFIGURED).
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable

from defend_markets.feeds import FeedError, http_get_json as _markets_http_get_json

from defend_sports.domain import (
    CanonicalEvent,
    LiveObservation,
    OddsObservation,
    SourceRef,
)
from defend_sports.providers.base import ProviderBatch, RawProviderEvent, SportsProvider

_TT_SPORT_KEY_HINTS = ("tabletennis", "table_tennis", "pingpong")

_ODDS_API_BASE = "https://api.the-odds-api.com/v4/sports"


class OddsApiProviderError(Exception):
    """The Odds API poll failure carrying a human detail."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def http_get_json(url: str) -> tuple[object, int]:
    try:
        return _markets_http_get_json(url)
    except FeedError as error:
        raise OddsApiProviderError(error.detail) from None


def _parse_commence_time(value: object) -> datetime | None:
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


def _normalize_outcome_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in ("home", "away"):
        return normalized
    return None


@dataclass(frozen=True)
class TheOddsApiSportsProvider:
    """Polls The Odds API for live table-tennis events, h2h odds and scores.

    ``sport_keys`` may pin explicit sport keys; by default the provider
    discovers table-tennis keys from the sports list endpoint. ``http_get``
    is injectable for tests.
    """

    provider_name: str = "the_odds_api"
    api_key: str = field(default="")
    sport_keys: tuple[str, ...] = ()
    http_get: Callable[[str], tuple[object, int]] = field(default=http_get_json)
    clock: Callable[[], datetime] = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def poll(self) -> ProviderBatch:
        if not self.api_key.strip():
            raise OddsApiProviderError("missing THE_ODDS_API_KEY")
        sport_keys = self.sport_keys or self._discover_sport_keys()
        if not sport_keys:
            return ProviderBatch()
        now = self.clock()
        suffix = now.strftime("%Y%m%dT%H%M%SZ")

        raw_events: list[RawProviderEvent] = []
        events: list[CanonicalEvent] = []
        odds: list[OddsObservation] = []
        by_match_id: dict[str, tuple[str, str]] = {}

        failures: list[str] = []
        parsed_any = False
        for sport_key in sport_keys:
            try:
                payload, _status = self._odds_for(sport_key)
            except OddsApiProviderError as error:
                failures.append(f"{sport_key}: {error.detail}")
                continue
            parsed_any = True
            for match in payload:
                if not isinstance(match, dict):
                    continue
                parsed = self._parse_match(match, sport_key, now, suffix)
                if parsed is None:
                    continue
                raw_event, event, match_odds, raw_ref = parsed
                raw_events.append(raw_event)
                events.append(event)
                odds.extend(match_odds)
                by_match_id[str(match.get("id"))] = (sport_key, raw_ref)

        if failures and not parsed_any:
            raise OddsApiProviderError("; ".join(failures))

        live = self._live_for(sport_keys, by_match_id, now, suffix)
        return ProviderBatch(
            raw_events=tuple(raw_events),
            events=tuple(events),
            live=live,
            odds=tuple(odds),
        )

    def _discover_sport_keys(self) -> tuple[str, ...]:
        payload, _status = self.http_get(
            f"{_ODDS_API_BASE}/?apiKey={urllib.parse.quote(self.api_key)}"
        )
        if not isinstance(payload, list):
            raise OddsApiProviderError("unexpected sports list payload")
        keys = {
            str(entry["key"])
            for entry in payload
            if isinstance(entry, dict)
            and isinstance(entry.get("key"), str)
            and any(hint in str(entry.get("key", "")).lower() for hint in _TT_SPORT_KEY_HINTS)
        }
        return tuple(sorted(keys))

    def _odds_for(self, sport_key: str) -> tuple[list[object], int]:
        url = (
            f"{_ODDS_API_BASE}/{urllib.parse.quote(sport_key)}/odds/"
            f"?apiKey={urllib.parse.quote(self.api_key)}"
            "&regions=eu&markets=h2h&oddsFormat=decimal"
        )
        payload, status = self.http_get(url)
        if not isinstance(payload, list):
            raise OddsApiProviderError(f"unexpected odds payload for {sport_key}")
        return payload, status

    def _scores_for(self, sport_key: str) -> tuple[list[object], int]:
        url = (
            f"{_ODDS_API_BASE}/{urllib.parse.quote(sport_key)}/scores/"
            f"?daysFrom=1&apiKey={urllib.parse.quote(self.api_key)}"
        )
        payload, status = self.http_get(url)
        if not isinstance(payload, list):
            raise OddsApiProviderError(f"unexpected scores payload for {sport_key}")
        return payload, status

    def _parse_match(
        self,
        match: dict[str, object],
        sport_key: str,
        now: datetime,
        suffix: str,
    ) -> tuple[RawProviderEvent, CanonicalEvent, tuple[OddsObservation, ...], str] | None:
        match_id = str(match.get("id") or "")
        home = str(match.get("home_team") or "").strip()
        away = str(match.get("away_team") or "").strip()
        if not match_id or not home or not away:
            return None
        raw_ref = f"{sport_key}:{match_id}@{suffix}"
        raw_event = RawProviderEvent(
            source=SourceRef(provider=self.provider_name, external_id=sport_key),
            provider_event_id=raw_ref,
            payload=dict(match),
            observed_at=now,
            display_name="The Odds API",
        )
        event = CanonicalEvent(
            event_external_id=match_id,
            sport_key="table_tennis",
            league_key=sport_key,
            display_name=f"{home} vs {away}",
            scheduled_at=_parse_commence_time(match.get("commence_time")),
            raw_event_ref=raw_ref,
        )
        match_odds: list[OddsObservation] = []
        bookmakers = match.get("bookmakers")
        if isinstance(bookmakers, list):
            for bookmaker in bookmakers:
                if not isinstance(bookmaker, dict):
                    continue
                book_key = str(bookmaker.get("key") or "").strip()
                if not book_key:
                    continue
                markets = bookmaker.get("markets")
                if not isinstance(markets, list):
                    continue
                for market in markets:
                    if not isinstance(market, dict) or str(market.get("key") or "") != "h2h":
                        continue
                    outcomes = market.get("outcomes")
                    if not isinstance(outcomes, list):
                        continue
                    for outcome in outcomes:
                        if not isinstance(outcome, dict):
                            continue
                        selection = _normalize_outcome_name(outcome.get("name"))
                        odds_value = _parse_decimal_odds(outcome.get("price"))
                        if selection is None or odds_value is None:
                            continue
                        match_odds.append(
                            OddsObservation(
                                source=SourceRef(
                                    provider=self.provider_name, external_id=book_key
                                ),
                                event_external_id=match_id,
                                market_key="match_winner",
                                selection_key=selection,
                                decimal_odds=odds_value,
                                observed_at=now,
                                raw_event_ref=raw_ref,
                            )
                        )
        return raw_event, event, tuple(match_odds), raw_ref

    def _live_for(
        self,
        sport_keys: tuple[str, ...],
        by_match_id: dict[str, tuple[str, str]],
        now: datetime,
        suffix: str,
    ) -> tuple[LiveObservation, ...]:
        live: list[LiveObservation] = []
        for sport_key in sport_keys:
            try:
                payload, _status = self._scores_for(sport_key)
            except OddsApiProviderError:
                continue
            for match in payload:
                if not isinstance(match, dict):
                    continue
                match_id = str(match.get("id") or "")
                if match_id not in by_match_id or bool(match.get("completed")):
                    continue
                scores = match.get("scores")
                if not isinstance(scores, list) or not scores:
                    continue
                score_rows = [
                    [str(entry.get("name") or ""), str(entry.get("score") or "")]
                    for entry in scores
                    if isinstance(entry, dict)
                ]
                live.append(
                    LiveObservation(
                        source=SourceRef(provider=self.provider_name, external_id=sport_key),
                        event_external_id=match_id,
                        state={
                            "status": "live",
                            "sport": "table_tennis",
                            "scores": score_rows,
                        },
                        observed_at=now,
                        raw_event_ref=by_match_id[match_id][1],
                    )
                )
        return tuple(live)


__all__ = ["TheOddsApiSportsProvider", "OddsApiProviderError", "http_get_json"]