"""Tests for the TT identity gate helpers (offline, deterministic)."""

from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path

import pytest

_TOOL = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "defend_tt_identity_gate.py"
)


def _load():
    loader = importlib.machinery.SourceFileLoader("tt_identity_gate", str(_TOOL))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate():
    return _load()


def test_slug_normalization_handles_punctuation_and_case(gate):
    assert gate._slug("John Smith") == "johnsmith"
    assert gate._slug("J. Smith") == "jsmith"
    assert gate._slug("John  Smith") == "johnsmith"
    assert gate._slug("john SMITH") == "johnsmith"
    assert gate._slug("Blazek, Jan") == "blazekjan"
    assert gate._slug("Blazek, Jan 1999") == "blazekjan1999"


def test_fragmented_same_person_variants(gate):
    assert gate._looks_fragmented("Blazek, Jan", "Blazek, Jan 1999")
    assert gate._looks_fragmented("Blazek Jan", "Blazek Jan 1999")
    assert gate._looks_fragmented("J Smith", "John Smith")
    assert gate._looks_fragmented("J. Smith", "John Smith")


def test_not_fragmented(gate):
    assert not gate._looks_fragmented("John Smith", "John Smith")
    assert not gate._looks_fragmented("John Smith", "John  Smith")
    assert not gate._looks_fragmented("John Smith", "john smith")
    assert not gate._looks_fragmented("John Smith", "Peter Jones")
    assert not gate._looks_fragmented("Jan Blazek", "Blazek Jan")
    assert not gate._looks_fragmented("", "")


def test_words(gate):
    assert gate._words("J. Smith") == ["j", "smith"]
    assert gate._words("Blazek, Jan 1999") == ["blazek", "jan", "1999"]
    assert gate._words("john  SMITH") == ["john", "smith"]