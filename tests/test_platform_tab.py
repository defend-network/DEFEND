"""Control Center PLATFORM tab tests.

Verifies the existing desktop Control Center gains a top-level PLATFORM tab
with the required sections, that functional sections render read-only data,
that sections without repository truth render explicit NOT_CONFIGURED /
NOT_IMPLEMENTED (never fake operational), and that no product-specific
settings are implemented inside Control Center.
"""

from __future__ import annotations

import inspect

from defend_control import ui


def _source(name: str) -> str:
    return inspect.getsource(getattr(ui.ControlCenterUI, name))


def test_platform_tab_is_a_top_level_notebook_tab():
    source = inspect.getsource(ui.ControlCenterUI)
    assert 'text="PLATFORM"' in source
    assert "_build_platform_tab" in source
    assert "_render_platform" in source


def test_platform_tab_has_all_required_sections():
    sections = {key: title for key, title in ui.ControlCenterUI._PLATFORM_SECTIONS}
    assert set(sections) == {
        "overview",
        "credentials",
        "infrastructure",
        "database_storage",
        "membership",
        "billing",
        "networking",
        "audit",
    }
    for title in (
        "Platform overview",
        "Credentials",
        "Infrastructure",
        "Database / storage",
        "Membership",
        "Billing",
        "Networking",
        "Platform audit",
    ):
        assert title in sections.values(), title


def test_platform_overview_renders_supervision_data():
    source = _source("_platform_overview_text")
    assert "Port collision check" in source
    assert "reported=" in source
    assert "processes=" in source


def test_platform_credentials_renders_masked_only():
    source = _source("_platform_credentials_text")
    assert "masked=" in source
    assert "intended_products" in source
    assert "NOT_IMPLEMENTED" in source
    assert "metadata" in source


def test_platform_infrastructure_renders_observable_facts():
    source = _source("_platform_infrastructure_text")
    for field in ("Host:", "OS:", "Python:", "Node:", "Disk", "Secret store"):
        assert field in source, field


def test_platform_membership_and_billing_are_honest_not_fake():
    membership = _source("_platform_membership_text")
    assert "NOT_CONFIGURED" in membership
    billing = _source("_platform_billing_text")
    assert "NOT_IMPLEMENTED" in billing
    assert "Neutral primitives" in billing


def test_platform_networking_reports_not_configured_cloudflare():
    source = _source("_platform_networking_text")
    assert "NOT_CONFIGURED" in source
    assert "Collision check" in source


def test_platform_audit_renders_redacted_events():
    source = _source("_platform_audit_text")
    assert "redacted" in source
    assert "no secrets" in source


def test_platform_tab_refresh_is_throttled_in_poll():
    source = inspect.getsource(ui.ControlCenterUI)
    assert "_render_platform_throttled" in source
    assert "_platform_refresh_counter" in source


def test_platform_tab_never_duplicates_product_settings():
    source = inspect.getsource(ui.ControlCenterUI)
    assert "risk threshold" not in source.casefold()
    assert "reasoning effort" not in source.casefold()
    assert "engineering tolerance" not in source.casefold()


def test_product_setup_button_is_disabled_and_product_owned():
    assert (
        ui._PRODUCT_SETUP_DISABLED_NOTE
        == "Setup not yet implemented in product"
    )
    source = inspect.getsource(ui.ControlCenterUI)
    assert "_PRODUCT_SETUP_DISABLED_NOTE" in source
    assert "_show_product_setup_note" in source
    assert ui._PRODUCT_SETUP_LABEL == "Product Setup"
    setup_button_source = inspect.getsource(
        ui.ControlCenterUI._build_product_detail_tab
    )
    assert "_PRODUCT_SETUP_LABEL" in setup_button_source
    assert 'state="disabled"' in setup_button_source
