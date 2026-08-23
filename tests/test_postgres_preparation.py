"""Real-Postgres run preparation + envelope tests (defendcoder_test only)."""

from __future__ import annotations

import os
import urllib.parse
from uuid import uuid4

import pytest

psycopg = pytest.importorskip("psycopg")

from defend_coder.db import CoderDatabase
from defend_coder.preparation import (
    RunPreparationError,
    RunPreparationService,
)

TEST_DB = "defendcoder_test"


def _test_url() -> str:
    url = os.environ.get("CODER_DATABASE_URL", "")
    if not url:
        pytest.skip("CODER_DATABASE_URL is not set")
    p = urllib.parse.urlsplit(url)
    host = p.hostname or "127.0.0.1"
    port = p.port or 5432
    user = p.username or "defendcoder"
    password = p.password or ""
    query = ("?" + p.query) if p.query else ""
    return f"postgresql://{user}:{password}@{host}:{port}/{TEST_DB}{query}"


@pytest.fixture(scope="module")
def db() -> CoderDatabase:
    url = _test_url()
    try:
        conn = psycopg.connect(url, connect_timeout=5)
        conn.close()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"defendcoder_test not reachable: {type(exc).__name__}")
    return CoderDatabase(url)


@pytest.fixture(scope="module")
def prep(db) -> RunPreparationService:
    db.migrate()
    return RunPreparationService(db)


@pytest.fixture
def seeded(db):
    """Create one real account + workspace (FK requirements)."""
    account_id = uuid4()
    workspace_id = uuid4()
    with db.connect() as connection:
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO coder_accounts(account_id, username, password_hash, role)"
                " VALUES (%s, %s, %s, 'admin')",
                (account_id, f"owner-{account_id}", "hash",),
            )
            cur.execute(
                "INSERT INTO coder_workspaces(workspace_id, owner_account_id, name, workspace_root)"
                " VALUES (%s, %s, %s, %s)",
                (workspace_id, account_id, "ws", "C:/fake/root"),
            )
    return account_id, workspace_id


def _pins():
    return (
        ("defendcoder-identity-v1", "1", "a" * 64),
        ("defendcoder-prompt-core-v1", "1", "b" * 64),
        ("deepseek-v4-chat-v1", "1", "c" * 64),
    )


class TestRunPreparation:
    def test_prepare_run_atomic_with_real_workspace(self, prep, seeded):
        owner, workspace = seeded
        identity, prompt, technical = _pins()
        prepared = prep.prepare_run(
            workspace_id=workspace,
            owner_account_id=owner,
            prompt="hello",
            requested_mode="AUTO",
            selected_tier="DEEPSEEK",
            provider="deepseek",
            model="deepseek-v4-flash",
            identity=identity,
            prompt_core=prompt,
            technical=technical,
        )
        envelope = prep.load_envelope(prepared.run_id)
        assert envelope is not None
        assert envelope.workspace_id == workspace
        assert envelope.owner_account_id == owner
        assert envelope.identity_hash == "a" * 64
        assert envelope.prompt_core_hash == "b" * 64
        assert envelope.technical_profile_hash == "c" * 64
        assert envelope.provider == "deepseek"
        assert envelope.model == "deepseek-v4-flash"

    def test_prepare_run_rolls_back_on_failure(self, prep, seeded):
        owner, workspace = seeded
        with pytest.raises(Exception):
            prep.prepare_run(
                workspace_id=workspace,
                owner_account_id=owner,
                prompt="x",
                requested_mode="AUTO",
                selected_tier="DEEPSEEK",
                provider="deepseek",
                model="deepseek-v4-flash",
                identity=(None, None, None),
                prompt_core=_pins()[1],
                technical=_pins()[2],
            )

    def test_prepare_run_requires_prompt(self, prep, seeded):
        owner, workspace = seeded
        with pytest.raises(RunPreparationError):
            prep.prepare_run(
                workspace_id=workspace,
                owner_account_id=owner,
                prompt="  ",
                requested_mode="AUTO",
                selected_tier="DEEPSEEK",
                provider="deepseek",
                model="deepseek-v4-flash",
                identity=_pins()[0],
                prompt_core=_pins()[1],
                technical=_pins()[2],
            )

    def test_route_history_and_checkpoint_persisted(self, prep, seeded):
        owner, workspace = seeded
        prepared = prep.prepare_run(
            workspace_id=workspace,
            owner_account_id=owner,
            prompt="do the thing",
            requested_mode="AUTO",
            selected_tier="DEEPSEEK",
            provider="deepseek",
            model="deepseek-v4-flash",
            identity=_pins()[0],
            prompt_core=_pins()[1],
            technical=_pins()[2],
        )
        with prep._db.connect() as connection:
            with connection.cursor() as cur:
                cur.execute(
                    "SELECT revision, provider, model FROM coder_run_route_history "
                    "WHERE run_id = %s",
                    (prepared.run_id,),
                )
                route = cur.fetchone()
                cur.execute(
                    "SELECT revision FROM coder_run_checkpoints WHERE run_id = %s",
                    (prepared.run_id,),
                )
                checkpoint = cur.fetchone()
        assert route == (1, "deepseek", "deepseek-v4-flash")
        assert checkpoint == (1,)
