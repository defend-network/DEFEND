"""Arb core: hermeticity — no provider/network calls, no live DB.

The M1 core is pure math/domain logic. These tests assert that the arb
package neither imports network/HTTP clients nor touches a live database.
"""

from __future__ import annotations

import importlib
import sys

import pytest

ARB_MODULES = [
    "defend_markets.arb.models",
    "defend_markets.arb.identity",
    "defend_markets.arb.compatibility",
    "defend_markets.arb.math",
    "defend_markets.arb.staking",
    "defend_markets.arb.freshness",
    "defend_markets.arb.risk",
    "defend_markets.arb.opportunity",
    "defend_markets.arb.paper",
    "defend_markets.arb.search",
    "defend_markets.arb.efficiency",
]

FORBIDDEN_IMPORTS = {
    "requests",
    "httpx",
    "aiohttp",
    "urllib.request",
    "socket",
    "http.client",
    "psycopg",
    "psycopg2",
    "sqlite3",
    "sqlalchemy",
    "aiosqlite",
}


@pytest.mark.parametrize("module_name", ARB_MODULES)
def test_arb_module_has_no_forbidden_imports(module_name):
    import types

    module = importlib.import_module(module_name)
    for key, value in vars(module).items():
        # Only inspect module attributes that are themselves imported modules.
        if not isinstance(value, types.ModuleType):
            continue
        top = value.__name__.split(".")[0]
        assert top not in FORBIDDEN_IMPORTS, f"{module_name} imports forbidden module {value.__name__} via {key}"


def test_arb_package_imports_no_network_client():
    import types

    import defend_markets.arb as arb_pkg

    source = sys.modules["defend_markets.arb"]
    for name, value in vars(source).items():
        if not isinstance(value, types.ModuleType):
            continue
        top = value.__name__.split(".")[0]
        assert top not in FORBIDDEN_IMPORTS


def test_arb_math_is_pure_function():
    from defend_markets.arb.math import compute_inverse_sum
    from decimal import Decimal

    # Calling the math with no network/db present must succeed.
    result = compute_inverse_sum((Decimal("2.10"), Decimal("2.10")))
    assert result.is_arb
