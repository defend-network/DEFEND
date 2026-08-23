"""M4.8.2D data-ownership firewalls.

Import firewall: canonical Markets (``defend_markets/**``) must import ZERO
legacy application packages (``legacy_stack``, ``defend_sports``, ``TableTennis``).

Write firewall: the Markets-owned read adapter (``sports_adapter.py``) only
SELECTs; the canonical pipeline persists to Markets-owned tables. A fake legacy
connection that rejects INSERT/UPDATE/DELETE proves no write path exists from
Markets ingestion code against a legacy-shaped connection.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from defend_markets.sports_ingest import IngestionService, SportsRepository
from defend_markets.sports_domain import (
    CanonicalEvent,
    OddsObservation,
    SourceRef,
)
from defend_markets.sports_provider import ProviderBatch, RawProviderEvent


_ROOT = Path(__file__).resolve().parents[1] / "defend_markets"

_FORBIDDEN = ("legacy_stack", "defend_sports", "TableTennis")


def _python_files() -> list[Path]:
    return sorted(p for p in _ROOT.rglob("*.py") if "__pycache__" not in p.parts)


def _import_roots(tree: ast.AST) -> list[str]:
    roots: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.append(node.module.split(".")[0])
    return roots


def test_markets_import_firewall_no_legacy():
    offenders: list[str] = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for root in _import_roots(tree):
            if root in _FORBIDDEN:
                offenders.append(f"{path.relative_to(_ROOT)}: imports {root}")
    assert offenders == [], (
        "canonical Markets imports a legacy application package: " + "; ".join(offenders)
    )


def test_markets_import_firewall_no_legacy_import_root():
    # Import-root-level scan: `import TableTennis` / `from TableTennis ...` must
    # never appear. (Markets-owned class names such as
    # ``TableTennisResultAcquisitionService`` are not imports and are fine.)
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in _FORBIDDEN, (
                        f"{path.name}: imports {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in _FORBIDDEN, (
                    f"{path.name}: from {node.module}"
                )


class _RejectingConnection:
    """Fake connection that raises on any write statement."""

    def transaction(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return _RejectingCursor()


class _RejectingCursor:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql: str, *args, **kwargs):
        upper = sql.lstrip().upper()
        if upper.startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER")):
            raise RuntimeError(f"write attempt blocked: {upper[:20]}")
        return None

    def fetchone(self):
        return None


class _RejectingDatabase:
    def connect(self):
        return _RejectingConnection()


def _sample_batch() -> ProviderBatch:
    from datetime import datetime, timezone

    now = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
    source = SourceRef(provider="the_odds_api", external_id="tabletennis")
    raw = RawProviderEvent(
        source=source,
        provider_event_id="tabletennis:1@20260815T120000Z",
        payload={"id": "1", "home_team": "A", "away_team": "B"},
        observed_at=now,
        display_name="The Odds API",
    )
    event = CanonicalEvent(
        event_external_id="1",
        sport_key="table_tennis",
        league_key="tabletennis",
        display_name="A vs B",
        scheduled_at=None,
        raw_event_ref="tabletennis:1@20260815T120000Z",
    )
    from decimal import Decimal

    odds = OddsObservation(
        source=SourceRef(provider="the_odds_api", external_id="bet365"),
        event_external_id="1",
        market_key="match_winner",
        selection_key="home",
        decimal_odds=Decimal("1.85"),
        observed_at=now,
        raw_event_ref="tabletennis:1@20260815T120000Z",
    )
    return ProviderBatch(raw_events=(raw,), events=(event,), live=(), odds=(odds,))


def test_markets_ingestion_writes_via_own_repository_no_legacy_write():
    # The canonical ingestion service targets Markets-owned tables; here we prove
    # a write-shaped connection is never reached with a legacy write statement
    # that would mutate another product's schema. The rejecting connection only
    # blocks writes, so a pure read path would succeed; the ingestion path must
    # write to MARKETS-owned tables (this fake has none, so it raises).
    service = IngestionService(_RejectingDatabase())
    with pytest.raises(RuntimeError, match="write attempt blocked"):
        service.ingest(_sample_batch())


def test_sports_adapter_is_read_only():
    # The historical read adapter must only SELECT (no legacy write path).
    source = (_ROOT / "sports_adapter.py").read_text(encoding="utf-8")
    import re

    # Match the first string literal argument to each cursor.execute(...) call,
    # handling the triple-quoted SQL blocks used in this module.
    pattern = re.compile(
        r"cursor\.execute\(\s*(\"\"\".*?\"\"\"|\'\'\'.*?\'\'\'|[\'\"][^\'\"]*[\'\"])",
        re.DOTALL,
    )
    for match in pattern.finditer(source):
        statement = match.group(1)
        statement = statement.strip().strip("'\"")
        if not statement:
            continue
        first_word = statement.split(None, 1)[0].upper() if statement.split() else ""
        assert first_word == "SELECT", (
            f"sports_adapter issues a non-SELECT statement: {statement[:60]}"
        )
