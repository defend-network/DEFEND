"""Real-Postgres durable tool ledger: run-scoped call-id identity.

Proves:
- run A / fc_1 succeeds, run B / fc_1 succeeds (same call id, different runs)
- same run / duplicate fc_1 is idempotently resolved (RUNNING) or rejected
  once SUCCEEDED (never auto re-run)
"""

from __future__ import annotations

import os
import urllib.parse
import uuid

import pytest

psycopg = pytest.importorskip("psycopg")

from defend_coder.db import CoderDatabase
from defend_coder.tool_ledger import (
    TOOL_STATE_RUNNING,
    TOOL_STATE_SUCCEEDED,
    DurableToolLedger,
    ToolAlreadySucceededError,
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


@pytest.fixture(autouse=True)
def _reset(db: CoderDatabase) -> None:
    with db.connect() as connection:
        with connection.cursor() as cur:
            cur.execute("SELECT current_database()")
            assert cur.fetchone()[0] == TEST_DB
            cur.execute(
                """
                DO $$
                DECLARE r record;
                BEGIN
                    FOR r IN SELECT tablename FROM pg_tables
                             WHERE schemaname = 'public'
                    LOOP
                        EXECUTE 'DROP TABLE IF EXISTS public.'
                            || quote_ident(r.tablename) || ' CASCADE';
                    END LOOP;
                END
                $$
                """
            )
    db.migrate()


def _make_run(db: CoderDatabase, run_id: uuid.UUID) -> uuid.UUID:
    with db.connect() as connection:
        with connection.cursor() as cur:
            account = uuid.uuid4()
            workspace = uuid.uuid4()
            cur.execute(
                "INSERT INTO coder_accounts(account_id, username, "
                "password_hash, role) VALUES (%s, %s, %s, 'admin')",
                (account, str(account), "x"),
            )
            cur.execute(
                "INSERT INTO coder_workspaces(workspace_id, owner_account_id, "
                "name, workspace_root) VALUES (%s, %s, %s, %s)",
                (workspace, account, "ws", "C:/x"),
            )
            cur.execute(
                "INSERT INTO coder_runs(run_id, workspace_id, "
                "owner_account_id, prompt, status, phase) "
                "VALUES (%s, %s, %s, %s, 'running', 'executing_tool')",
                (run_id, workspace, account, "p"),
            )
    return run_id


def _begin(ledger: DurableToolLedger, run_id: uuid.UUID, call_id: str):
    return ledger.begin(
        run_id=run_id,
        tool_call_id=call_id,
        tool_name="write_file",
        argument_hash="h1",
        mutation_class="mutating",
    )


class TestDurableToolLedgerIdentity:
    def test_same_call_id_across_different_runs(self, db: CoderDatabase):
        ledger = DurableToolLedger(db)
        run_a = _make_run(db, uuid.uuid4())
        run_b = _make_run(db, uuid.uuid4())

        e_a = _begin(ledger, run_a, "fc_1")
        ledger.finish(e_a, state=TOOL_STATE_SUCCEEDED)

        e_b = _begin(ledger, run_b, "fc_1")
        ledger.finish(e_b, state=TOOL_STATE_SUCCEEDED)

        assert ledger.for_call(run_a, "fc_1").state == TOOL_STATE_SUCCEEDED
        assert ledger.for_call(run_b, "fc_1").state == TOOL_STATE_SUCCEEDED

    def test_duplicate_in_same_run_idempotent_while_running(self, db: CoderDatabase):
        ledger = DurableToolLedger(db)
        run = _make_run(db, uuid.uuid4())

        e1 = _begin(ledger, run, "fc_1")
        e2 = _begin(ledger, run, "fc_1")
        assert e1 == e2
        assert ledger.for_call(run, "fc_1").state == TOOL_STATE_RUNNING

    def test_completed_mutation_never_auto_rerun(self, db: CoderDatabase):
        ledger = DurableToolLedger(db)
        run = _make_run(db, uuid.uuid4())

        e1 = _begin(ledger, run, "fc_1")
        ledger.finish(e1, state=TOOL_STATE_SUCCEEDED)
        with pytest.raises(ToolAlreadySucceededError):
            _begin(ledger, run, "fc_1")
