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
from typing import Protocol

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