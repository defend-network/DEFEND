from __future__ import annotations

import inspect

from defend_control import ui


def test_setup_uses_integration_catalog():
    source = inspect.getsource(ui.SetupDialog)

    assert "SECRET_CATALOG" in source
    assert "_secret_groups" in source


def test_setup_groups_credentials_by_product():
    source = inspect.getsource(ui.SetupDialog)

    assert "Platform / Operations" in source
    assert "DEFEND AI" in source
    assert "DEFENDcoder" in source
    assert "DEFENDmarkets" in source
    assert "SCS AI" in source


def test_setup_no_longer_depends_on_flat_secret_fields():
    source = inspect.getsource(ui.SetupDialog)

    assert "_SECRET_FIELDS" not in source


def test_setup_password_entries_remain_masked():
    source = inspect.getsource(ui.SetupDialog)

    assert 'show="*"' in source


def test_setup_retains_blank_secret_semantics():
    source = inspect.getsource(ui.SetupDialog._save)

    assert "if (value := variable.get())" in source


def test_setup_mentions_configured_values_are_not_displayed():
    source = inspect.getsource(ui.SetupDialog)

    assert "saved values are never displayed" in source.lower()


def test_setup_uses_scrollable_secret_area():
    source = inspect.getsource(ui.SetupDialog)

    assert "tk.Canvas" in source
    assert "Scrollbar" in source
