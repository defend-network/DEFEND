"""Phase C probe adapters: minimal, evidence-driven provider adapters.

Each adapter owns request construction, authentication injection, endpoint
definitions, pagination, response parsing, and normalization into
:class:`~defend_integrations.probing.CanonicalObservation` records with full
provenance. Adapters stay small until empirical evidence proves a provider is
valuable (P2). Live probing is credential activation, not new engineering.

Providers without a verified endpoint catalog (tabletennisapi, tt-live host,
allscores, allsportsapi2) keep an empty endpoint table and report the reason;
no quota is spent on them until contract evidence shows TT capability (P8).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from .probing import (
    CanonicalObservation,
    ProbeBudget,
    RawEvidence,
    capture_quota,
    classify_error,
    probe_get,
    utc_now_iso,
)

_SM = "https://table-tennis.sportmicro.com"


@dataclass
class PhaseCResult:
    """Outcome of one adapter run: evidence, observations, capability deltas."""

    provider_id: str
    evidence: list[RawEvidence] = field(default_factory=list)
    observations: list[CanonicalObservation] = field(default_factory=list)
    capabilities: dict[str, str] = field(default_factory=dict)
    endpoints: dict[str, dict[str, Any]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "evidence": [e.to_dict() for e in self.evidence],
            "observations": [o.to_dict() for o in self.observations],
            "capabilities": dict(self.capabilities),
            "endpoints": {
                name: dict(detail) for name, detail in self.endpoints.items()
            },
            "notes": list(self.notes),
        }


class PhaseCAdapter(Protocol):
    provider_id: str

    def run(
        self,
        secrets: dict[str, str],
        budget: ProbeBudget,
        evidence_dir: Path,
    ) -> PhaseCResult: ...


def _record_endpoint(
    result: PhaseCResult,
    name: str,
    status_code: int | None,
    error_class: str | None,
    quota: tuple[int | None, str | None],
    note: str = "",
) -> None:
    result.endpoints[name] = {
        "status_code": status_code,
        "error_class": error_class,
        "ok": status_code is not None and 200 <= status_code < 300,
        "remaining_quota": quota[0],
        "quota_reset_at": quota[1],
        "note": note,
    }


# --------------------------------------------------------------------------- #
# OddsPapi (v4)
# --------------------------------------------------------------------------- #


class OddspapiPhaseCAdapter:
    """OddsPapi v4 (api.oddspapi.io). Query-key auth, sportId 25 = TT.

    Historical odds: ``/v4/historical-odds?fixtureId=<id>&bookmakers=<a,b,c>``
    with at most 3 bookmakers (omitting the param returns 400
    TOO_MANY_BOOKMAKERS). Snapshots carry ``createdAt`` - the provider's
    observation timestamp.
    """

    provider_id = "oddspapi"
    base = "https://api.oddspapi.io/v4"

    def __init__(self) -> None:
        self._key = ""

    def _url(self, path: str) -> str:
        sep = "&" if "?" in path else "?"
        return f"{self.base}{path}{sep}apiKey={self._key}"

    def _secrets(self) -> tuple[str, ...]:
        return (self._key,)

    def run(self, secrets, budget, evidence_dir) -> PhaseCResult:
        """Probe the recent 10-day fixtures window (ISO <=10 days per call)."""
        key = secrets.get("ODDSPAPI_API_KEY", "")
        if not key:
            result = PhaseCResult(provider_id=self.provider_id)
            result.notes.append("missing ODDSPAPI_API_KEY")
            return result
        self._key = key
        from_iso = (
            datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=10)
        ).isoformat().replace("+00:00", "Z")
        to_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        result, parsed = self.probe_fixtures(
            budget, evidence_dir, from_iso=from_iso, to_iso=to_iso
        )
        if isinstance(parsed, list):
            tt = [fx for fx in parsed if isinstance(fx, dict) and fx.get("sportId") == 25]
            result.capabilities["tt_fixtures"] = "yes"
            result.capabilities["tt_results"] = "yes"
            result.notes.append(f"fixtures in window: {len(tt)}")
        return result

    def probe_fixtures(
        self,
        budget: ProbeBudget,
        evidence_dir: Path,
        *,
        from_iso: str,
        to_iso: str,
        sport_id: int = 25,
    ) -> tuple[PhaseCResult, Any]:
        result = PhaseCResult(provider_id=self.provider_id)
        if not budget.take():
            result.notes.append("budget exhausted; fixtures not probed")
            return result, None
        url = self._url(
            f"/fixtures?sportId={sport_id}&from={from_iso}&to={to_iso}"
        )
        fetch_result, evidence, parsed = probe_get(
            self.provider_id,
            "fixtures",
            url,
            known_secrets=self._secrets(),
        )
        evidence_path = evidence.save(evidence_dir)
        result.evidence.append(evidence)
        _record_endpoint(
            result,
            "fixtures",
            fetch_result.status_code,
            classify_error(fetch_result.status_code, evidence.body),
            (None, None),
        )
        return result, parsed

    def probe_historical(
        self,
        budget: ProbeBudget,
        evidence_dir: Path,
        *,
        fixture_id: str,
        bookmakers: list[str],
        commence_at: str | None = None,
    ) -> tuple[PhaseCResult, list[CanonicalObservation]]:
        """One historical-odds call (<=3 bookmakers) -> observations."""
        result = PhaseCResult(provider_id=self.provider_id)
        if not bookmakers or len(bookmakers) > 3:
            result.notes.append(
                "bookmakers param required, 1..3 values (provider contract)"
            )
            return result, []
        if not budget.take():
            result.notes.append("budget exhausted; historical odds not probed")
            return result, []
        url = self._url(
            f"/historical-odds?fixtureId={fixture_id}"
            f"&bookmakers={','.join(bookmakers)}"
        )
        fetch_result, evidence, parsed = probe_get(
            self.provider_id,
            "historical-odds",
            url,
            known_secrets=self._secrets(),
        )
        evidence_path = evidence.save(evidence_dir)
        result.evidence.append(evidence)
        error_class = classify_error(fetch_result.status_code, evidence.body)
        quota = (None, None)
        _record_endpoint(
            result,
            f"historical-odds:{fixture_id}",
            fetch_result.status_code,
            error_class,
            quota,
        )
        observations = (
            parse_oddspapi_historical(
                parsed,
                provider="oddspapi",
                fixture_id=fixture_id,
                raw_evidence_ref=str(evidence_path),
                commence_at=commence_at,
                ingested_at=utc_now_iso(),
            )
            if fetch_result.ok and isinstance(parsed, dict)
            else []
        )
        result.observations.extend(observations)
        return result, observations


def parse_oddspapi_historical(
    payload: dict[str, Any],
    *,
    provider: str,
    fixture_id: str,
    raw_evidence_ref: str,
    commence_at: str | None,
    ingested_at: str,
) -> list[CanonicalObservation]:
    """Normalize one /v4/historical-odds payload (P3 boundary).

    Shape (empirically verified 2026-08-20):
    {fixtureId, bookmakers: {name: {markets: {mid: {outcomes: {oid: {
      players: {key: [{createdAt, price, limit, active, exchangeMeta}]}}}}}}}}
    """
    observations: list[CanonicalObservation] = []
    bookmakers = payload.get("bookmakers")
    if not isinstance(bookmakers, dict):
        return observations
    for bookmaker, bm_body in bookmakers.items():
        markets = bm_body.get("markets") if isinstance(bm_body, dict) else None
        if not isinstance(markets, dict):
            continue
        for market_id, market in markets.items():
            outcomes = market.get("outcomes") if isinstance(market, dict) else None
            if not isinstance(outcomes, dict):
                continue
            for outcome_id, outcome in outcomes.items():
                players = (
                    outcome.get("players") if isinstance(outcome, dict) else None
                )
                if not isinstance(players, dict):
                    continue
                for player_key, snapshots in players.items():
                    if not isinstance(snapshots, list):
                        continue
                    for snapshot in snapshots:
                        if not isinstance(snapshot, dict):
                            continue
                        observed_at = snapshot.get("createdAt")
                        if not isinstance(observed_at, str):
                            continue
                        price = snapshot.get("price")
                        observations.append(
                            CanonicalObservation(
                                provider=provider,
                                provider_event_id=fixture_id,
                                provider_bookmaker=str(bookmaker),
                                provider_market_id=str(market_id),
                                provider_outcome_id=str(outcome_id),
                                raw_evidence_ref=raw_evidence_ref,
                                observed_at=observed_at,
                                commence_at=commence_at,
                                ingested_at=ingested_at,
                                price=float(price) if isinstance(price, (int, float)) else None,
                                active=snapshot.get("active"),
                                participant_key=str(player_key),
                            )
                        )
    return observations


# --------------------------------------------------------------------------- #
# The Odds API (v4) - no TT coverage (empirically verified)
# --------------------------------------------------------------------------- #


class TheOddsApiPhaseCAdapter:
    """The Odds API v4. 2026-08-20 probe: no table tennis sport key exists;
    175 sports, /table_tennis/* returns 404 UNKNOWN_SPORT. Classified
    UNSUPPORTED_FOR_TT; a single sports-list call re-verifies cheaply."""

    provider_id = "the_odds_api"
    base = "https://api.the-odds-api.com/v4"

    def run(self, secrets, budget, evidence_dir) -> PhaseCResult:
        result = PhaseCResult(provider_id=self.provider_id)
        key = secrets.get("THE_ODDS_API_KEY", "")
        if not key:
            result.notes.append("missing THE_ODDS_API_KEY")
            return result
        if not budget.take():
            result.notes.append("budget exhausted")
            return result
        url = f"{self.base}/sports/?apiKey={key}"
        fetch_result, evidence, parsed = probe_get(
            self.provider_id,
            "sports",
            url,
            known_secrets=(key,),
            quota_headers=("x-requests-remaining", "x-requests-used"),
        )
        evidence_path = evidence.save(evidence_dir)
        result.evidence.append(evidence)
        quota = capture_quota(
            fetch_result.headers, ("x-requests-remaining", "x-requests-used")
        )
        _record_endpoint(result, "sports", fetch_result.status_code,
                         classify_error(fetch_result.status_code, evidence.body), quota)
        if fetch_result.ok and isinstance(parsed, list):
            tt_keys = [
                s.get("key")
                for s in parsed
                if isinstance(s, dict) and "table" in str(s.get("key", "")).lower()
            ]
            result.capabilities["tt_results"] = (
                "yes" if tt_keys else "no"
            )
            result.notes.append(
                "UNSUPPORTED_FOR_TT" if not tt_keys else f"tt keys: {tt_keys}"
            )
            result.capabilities["tt_odds"] = "no"
            result.capabilities["tt_live_odds"] = "no"
            result.capabilities["tt_historical_odds"] = "no"
        return result


# --------------------------------------------------------------------------- #
# Odds-API.io (v4)
# --------------------------------------------------------------------------- #


class OddsApiIoPhaseCAdapter:
    """Odds-API.io. Query-key auth. /v4/sports returns 404 (verified
    2026-08-20); the working sports path is /v3/sports (same as the health
    adapter). TT presence decided by the sports list."""

    provider_id = "odds_api_io"
    base = "https://api.odds-api.io/v3"

    def run(self, secrets, budget, evidence_dir) -> PhaseCResult:
        result = PhaseCResult(provider_id=self.provider_id)
        key = secrets.get("ODDS_API_IO_API_KEY", "")
        if not key:
            result.notes.append("missing ODDS_API_IO_API_KEY")
            return result
        if not budget.take():
            result.notes.append("budget exhausted")
            return result
        url = f"{self.base}/sports?apiKey={key}"
        fetch_result, evidence, parsed = probe_get(
            self.provider_id,
            "sports",
            url,
            known_secrets=(key,),
            quota_headers=("x-ratelimit-remaining", "ratelimit-remaining"),
        )
        evidence_path = evidence.save(evidence_dir)
        result.evidence.append(evidence)
        quota = capture_quota(
            fetch_result.headers, ("x-ratelimit-remaining", "ratelimit-remaining")
        )
        _record_endpoint(result, "sports", fetch_result.status_code,
                         classify_error(fetch_result.status_code, evidence.body), quota)
        if fetch_result.ok and isinstance(parsed, list):
            tt = [
                s for s in parsed
                if isinstance(s, dict)
                and (
                    s.get("sportId") == 25
                    or "table" in str(s.get("slug", s.get("sportName", ""))).lower()
                )
            ]
            if tt:
                result.capabilities["tt_results"] = "yes"
                result.notes.append(f"TT sport present: {tt[0]}")
            else:
                result.capabilities["tt_results"] = "no"
                result.notes.append("no TT sport entry in sports list")
        return result


# --------------------------------------------------------------------------- #
# SportsGameOdds (v2)
# --------------------------------------------------------------------------- #


class SportsGameOddsPhaseCAdapter:
    """SportsGameOdds v2 (api.sportsgameodds.com/v2). Header x-api-key auth,
    cursor pagination via ``nextCursor``. Event.odds.<oddID>.byBookmaker holds
    bookmaker snapshots; whether history beyond the current snapshot exists
    is an empirical question, not a schema inference (P7)."""

    provider_id = "sports_game_odds"
    base = "https://api.sportsgameodds.com/v2"

    def _headers(self, key: str) -> dict[str, str]:
        return {"x-api-key": key, "Accept": "application/json"}

    def run(self, secrets, budget, evidence_dir) -> PhaseCResult:
        result = PhaseCResult(provider_id=self.provider_id)
        key = secrets.get("SPORTS_GAME_ODDS_API_KEY", "")
        if not key:
            result.notes.append("missing SPORTS_GAME_ODDS_API_KEY")
            return result
        if not budget.take():
            result.notes.append("budget exhausted")
            return result
        url = f"{self.base}/sports"
        fetch_result, evidence, parsed = probe_get(
            self.provider_id,
            "sports",
            url,
            headers=self._headers(key),
            known_secrets=(key,),
            quota_headers=(),
        )
        evidence_path = evidence.save(evidence_dir)
        result.evidence.append(evidence)
        _record_endpoint(result, "sports", fetch_result.status_code,
                         classify_error(fetch_result.status_code, evidence.body), (None, None))
        if fetch_result.ok and isinstance(parsed, dict):
            data = parsed.get("data")
            if isinstance(data, list):
                tt = [
                    s for s in data
                    if isinstance(s, dict)
                    and "table" in str(s.get("name") or s.get("sportID", "")).lower()
                ]
                result.notes.append(
                    "TT sport entry: "
                    + (str(tt[0]) if tt else "none in /sports response")
                )
                if tt:
                    result.capabilities["tt_results"] = "pending"
        return result

    def probe_events(
        self,
        secrets: dict[str, str],
        budget: ProbeBudget,
        evidence_dir: Path,
        *,
        league_ids: list[str],
        max_pages: int = 3,
    ) -> PhaseCResult:
        """Cursor-paginated /events probe for the given leagues."""
        result = PhaseCResult(provider_id=self.provider_id)
        key = secrets.get("SPORTS_GAME_ODDS_API_KEY", "")
        if not key:
            result.notes.append("missing SPORTS_GAME_ODDS_API_KEY")
            return result
        cursor: str | None = None
        for page in range(max_pages):
            if not budget.take():
                result.notes.append("budget exhausted")
                break
            query = f"leagueID={','.join(league_ids)}&limit=50"
            if cursor:
                query += f"&cursor={cursor}"
            url = f"{self.base}/events?{query}"
            fetch_result, evidence, parsed = probe_get(
                self.provider_id,
                f"events:page{page}",
                url,
                headers=self._headers(key),
                known_secrets=(key,),
                quota_headers=(),
            )
            evidence_path = evidence.save(evidence_dir)
            result.evidence.append(evidence)
            _record_endpoint(result, f"events:page{page}",
                             fetch_result.status_code,
                             classify_error(fetch_result.status_code, evidence.body), (None, None))
            if not (fetch_result.ok and isinstance(parsed, dict)):
                break
            data = parsed.get("data")
            if isinstance(data, list):
                result.notes.append(f"page {page}: {len(data)} events")
                result.capabilities["tt_results"] = "pending"
            cursor = parsed.get("nextCursor")
            if not isinstance(cursor, str) or not cursor:
                break
        return result

    def probe_usage(self, secrets, budget, evidence_dir) -> PhaseCResult:
        result = PhaseCResult(provider_id=self.provider_id)
        key = secrets.get("SPORTS_GAME_ODDS_API_KEY", "")
        if not key or not budget.take():
            result.notes.append("budget exhausted or missing key")
            return result
        url = f"{self.base}/account/usage"
        fetch_result, evidence, parsed = probe_get(
            self.provider_id,
            "account-usage",
            url,
            headers=self._headers(key),
            known_secrets=(key,),
            quota_headers=(),
        )
        evidence_path = evidence.save(evidence_dir)
        result.evidence.append(evidence)
        quota = capture_quota(None, (), parsed, "data")
        _record_endpoint(result, "account-usage", fetch_result.status_code,
                         classify_error(fetch_result.status_code, evidence.body), quota)
        return result


# --------------------------------------------------------------------------- #
# Sportradar Table Tennis v2 (trial)
# --------------------------------------------------------------------------- #


class SportradarTTPhaseCAdapter:
    """Sportradar TT v2 trial (api.sportradar.com/tabletennis/trial/v2).

    JSON via ``.json`` extension + ``api_key`` query param (Sportradar General
    Sport API convention). Feeds of interest (P6): competitions (no ID
    needed), daily summaries (date), season probabilities (2-way match win
    prob = PROVIDER_PREDICTION, never bookmaker odds), rankings, H2H.
    """

    provider_id = "sportradar_tt"
    trial = "https://api.sportradar.com/tabletennis/trial/v2"

    def _url(self, key: str, path: str) -> str:
        return f"{self.trial}/{path}.json?api_key={key}"

    def run(self, secrets, budget, evidence_dir) -> PhaseCResult:
        result = PhaseCResult(provider_id=self.provider_id)
        key = secrets.get("SPORTRADAR_API_KEY", "")
        if not key:
            result.notes.append("missing SPORTRADAR_API_KEY")
            return result
        if not budget.take():
            result.notes.append("budget exhausted")
            return result
        url = self._url(key, "competitions")
        fetch_result, evidence, parsed = probe_get(
            self.provider_id,
            "competitions",
            url,
            known_secrets=(key,),
        )
        evidence_path = evidence.save(evidence_dir)
        result.evidence.append(evidence)
        _record_endpoint(result, "competitions", fetch_result.status_code,
                         classify_error(fetch_result.status_code, evidence.body), (None, None))
        if fetch_result.ok and isinstance(parsed, dict):
            competitions = parsed.get("competitions")
            if isinstance(competitions, list):
                result.capabilities["tt_fixtures"] = "yes"
                result.notes.append(f"competitions: {len(competitions)}")
                for comp in competitions[:5]:
                    if isinstance(comp, dict):
                        result.notes.append(
                            f"  competition id={comp.get('id')} "
                            f"name={comp.get('name')}"
                        )
        return result

    def probe_daily_summaries(
        self,
        secrets,
        budget,
        evidence_dir,
        *,
        date: str,
    ) -> PhaseCResult:
        result = PhaseCResult(provider_id=self.provider_id)
        key = secrets.get("SPORTRADAR_API_KEY", "")
        if not key or not budget.take():
            result.notes.append("budget exhausted or missing key")
            return result
        url = self._url(key, f"schedules/{date}/summaries")
        fetch_result, evidence, parsed = probe_get(
            self.provider_id,
            f"daily-summaries:{date}",
            url,
            known_secrets=(key,),
        )
        evidence_path = evidence.save(evidence_dir)
        result.evidence.append(evidence)
        _record_endpoint(result, f"daily-summaries:{date}",
                         fetch_result.status_code,
                         classify_error(fetch_result.status_code, evidence.body), (None, None))
        if fetch_result.ok and isinstance(parsed, dict):
            summaries = parsed.get("summaries")
            if isinstance(summaries, list):
                result.capabilities["tt_results"] = "yes"
                result.notes.append(f"daily summaries: {len(summaries)} events")
        return result

    def probe_season_probabilities(
        self,
        secrets,
        budget,
        evidence_dir,
        *,
        season_id: str,
    ) -> PhaseCResult:
        """Season Probabilities = PROVIDER_PREDICTION source (P6). Never odds."""
        result = PhaseCResult(provider_id=self.provider_id)
        key = secrets.get("SPORTRADAR_API_KEY", "")
        if not key or not budget.take():
            result.notes.append("budget exhausted or missing key")
            return result
        url = self._url(key, f"seasons/{season_id}/probabilities")
        fetch_result, evidence, parsed = probe_get(
            self.provider_id,
            f"season-probabilities:{season_id}",
            url,
            known_secrets=(key,),
        )
        evidence_path = evidence.save(evidence_dir)
        result.evidence.append(evidence)
        _record_endpoint(result, f"season-probabilities:{season_id}",
                         fetch_result.status_code,
                         classify_error(fetch_result.status_code, evidence.body), (None, None))
        if fetch_result.ok and isinstance(parsed, dict):
            probabilities = parsed.get("probabilities")
            if isinstance(probabilities, list):
                result.capabilities["tt_probabilities"] = "yes"
                result.notes.append(
                    f"season probabilities: {len(probabilities)} sport events "
                    "(PROVIDER_PREDICTION, not bookmaker odds)"
                )
        return result


# --------------------------------------------------------------------------- #
# RapidAPI (shared RAPIDAPI_KEY; X-RapidAPI-Key + X-RapidAPI-Host)
# --------------------------------------------------------------------------- #


@dataclass
class RapidEndpoint:
    name: str
    path: str
    params: dict[str, str] = field(default_factory=dict)


class RapidApiPhaseCAdapter:
    """One shared credential (RAPIDAPI_KEY), per-host endpoint tables (P1).

    Endpoint tables come from contract evidence only. Hosts without a
    verified catalog keep an empty table; run() reports the reason and
    spends no quota (P8).
    """

    def __init__(self, provider_id: str, host: str, endpoints: list[RapidEndpoint]) -> None:
        self.provider_id = provider_id
        self.host = host
        self.endpoints = endpoints

    def _headers(self, key: str) -> dict[str, str]:
        return {
            "X-RapidAPI-Key": key,
            "X-RapidAPI-Host": self.host,
            "Accept": "application/json",
        }

    def run(self, secrets, budget, evidence_dir) -> PhaseCResult:
        result = PhaseCResult(provider_id=self.provider_id)
        key = secrets.get("RAPIDAPI_KEY", "")
        if not key:
            result.notes.append("missing RAPIDAPI_KEY (shared credential)")
            return result
        if not self.endpoints:
            result.notes.append(
                "endpoint catalog UNVERIFIED; no quota spent (P8)"
            )
            return result
        for endpoint in self.endpoints:
            if not budget.take():
                result.notes.append("budget exhausted")
                break
            query = "&".join(f"{k}={v}" for k, v in endpoint.params.items())
            url = f"https://{self.host}{endpoint.path}"
            if query:
                url += f"?{query}"
            fetch_result, evidence, parsed = probe_get(
                self.provider_id,
                endpoint.name,
                url,
                headers=self._headers(key),
                known_secrets=(key,),
            )
            evidence_path = evidence.save(evidence_dir)
            result.evidence.append(evidence)
            _record_endpoint(
                result,
                endpoint.name,
                fetch_result.status_code,
                classify_error(fetch_result.status_code, evidence.body),
                (None, None),
            )
            if fetch_result.ok and isinstance(parsed, (dict, list)):
                result.capabilities[endpoint.name] = "yes"
        return result


def rapid_adapters() -> dict[str, RapidApiPhaseCAdapter]:
    """Endpoint tables derived from contract evidence (Phase B)."""
    return {
        "rapidapi_tt_micro": RapidApiPhaseCAdapter(
            "rapidapi_tt_micro",
            "table-tennis-micro.p.rapidapi.com",
            [
                RapidEndpoint("matches-by-date", "/matches-by-date",
                              {"date": "{date}"}),
                RapidEndpoint("matches-live", "/matches-live"),
                RapidEndpoint("standings", "/standings"),
                RapidEndpoint("teams", "/teams"),
                RapidEndpoint("odds-coverage", "/odds/coverage"),
                RapidEndpoint("odds-bookmakers", "/odds/bookmakers"),
            ],
        ),
        "rapidapi_tabletennis": RapidApiPhaseCAdapter(
            "rapidapi_tabletennis", "tabletennisapi.p.rapidapi.com", []
        ),
        "rapidapi_allscores": RapidApiPhaseCAdapter(
            "rapidapi_allscores", "allscores.p.rapidapi.com", []
        ),
        "rapidapi_allsportsapi2": RapidApiPhaseCAdapter(
            "rapidapi_allsportsapi2", "allsportsapi2.p.rapidapi.com", []
        ),
        "rapidapi_tt_live": RapidApiPhaseCAdapter(
            "rapidapi_tt_live",
            "table-tennis-api-live-scores-stats-odds-predictions.p.rapidapi.com",
            [],
        ),
    }


PHASE_C_ADAPTERS: dict[str, PhaseCAdapter] = {
    **{
        "oddspapi": OddspapiPhaseCAdapter(),
        "the_odds_api": TheOddsApiPhaseCAdapter(),
        "odds_api_io": OddsApiIoPhaseCAdapter(),
        "sports_game_odds": SportsGameOddsPhaseCAdapter(),
        "sportradar_tt": SportradarTTPhaseCAdapter(),
    },
    **rapid_adapters(),
}


def phase_c_adapter_for(provider_id: str) -> PhaseCAdapter | None:
    return PHASE_C_ADAPTERS.get(provider_id)