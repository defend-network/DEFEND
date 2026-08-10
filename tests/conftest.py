from __future__ import annotations

import pytest

from defend_data.config import DataPaths
from defend_data.identity_store import IdentityStore


@pytest.fixture
def data_paths(tmp_path):
    return DataPaths.from_env(tmp_path / "DEFEND_DATA").ensure()


@pytest.fixture
def identity(data_paths):
    store = IdentityStore(data_paths)
    yield store
    store.close()


@pytest.fixture
def owner(identity):
    return identity.bootstrap_owner(
        email="chairman@defend-network.org",
        display_name="Chairman",
        password="valid owner password",
    )
