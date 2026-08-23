"""Real-Postgres durable tool ledger: run-scoped identity + crash safety.

Proves the mutation integrity matrix:
- run A / fc_1 and run B / fc_1 succeed independently
- same run / fc_1 SUCCEEDED -> never re-execute (ToolAlreadySucceededError)
- same run / fc_1 RUNNING (interrupted) -> ToolRecoveryRequiredError
- recover_interrupted: REQUESTED/RUNNING -> UNKNOWN_AFTER_INTERRUPTION
- same run / fc_1 UNKNOWN -> recovery required, zero execution
- same run / fc_1 FAILED -> terminal (ToolAlreadyFailedError)
- same run / fc_1 changed args or tool -> ToolIdentityMismatchError
"""

from __future__ import annotations

import os
import threading
import urllib.parse
import uuid

import pytest

psycopg = pytest.importorskip("psycopg")

from defend_coder.db import CoderDatabase
from defend_coder.tool_ledger import (
    TOOL_STATE_FAILED,
    TOOL_STATE_RUNNING,
    TOOL_STATE_SUCCEEDED,
    TOOL_STATE_UNKNOWN,
    DurableToolLedger,
    ToolAlreadyFailedError,
    ToolAlreadySucceededError,
    ToolIdentityMismatchError,
    ToolRecoveryRequiredError,
    argument_hash,
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


def _begin(ledger, run_id, call_id, tool_name="write_file", args=None):
    return ledger.begin(
        run_id=run_id,
        tool_call_id=call_id,
        tool_name=tool_name,
        argument_hash=argument_hash(args if args is not None else {"x": 1}),
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

    def test_completed_mutation_never_auto_rerun(self, db: CoderDatabase):
        ledger = DurableToolLedger(db)
        run = _make_run(db, uuid.uuid4())
        e1 = _begin(ledger, run, "fc_1")
        ledger.finish(e1, state=TOOL_STATE_SUCCEEDED, result_ref="r/1")
        with pytest.raises(ToolAlreadySucceededError) as exc:
            _begin(ledger, run, "fc_1")
        assert exc.value.result_ref == "r/1"


class TestInterruptedMutationSafety:
    def test_running_existing_requires_recovery_not_replay(self, db):
        ledger = DurableToolLedger(db)
        run = _make_run(db, uuid.uuid4())
        _begin(ledger, run, "fc_1")  # left RUNNING (crash before finish)
        with pytest.raises(ToolRecoveryRequiredError):
            _begin(ledger, run, "fc_1")

    def test_recover_interrupted_transitions_to_unknown(self, db):
        ledger = DurableToolLedger(db)
        run = _make_run(db, uuid.uuid4())
        _begin(ledger, run, "fc_1")
        _begin(ledger, run, "fc_2")
        assert ledger.recover_interrupted(run) == 2
        assert ledger.for_call(run, "fc_1").state == TOOL_STATE_UNKNOWN
        assert ledger.for_call(run, "fc_2").state == TOOL_STATE_UNKNOWN

    def test_recover_ignores_terminal_states(self, db):
        ledger = DurableToolLedger(db)
        run = _make_run(db, uuid.uuid4())
        e1 = _begin(ledger, run, "fc_1")
        ledger.finish(e1, state=TOOL_STATE_SUCCEEDED)
        e2 = _begin(ledger, run, "fc_2")
        ledger.finish(e2, state=TOOL_STATE_FAILED)
        assert ledger.recover_interrupted(run) == 0
        assert ledger.for_call(run, "fc_1").state == TOOL_STATE_SUCCEEDED
        assert ledger.for_call(run, "fc_2").state == TOOL_STATE_FAILED

    def test_unknown_requires_recovery_not_replay(self, db):
        ledger = DurableToolLedger(db)
        run = _make_run(db, uuid.uuid4())
        _begin(ledger, run, "fc_1")
        ledger.recover_interrupted(run)
        with pytest.raises(ToolRecoveryRequiredError):
            _begin(ledger, run, "fc_1")

    def test_failed_same_call_is_terminal(self, db):
        ledger = DurableToolLedger(db)
        run = _make_run(db, uuid.uuid4())
        e1 = _begin(ledger, run, "fc_1")
        ledger.finish(e1, state=TOOL_STATE_FAILED)
        with pytest.raises(ToolAlreadyFailedError):
            _begin(ledger, run, "fc_1")


class TestIdentityIntegrity:
    def test_same_call_changed_arguments_fails_closed(self, db):
        ledger = DurableToolLedger(db)
        run = _make_run(db, uuid.uuid4())
        _begin(ledger, run, "fc_1", args={"path": "a.txt"})
        with pytest.raises(ToolIdentityMismatchError):
            _begin(ledger, run, "fc_1", args={"path": "b.txt"})

    def test_same_call_changed_tool_fails_closed(self, db):
        ledger = DurableToolLedger(db)
        run = _make_run(db, uuid.uuid4())
        _begin(ledger, run, "fc_1", tool_name="write_file")
        with pytest.raises(ToolIdentityMismatchError):
            _begin(ledger, run, "fc_1", tool_name="delete_file")


class TestConcurrentBegin:
    def test_concurrent_begins_single_authority(self, db: CoderDatabase):
        ledger = DurableToolLedger(db)
        run = _make_run(db, uuid.uuid4())
        results: list[tuple[str, object]] = []
        lock = threading.Lock()

        def worker():
            try:
                eid = _begin(ledger, run, "fc_1")
                with lock:
                    results.append(("authority", eid))
            except Exception as exc:  # noqa: BLE001
                with lock:
                    results.append((type(exc).__name__, exc))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        authorities = [r for r in results if r[0] == "authority"]
        assert len(authorities) == 1
        assert ledger.for_call(run, "fc_1").state == TOOL_STATE_RUNNING
