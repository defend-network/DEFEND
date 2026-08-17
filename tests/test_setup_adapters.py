from __future__ import annotations

import json

import pytest

import defend_integrations.adapters as adapters_module
from defend_integrations.adapters import (
    PLACEHOLDER_ADAPTER,
    REAL_ADAPTERS,
    adapter_for,
)
from defend_integrations.http import FetchResult
from defend_integrations.models import AdapterKind, HealthBadge, badge_from_probe
from defend_integrations.registry import find_provider

REAL_IDS = (
    "vast",
    "huggingface",
    "fred",
    "congress_gov",
    "the_odds_api",
    "sec_edgar",
    "world_bank",
    "polymarket",
)


def fake_fetch(result: FetchResult):
    def _fake(url, *, timeout_seconds=10.0, headers=None, retries=2,
              backoff_seconds=1.0, known_secrets=()):
        return result

    adapters_module.fetch = _fake


class _Success(FetchResult):
    def __init__(self, body: object, headers=None):
        super().__init__(
            ok=True,
            status_code=200,
            latency_ms=31,
            error_type=None,
            body=json.dumps(body),
            retries=0,
            headers=headers,
        )


class _Failure(FetchResult):
    def __init__(self, status_code=None, error_type="TimeoutError", detail=None):
        super().__init__(
            ok=False,
            status_code=status_code,
            latency_ms=20,
            error_type=error_type,
            body=None,
        )


SECRETS_BY_PROVIDER = {
    "vast": {"VAST_API_KEY": "vast-key-value"},
    "huggingface": {"HF_TOKEN": "hf-key-value"},
    "fred": {"FRED_API_KEY": "fred-key-value"},
    "congress_gov": {"CONGRESS_API_KEY": "congress-key-value"},
    "the_odds_api": {"THE_ODDS_API_KEY": "odds-key-value"},
    "sec_edgar": {},
    "world_bank": {},
    "polymarket": {},
}


def probe_for(provider_id: str, result: FetchResult):
    definition = find_provider(provider_id)
    assert definition is not None
    adapter = REAL_ADAPTERS[provider_id]
    return adapter.probe(definition, SECRETS_BY_PROVIDER[provider_id], {})


def test_all_real_adapters_resolve_and_report_healthy_on_200():
    success_bodies = {
        "vast": {"instances": []},
        "huggingface": {"name": "someone", "orgs": []},
        "fred": {"seriess": [{"id": "GDPC1"}]},
        "congress_gov": {"bills": []},
        "the_odds_api": [],
        "sec_edgar": {"html": "ok"},
        "world_bank": [{"page": 1}, [{"id": "USA"}]],
        "polymarket": [],
    }
    for provider_id in REAL_IDS:
        fake_fetch(_Success(success_bodies[provider_id]))
        probe = probe_for(provider_id, _Success(success_bodies[provider_id]))
        assert probe.ok, provider_id
        assert probe.latency_ms == 31
        assert badge_from_probe(probe) is HealthBadge.HEALTHY, provider_id


def test_missing_credentials_never_touch_network():
    definition = find_provider("fred")
    probe = REAL_ADAPTERS["fred"].probe(definition, {}, {})
    assert probe.ok is False
    assert probe.detail == "missing FRED_API_KEY"


def test_auth_failure_maps_to_auth_failed():
    fake_fetch(_Failure(status_code=401))
    for provider_id in ("vast", "huggingface", "fred", "congress_gov", "the_odds_api"):
        probe = probe_for(provider_id, _Failure(status_code=401))
        assert probe.ok is False
        assert badge_from_probe(probe) is HealthBadge.AUTH_FAILED, provider_id
        assert probe.detail == "authentication failed"


def test_rate_limit_maps_to_rate_limited():
    fake_fetch(_Failure(status_code=429))
    probe = probe_for("fred", _Failure(status_code=429))
    assert badge_from_probe(probe) is HealthBadge.RATE_LIMITED
    assert probe.detail == "rate limited"


def test_unreachable_maps_to_unavailable():
    fake_fetch(_Failure(status_code=None, error_type="TimeoutError"))
    probe = probe_for("world_bank", _Failure())
    assert probe.ok is False
    assert badge_from_probe(probe) is HealthBadge.UNAVAILABLE


def test_no_key_providers_succeed_without_secrets():
    fake_fetch(_Success(["meta", [{"id": "USA"}]], headers={}))
    definition = find_provider("world_bank")
    probe = REAL_ADAPTERS["world_bank"].probe(definition, {}, {})
    assert probe.ok is True
    assert probe.authenticated is True

    fake_fetch(_Success([]))
    definition = find_provider("polymarket")
    probe = REAL_ADAPTERS["polymarket"].probe(definition, {}, {})
    assert probe.ok is True

    definition = find_provider("sec_edgar")
    probe = REAL_ADAPTERS["sec_edgar"].probe(definition, {}, {})
    assert probe.ok is True


def test_odds_api_extracts_quota_from_headers():
    fake_fetch(
        _Success(
            [],
            headers={
                "x-requests-remaining": "87",
                "x-requests-last": "2026-08-18T00:00:00Z",
            },
        )
    )
    probe = probe_for("the_odds_api", _Success([], headers={}))
    assert probe.ok is True
    assert probe.remaining_quota == 87
    assert probe.quota_reset_at == "2026-08-18T00:00:00Z"


def test_fred_requires_expected_series_shape():
    fake_fetch(_Success({"seriess": []}))
    probe = probe_for("fred", _Success({"seriess": []}))
    assert probe.ok is False
    assert badge_from_probe(probe) is HealthBadge.UNAVAILABLE


def test_placeholder_adapter_never_claims_health():
    probe = PLACEHOLDER_ADAPTER.probe(find_provider("api_sports"), {"API_SPORTS_API_KEY": "x"}, {})
    assert probe.ok is False
    assert probe.detail == "ADAPTER NOT IMPLEMENTED"
    assert badge_from_probe(probe) is not HealthBadge.HEALTHY


def test_adapter_for_returns_placeholder_for_placeholder_definitions():
    definition = find_provider("coingecko")
    assert definition.adapter_kind is AdapterKind.PLACEHOLDER
    assert adapter_for(definition) is PLACEHOLDER_ADAPTER


def test_real_adapter_error_text_contains_no_secrets(monkeypatch):
    captured: list[dict] = []

    def capturing(url, *, timeout_seconds=10.0, headers=None, retries=2,
                  backoff_seconds=1.0, known_secrets=()):
        captured.append({"url": url, "headers": headers, "known": known_secrets})
        return _Failure(status_code=503)

    adapters_module.fetch = capturing
    probe = probe_for("fred", _Failure(status_code=503))
    assert probe.ok is False
    assert probe.detail == "status 503"
    # The key appears only inside the mocked transport call (as a known
    # secret for redaction); it must never surface in the probe detail.
    assert "fred-key-value" not in probe.detail
    assert "api_key" not in probe.detail
    assert captured and "fred-key-value" in captured[0]["known"]