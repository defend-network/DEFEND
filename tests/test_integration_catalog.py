from __future__ import annotations

from defend_control.integration_catalog import (
    INTEGRATION_CATALOG,
    SECRET_CATALOG,
    CostClass,
    IntegrationOwner,
    StartupCheck,
    get_integration,
)


def test_integration_ids_are_unique():
    ids = [item.integration_id for item in INTEGRATION_CATALOG]
    assert len(ids) == len(set(ids))


def test_secret_keys_are_unique():
    keys = [item.key for item in SECRET_CATALOG]
    assert len(keys) == len(set(keys))


def test_free_no_key_nws_is_enabled():
    nws = get_integration("nws_weather")

    assert nws.owner == IntegrationOwner.SCS
    assert nws.cost_class == CostClass.FREE
    assert nws.credential_keys == ()
    assert nws.enabled_by_default is True
    assert nws.startup_check == StartupCheck.FREE_PING


def test_free_tier_sports_sources_are_registered():
    ids = {item.integration_id for item in INTEGRATION_CATALOG}

    assert "the_odds_api" in ids
    assert "api_sports" in ids
    assert "sportradar" in ids


def test_secondary_compute_provider_is_registered():
    runpod = get_integration("runpod")

    assert runpod.owner == IntegrationOwner.PLATFORM
    assert "RUNPOD_API_KEY" in runpod.credential_keys


def test_observability_and_alerting_are_registered():
    ids = {item.integration_id for item in INTEGRATION_CATALOG}

    assert "sentry" in ids
    assert "discord_alerts" in ids


def test_payments_are_scs_owned():
    stripe = get_integration("stripe")

    assert stripe.owner == IntegrationOwner.SCS
    assert "STRIPE_SECRET_KEY" in stripe.credential_keys
    assert "STRIPE_WEBHOOK_SECRET" in stripe.credential_keys


def test_paid_or_metered_integrations_do_not_remote_check_on_startup():
    for item in INTEGRATION_CATALOG:
        if item.cost_class in {
            CostClass.USAGE,
            CostClass.PAID,
            CostClass.TRIAL,
        }:
            assert item.startup_check != StartupCheck.FREE_PING


def test_every_credential_reference_exists_in_secret_catalog():
    known = {item.key for item in SECRET_CATALOG}

    for integration in INTEGRATION_CATALOG:
        assert set(integration.credential_keys) <= known


def test_hardrock_is_not_falsely_registered_as_public_api():
    assert all(
        item.integration_id != "hardrock_public_api"
        for item in INTEGRATION_CATALOG
    )


def test_secret_representations_contain_no_values():
    forbidden = ("sk_live_", "hf_", "ghp_", "rpa_")

    for definition in SECRET_CATALOG:
        rendered = repr(definition)

        for fragment in forbidden:
            assert fragment not in rendered
