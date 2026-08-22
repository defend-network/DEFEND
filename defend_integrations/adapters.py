"""Provider health adapters.

Eight providers have *real, read-only* health adapters (Vast, Hugging Face,
FRED, Congress.gov, The Odds API, SEC EDGAR, World Bank, Polymarket). Every
other registry entry uses the explicit placeholder adapter, which reports
ADAPTER NOT IMPLEMENTED and never claims HEALTHY.

All HTTP discipline (timeout, retry/backoff, size caps, sanitization) is
handled by :mod:`defend_integrations.http`; adapters only declare endpoints,
headers, and success predicates.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Protocol
from urllib.parse import quote

from .http import FetchResult, fetch
from .models import (
    AdapterKind,
    AdapterProbe,
    ProviderDefinition,
)

_KNOWN_UA = (
    "DEFEND Integration Control Plane (setup probe; "
    "chairman@defend-network.org)"
)

_PLACEHOLDER_DETAIL = "ADAPTER NOT IMPLEMENTED"


class HealthAdapter(Protocol):
    provider_id: str

    def probe(
        self,
        definition: ProviderDefinition,
        secrets: dict[str, str],
        config: dict[str, str],
    ) -> AdapterProbe: ...


def _quota_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _quota_parse(value: object) -> int | None:
    if isinstance(value, bool) or isinstance(value, int):
        return _quota_int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


class _BaseAdapter:
    provider_id: str = ""

    def _probe(
        self,
        url: str,
        secrets: dict[str, str],
        *,
        headers: dict[str, str] | None = None,
        timeout_seconds: float = 10.0,
        success_predicate=None,
        known_secrets: tuple[str, ...] = (),
        quota_headers: tuple[str, ...] = (),
        quota_body_path: str | None = None,
        quota_reset_header: str | None = None,
    ) -> AdapterProbe:
        result: FetchResult = fetch(
            url,
            timeout_seconds=timeout_seconds,
            headers=headers,
            retries=2,
            backoff_seconds=1.0,
            known_secrets=known_secrets,
        )
        detail = self._detail_from_result(result)
        if not result.ok:
            return AdapterProbe(
                ok=False,
                status_code=result.status_code,
                latency_ms=result.latency_ms,
                detail=detail,
                authenticated=None,
            )
        body = json.loads(result.body) if result.body else None
        ok = success_predicate(body) if success_predicate else True
        remaining_quota: int | None = None
        quota_reset_at: str | None = None
        if result.headers:
            for header_name in quota_headers:
                raw = result.headers.get(header_name)
                parsed = _quota_parse(raw)
                if parsed is not None:
                    remaining_quota = parsed
                    break
        if quota_body_path and isinstance(body, dict):
            node: object = body
            for part in quota_body_path.split("."):
                if isinstance(node, dict):
                    node = node.get(part)
                else:
                    node = None
                    break
            if isinstance(node, dict):
                parsed = _quota_parse(node.get("remaining_quota"))
                if parsed is not None:
                    remaining_quota = parsed
                reset = node.get("quota_reset_at")
                quota_reset_at = reset if isinstance(reset, str) else None
        if quota_reset_header and result.headers:
            reset = result.headers.get(quota_reset_header)
            quota_reset_at = reset if isinstance(reset, str) else None
        return AdapterProbe(
            ok=ok,
            status_code=result.status_code,
            latency_ms=result.latency_ms,
            detail=detail,
            authenticated=True,
            remaining_quota=remaining_quota,
            quota_reset_at=quota_reset_at,
        )

    @staticmethod
    def _detail_from_result(result: FetchResult) -> str:
        if result.ok:
            return "reachable"
        if result.status_code == 429:
            return "rate limited"
        if result.status_code in (401, 403):
            return "authentication failed"
        if result.status_code is not None:
            return f"status {result.status_code}"
        return result.error_type or "unreachable"

    def probe(
        self,
        definition: ProviderDefinition,
        secrets: dict[str, str],
        config: dict[str, str],
    ) -> AdapterProbe:
        raise NotImplementedError


class PlaceholderAdapter:
    """Explicit placeholder: never claims a real health result."""

    provider_id = "__placeholder__"

    def probe(
        self,
        definition: ProviderDefinition,
        secrets: dict[str, str],
        config: dict[str, str],
    ) -> AdapterProbe:
        return AdapterProbe(
            ok=False,
            status_code=None,
            latency_ms=0,
            detail=_PLACEHOLDER_DETAIL,
            authenticated=None,
        )


class VastAdapter(_BaseAdapter):
    provider_id = "vast"

    def probe(self, definition, secrets, config) -> AdapterProbe:
        key = secrets.get("VAST_API_KEY", "")
        if not key:
            return AdapterProbe(
                ok=False, status_code=None, latency_ms=0,
                detail="missing VAST_API_KEY", authenticated=None,
            )
        return self._probe(
            "https://console.vast.ai/api/v0/users/current/",
            secrets,
            headers={"Authorization": f"Bearer {key}"},
            success_predicate=lambda body: isinstance(body, dict)
            and "id" in body,
            known_secrets=(key,),
        )


class HuggingFaceAdapter(_BaseAdapter):
    provider_id = "huggingface"

    def probe(self, definition, secrets, config) -> AdapterProbe:
        token = secrets.get("HF_TOKEN", "")
        if not token:
            return AdapterProbe(
                ok=False, status_code=None, latency_ms=0,
                detail="missing HF_TOKEN", authenticated=None,
            )
        return self._probe(
            "https://huggingface.co/api/whoami-v2",
            secrets,
            headers={"Authorization": f"Bearer {token}"},
            success_predicate=lambda body: isinstance(body, dict)
            and "name" in body,
            known_secrets=(token,),
        )


class FredAdapter(_BaseAdapter):
    provider_id = "fred"

    def probe(self, definition, secrets, config) -> AdapterProbe:
        key = secrets.get("FRED_API_KEY", "")
        if not key:
            return AdapterProbe(
                ok=False, status_code=None, latency_ms=0,
                detail="missing FRED_API_KEY", authenticated=None,
            )
        url = (
            "https://api.stlouisfed.org/fred/series"
            "?series_id=GDPC1&file_type=json&api_key=" + key
        )
        return self._probe(
            url,
            secrets,
            success_predicate=lambda body: isinstance(body, dict)
            and isinstance(body.get("seriess"), list)
            and len(body["seriess"]) == 1,
            known_secrets=(key,),
        )


class CongressGovAdapter(_BaseAdapter):
    provider_id = "congress_gov"

    def probe(self, definition, secrets, config) -> AdapterProbe:
        key = secrets.get("CONGRESS_API_KEY", "")
        if not key:
            return AdapterProbe(
                ok=False, status_code=None, latency_ms=0,
                detail="missing CONGRESS_API_KEY", authenticated=None,
            )
        url = (
            "https://api.congress.gov/v3/bill"
            f"?limit=1&format=json&api_key={key}"
        )
        return self._probe(
            url,
            secrets,
            headers={"User-Agent": _KNOWN_UA},
            success_predicate=lambda body: isinstance(body, dict)
            and isinstance(body.get("bills"), list),
            known_secrets=(key,),
        )


class OddsApiAdapter(_BaseAdapter):
    provider_id = "the_odds_api"

    def probe(self, definition, secrets, config) -> AdapterProbe:
        key = secrets.get("THE_ODDS_API_KEY", "")
        if not key:
            return AdapterProbe(
                ok=False, status_code=None, latency_ms=0,
                detail="missing THE_ODDS_API_KEY", authenticated=None,
            )
        url = f"https://api.the-odds-api.com/v4/sports/?apiKey={key}"
        return self._probe(
            url,
            secrets,
            success_predicate=lambda body: isinstance(body, list),
            known_secrets=(key,),
            quota_headers=(
                "x-requests-remaining",
                "x-requests-used",
            ),
            quota_reset_header="x-requests-last",
        )


class OddsApiIoAdapter(_BaseAdapter):
    provider_id = "odds_api_io"

    def probe(self, definition, secrets, config) -> AdapterProbe:
        key = secrets.get("ODDS_API_IO_API_KEY", "")
        if not key:
            return AdapterProbe(
                ok=False, status_code=None, latency_ms=0,
                detail="missing ODDS_API_IO_API_KEY", authenticated=None,
            )
        url = f"https://api.odds-api.io/v3/sports?apiKey={key}"
        result = fetch(
            url,
            timeout_seconds=10.0,
            headers={"User-Agent": _KNOWN_UA, "Accept": "application/json"},
            retries=2,
            backoff_seconds=1.0,
            known_secrets=(key,),
        )
        if not result.ok:
            return AdapterProbe(
                ok=False,
                status_code=result.status_code,
                latency_ms=result.latency_ms,
                detail=self._detail_from_result(result),
                authenticated=None,
            )
        body = json.loads(result.body) if result.body else None
        if not isinstance(body, list):
            return AdapterProbe(
                ok=False,
                status_code=result.status_code,
                latency_ms=result.latency_ms,
                detail="authenticated response did not contain a sports list",
                authenticated=True,
                coverage_state="UNKNOWN",
            )

        tt_present = any(
            isinstance(sport, dict)
            and (
                str(sport.get("slug") or "").casefold() == "table-tennis"
                or str(sport.get("name") or "").casefold() == "table tennis"
            )
            for sport in body
        )
        coverage_state = "UNKNOWN"
        coverage_detail = "table_tennis_present=" + str(tt_present).lower()
        selected_url = f"https://api.odds-api.io/v3/bookmakers/selected?apiKey={key}"
        selected_result = fetch(
            selected_url,
            timeout_seconds=10.0,
            headers={"User-Agent": _KNOWN_UA, "Accept": "application/json"},
            retries=1,
            backoff_seconds=1.0,
            known_secrets=(key,),
        )
        selected_body = json.loads(selected_result.body) if selected_result.body else None
        selected = []
        if isinstance(selected_body, dict) and isinstance(selected_body.get("bookmakers"), list):
            selected = [
                str(value).strip()
                for value in selected_body["bookmakers"]
                if isinstance(value, str) and value.strip()
            ][:2]

        now = datetime.now(timezone.utc)
        events_url = (
            "https://api.odds-api.io/v3/events?sport=table-tennis"
            f"&from={quote(now.isoformat().replace('+00:00', 'Z'))}"
            f"&to={quote((now + timedelta(hours=2)).isoformat().replace('+00:00', 'Z'))}"
            f"&apiKey={key}"
        )
        events_result = fetch(
            events_url,
            timeout_seconds=10.0,
            headers={"User-Agent": _KNOWN_UA, "Accept": "application/json"},
            retries=1,
            backoff_seconds=1.0,
            known_secrets=(key,),
        )
        from defend_markets.shadow import parse_recovered_json

        events_body, _recovered = parse_recovered_json(events_result.body or "")
        if not isinstance(events_body, list):
            try:
                events_body = json.loads(events_result.body) if events_result.body else None
            except json.JSONDecodeError:
                events_body = None
        events = events_body if isinstance(events_body, list) else []
        bookmaker_keys: list[str] = []
        market_count = 0
        odds_status: int | None = None
        if selected and events and isinstance(events[0], dict):
            event_id = str(events[0].get("id") or "")
            odds_url = (
                "https://api.odds-api.io/v3/odds?eventId=" + quote(event_id)
                + "&bookmakers=" + quote(",".join(selected))
                + "&apiKey=" + key
            )
            odds_result = fetch(
                odds_url,
                timeout_seconds=10.0,
                headers={"User-Agent": _KNOWN_UA, "Accept": "application/json"},
                retries=1,
                backoff_seconds=1.0,
                known_secrets=(key,),
            )
            odds_status = odds_result.status_code
            odds_body = json.loads(odds_result.body) if odds_result.body else None
            if isinstance(odds_body, dict) and isinstance(odds_body.get("bookmakers"), dict):
                bookmaker_keys = sorted(str(key) for key in odds_body["bookmakers"])
                for value in odds_body["bookmakers"].values():
                    if isinstance(value, list):
                        market_count += len(value)
                    elif isinstance(value, dict) and isinstance(value.get("markets"), dict):
                        market_count += len(value["markets"])
        if bookmaker_keys and market_count:
            coverage_state = "AVAILABLE"
        elif tt_present and events_result.ok and odds_status in (200, None):
            coverage_state = "EMPTY"
        coverage_detail = (
            f"table_tennis_present={tt_present}; events={len(events)}; "
            f"selected_books={','.join(selected) or 'none'}; "
            f"bookmaker_keys={','.join(bookmaker_keys) or 'none'}; "
            f"market_entries={market_count}; odds_status={odds_status}"
        )
        return AdapterProbe(
            ok=True,
            status_code=result.status_code,
            latency_ms=result.latency_ms,
            detail="authenticated; " + coverage_detail,
            authenticated=True,
            coverage_state=coverage_state,
            coverage_detail=coverage_detail,
        )


class OddsPapiAdapter(_BaseAdapter):
    """OddsPapi (api.oddspapi.io) smallest-harmless health probe.

    Two read-only requests per Test click: the sports list (auth + Table
    Tennis presence) and a minimal odds-family call (endpoint-access
    evidence). Quota headers are captured when present. Capability cells
    stay UNKNOWN until an owner-supplied key is tested; this probe only
    records auth/reachability/TT-presence evidence.
    """

    provider_id = "oddspapi"

    _SPORTS_URL = "https://api.oddspapi.io/v4/sports?apiKey={key}"
    _ODDS_URL = (
        "https://api.oddspapi.io/v4/odds"
        "?apiKey={key}&fixtureId=0"
    )
    _QUOTA_HEADERS = (
        "x-ratelimit-remaining",
        "x-requests-remaining",
        "ratelimit-remaining",
    )
    _PLAN_MARKERS = ("plan", "upgrade", "subscription", "tier")
    _HEADERS = {"User-Agent": _KNOWN_UA, "Accept": "application/json"}

    def probe(self, definition, secrets, config) -> AdapterProbe:
        key = secrets.get("ODDSPAPI_API_KEY", "")
        if not key:
            return AdapterProbe(
                ok=False, status_code=None, latency_ms=0,
                detail="missing ODDSPAPI_API_KEY", authenticated=None,
            )
        result = fetch(
            self._SPORTS_URL.format(key=key),
            timeout_seconds=10.0,
            headers=self._HEADERS,
            retries=2,
            backoff_seconds=1.0,
            known_secrets=(key,),
        )
        if not result.ok:
            return AdapterProbe(
                ok=False,
                status_code=result.status_code,
                latency_ms=result.latency_ms,
                detail=self._detail_from_result(result),
                authenticated=None,
                error_class=self._error_class(result),
            )
        body = json.loads(result.body) if result.body else None
        sports = body if isinstance(body, list) else []
        tt_present = any(
            isinstance(sport, dict)
            and (
                sport.get("id") == 25
                or sport.get("sportId") == 25
                or "table-tennis" in str(sport.get("slug", "")).lower()
                or "table tennis"
                in str(sport.get("name") or sport.get("sportName", "")).lower()
            )
            for sport in sports
        )
        detail = f"reachable; table tennis sport present={tt_present}"
        remaining_quota = None
        quota_reset_at = None
        if result.headers:
            for header_name in self._QUOTA_HEADERS:
                parsed = _quota_parse(result.headers.get(header_name))
                if parsed is not None:
                    remaining_quota = parsed
                    break
            reset = result.headers.get("x-ratelimit-reset")
            quota_reset_at = reset if isinstance(reset, str) else None
        odds_result = fetch(
            self._ODDS_URL.format(key=key),
            timeout_seconds=10.0,
            headers=self._HEADERS,
            retries=1,
            backoff_seconds=1.0,
            known_secrets=(key,),
        )
        if odds_result.ok:
            detail += "; historical odds endpoint reachable"
        elif odds_result.status_code in (401, 403):
            detail += (
                f"; historical odds endpoint: HTTP {odds_result.status_code} "
                "(possibly tier-gated; pending empirical verification)"
            )
        elif (
            odds_result.status_code is not None
            and 400 <= odds_result.status_code < 500
        ):
            detail += (
                f"; historical odds endpoint reachable (param contract "
                f"enforced: HTTP {odds_result.status_code})"
            )
        else:
            detail += (
                f"; historical odds endpoint: "
                f"{self._detail_from_result(odds_result)} "
                "(param contract pending empirical verification)"
            )
        return AdapterProbe(
            ok=True,
            status_code=result.status_code,
            latency_ms=result.latency_ms,
            detail=detail,
            authenticated=True,
            remaining_quota=remaining_quota,
            quota_reset_at=quota_reset_at,
        )

    @staticmethod
    def _error_class(result: FetchResult) -> str | None:
        if result.status_code == 429:
            return "rate_limited"
        if result.status_code in (401, 403):
            body = (result.body or "").lower()
            if any(marker in body for marker in OddsPapiAdapter._PLAN_MARKERS):
                return "plan_required"
            return "auth_failed"
        return None


class SecEdgarAdapter(_BaseAdapter):
    provider_id = "sec_edgar"

    def probe(self, definition, secrets, config) -> AdapterProbe:
        url = (
            "https://www.sec.gov/cgi-bin/browse-edgar"
            "?action=getcompany&CIK=0000320193&type=10-K"
            "&dateb=&owner=include&count=1"
        )
        return self._probe(
            url,
            secrets,
            headers={"User-Agent": _KNOWN_UA, "Accept": "text/html"},
            success_predicate=lambda body: body is not None,
        )


class WorldBankAdapter(_BaseAdapter):
    provider_id = "world_bank"

    def probe(self, definition, secrets, config) -> AdapterProbe:
        return self._probe(
            "https://api.worldbank.org/v2/country/USA?format=json",
            secrets,
            success_predicate=lambda body: isinstance(body, list)
            and len(body) == 2
            and isinstance(body[1], list)
            and len(body[1]) >= 1,
        )


class PolymarketAdapter(_BaseAdapter):
    provider_id = "polymarket"

    def probe(self, definition, secrets, config) -> AdapterProbe:
        return self._probe(
            "https://gamma-api.polymarket.com/markets?limit=1",
            secrets,
            success_predicate=lambda body: isinstance(body, list),
        )


PLACEHOLDER_ADAPTER = PlaceholderAdapter()

REAL_ADAPTERS: dict[str, HealthAdapter] = {
    adapter.provider_id: adapter
    for adapter in (
        VastAdapter(),
        HuggingFaceAdapter(),
        FredAdapter(),
        CongressGovAdapter(),
        OddsApiAdapter(),
        OddsApiIoAdapter(),
        OddsPapiAdapter(),
        SecEdgarAdapter(),
        WorldBankAdapter(),
        PolymarketAdapter(),
    )
}


def adapter_for(definition: ProviderDefinition) -> HealthAdapter:
    """Resolve the health adapter for a provider definition."""
    if definition.adapter_kind is AdapterKind.PLACEHOLDER:
        return PLACEHOLDER_ADAPTER
    return REAL_ADAPTERS.get(definition.provider_id, PLACEHOLDER_ADAPTER)
