from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_identity_routes import router


@pytest.fixture
def client(identity):
    app = FastAPI()
    app.state.defend_data = SimpleNamespace(identity=identity)
    app.include_router(router)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def invitation_token(identity, owner):
    account = identity.create_account(
        email="activation-contract@example.com",
        display_name="Activation Contract",
        role="user",
        created_by=owner.account_id,
    )
    _, token = identity.create_invitation(
        account_id=account.account_id,
        created_by=owner.account_id,
    )
    return token


def test_activation_status_never_returns_token_hash(client, invitation_token):
    payload = client.post(
        "/api/activate/status", json={"token": invitation_token}
    ).json()

    assert payload["status"] == "pending"
    assert "token_hash" not in payload
