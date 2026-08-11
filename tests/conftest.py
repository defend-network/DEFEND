from __future__ import annotations

import pytest

from defend_data.config import DataPaths
from defend_data.identity_store import IdentityStore
from defend_data.visitor_store import VisitorStore


@pytest.fixture
def data_paths(tmp_path):
    return DataPaths.from_env(tmp_path / "DEFEND_DATA").ensure()


@pytest.fixture
def identity(data_paths):
    store = IdentityStore(data_paths)
    yield store
    store.close()


@pytest.fixture
def visitor_store(data_paths, monkeypatch):
    monkeypatch.setenv(
        "DEFEND_VISITOR_HMAC_KEY",
        "test-key-with-at-least-thirty-two-characters",
    )
    store = VisitorStore(data_paths)
    yield store
    store.close()


@pytest.fixture
def owner(identity):
    return identity.bootstrap_owner(
        email="chairman@defend-network.org",
        display_name="Chairman",
        password="valid owner password",
    )
