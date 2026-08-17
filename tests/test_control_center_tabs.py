from __future__ import annotations

import inspect

from defend_control import ui


def test_control_center_uses_product_notebook():
    source = inspect.getsource(ui.ControlCenterUI)

    assert "ttk.Notebook" in source
    assert '"Home"' in source
    assert '"DEFEND AI"' in source
    assert '"DEFEND Sports"' in source
    assert '"SCS AI"' in source
    assert '"DEFENDcoder"' in source


def test_product_tabs_render_status_details():
    source = inspect.getsource(ui.ControlCenterUI)

    assert "status.details" in source
    assert "_product_detail" in source


def test_product_tabs_have_isolated_logs():
    source = inspect.getsource(ui.ControlCenterUI)

    assert "_product_logs" in source
    assert 'getattr(product, "logs")' in source


def test_home_keeps_global_product_actions():
    source = inspect.getsource(ui.ControlCenterUI)

    assert "_PRODUCT_ACTIONS" in source
    assert "_product_action" in source


def test_control_center_sets_defend_window_icon():
    source = inspect.getsource(ui.ControlCenterUI)

    assert "DEFEND_LOGO.ico" in source or "iconbitmap" in source

def test_control_center_orders_defend_products_before_scs():
    import inspect
    from defend_control import ui

    source = inspect.getsource(ui.ControlCenterUI)

    assert "_ordered_products" in source
    assert '"defend": 0' in source
    assert '"sports": 1' in source
    assert '"coder": 2' in source
    assert '"scs": 3' in source


def test_home_uses_four_product_cards():
    import inspect
    from defend_control import ui

    source = inspect.getsource(ui.ControlCenterUI)

    assert "_build_home_card" in source
    assert "_home_cards" in source
    assert "_home_card_states" in source
    assert "_home_card_text" in source


def test_notebook_tabs_are_resized_evenly():
    import inspect
    from defend_control import ui

    source = inspect.getsource(ui.ControlCenterUI)

    assert "_resize_notebook_tabs" in source
    assert '"<Configure>"' in source


def test_home_has_platform_posture_summary():
    import inspect
    from defend_control import ui

    source = inspect.getsource(ui.ControlCenterUI)

    assert "_platform_posture" in source
    assert "_render_platform_posture" in source

def test_product_rendering_does_not_depend_on_legacy_home_table():
    import inspect
    from defend_control import ui

    source = inspect.getsource(ui.ControlCenterUI._render_products)

    assert "if state_var is None:\n                continue" not in source
    assert "_render_product_details" in source
    assert "_render_product_logs" in source


def test_product_cards_and_tabs_track_action_buttons():
    import inspect
    from defend_control import ui

    source = inspect.getsource(ui.ControlCenterUI)

    assert "_home_buttons" in source
    assert "_tab_buttons" in source
    assert "_focus_product_log" in source
