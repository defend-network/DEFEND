"""Owner workstation V1.1 — recovery authority + execution exclusivity.

Real defendcoder_test PostgreSQL. No persistence mocks. No live providers.

Covers the auditor defects:
- reconcile happens BEFORE resume authorization
- a reconciliation-created UNKNOWN blocks the worker
- existing UNKNOWN blocks the worker
- one active run per workspace is atomically enforced
- succeeded/cancelled runs cannot ordinary-resume
- recovery resolution is durable and never re-executes the original call
- immutable envelope task hash is validated (fail closed)
"""

from __future__ import annotations

import os
import urllib.parse
from uuid import uuid4

import pytest

psycopg = pytest.importorskip("psycopg")

from defend_coder.authority_store import build_authority_store, hydrate_authority
from defend_coder.db import CoderDatabase
from defend_coder.lifecycle import (
    NotResumableError,
    RecoveryRequiredError,
    RunConflictError,
    RunLifecycleService,
)
from defend_coder.preparation import RunPreparationService, prompt_sha256
from defend_coder.repositories import WorkspaceRecord
from defend_coder.run_store import RunAttemptStore, RunCheckpointStore
from defend_coder.runs import RunRunner, RunsRepository
from defend_coder.tool_ledger import (
    TOOL_STATE_FAILED,
    TOOL_STATE_SUCCEEDED,
    TOOL_STATE_UNKNOWN,
    DurableToolLedger,
    ToolAlreadyFailedError,
    ToolAlreadySucceededError,
    argument_hash,
)
from defend_coder.tools import CoderToolkit

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


class _FakeProvider:
    provider_id = "deepseek"
    model_id = "deepseek-v4-flash"
    protocol = "chat_completions"

    def generate(self, request):
        from defend_coder.provider_adapters import CoderGenerationResult

        return CoderGenerationResult(
            visible_content="done",
            tool_calls=(),
            usage=None,
            finish_reason="stop",
            provider="deepseek",
            model="deepseek-v4-flash",
        )


class _Services:
    def __init__(self, db: CoderDatabase) -> None:
        self.db = db
        self.runs = RunsRepository(db)
        self.preparation = RunPreparationService(db)
        self.ledger = DurableToolLedger(db)
        self.checkpoints = RunCheckpointStore(db)
        self.attempts = RunAttemptStore(db)

        def _toolkit_factory(log_reader):
            return CoderToolkit(
                repository=db_repo, configured_root="C:/fake", log_reader=log_reader
            )

        from defend_coder.repositories import CoderRepository

        db_repo = CoderRepository(db)
        self.runner = RunRunner(
            repository=self.runs,
            toolkit_factory=_toolkit_factory,
            provider_resolver=lambda rid: _FakeProvider(),
            envelope_loader=self.preparation.load_envelope,
            tool_ledger=self.ledger,
            checkpoint_store=self.checkpoints,
            attempt_store=self.attempts,
        )
        self.lifecycle = RunLifecycleService(
            runs=self.runs,
            preparation=self.preparation,
            tool_ledger=self.ledger,
            runner=self.runner,
        )


def _seed(db: CoderDatabase):
    store = build_authority_store(db)
    hydrate_authority(store)
    account = uuid4()
    workspace = uuid4()
    with db.connect() as c:
        with c.cursor() as cur:
            cur.execute(
                "INSERT INTO coder_accounts(account_id,username,password_hash,role)"
                " VALUES (%s,%s,%s,'admin')",
                (account, f"o-{account}", "x"),
            )
            cur.execute(
                "INSERT INTO coder_workspaces(workspace_id,owner_account_id,name,"
                "workspace_root) VALUES (%s,%s,%s,%s)",
                (workspace, account, "ws", "C:/fake"),
            )
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    ws = WorkspaceRecord(
        workspace_id=workspace,
        owner_account_id=account,
        name="ws",
        workspace_root="C:/fake",
        repository_url=None,
        default_branch=None,
        created_at=now,
        updated_at=now,
    )
    return account, ws


_PINS = (
    ("defendcoder-identity-v1", "1", "a" * 64),
    ("defendcoder-prompt-core-v1", "1", "b" * 64),
    ("deepseek-v4-chat-v1", "1", "c" * 64),
)


def _prepare(s: _Services, ws: WorkspaceRecord, account) -> object:
    identity, prompt, technical = _PINS
    return s.preparation.prepare_run(
        workspace_id=ws.workspace_id,
        owner_account_id=account,
        prompt="build it",
        requested_mode="AUTO",
        selected_tier="DEEPSEEK",
        provider="deepseek",
        model="deepseek-v4-flash",
        identity=identity,
        prompt_core=prompt,
        technical=technical,
    )


def _begin_mutation(s: _Services, run_id, call_id="fc_1"):
    return s.ledger.begin(
        run_id=run_id,
        tool_call_id=call_id,
        tool_name="write_file",
        argument_hash=argument_hash({"path": "a.txt"}),
        mutation_class="mutating",
    )


class TestRecoveryOrder:
    def test_reconcile_before_authorize_blocks_resume(self, db):
        s = _Services(db)
        account, ws = _seed(db)
        prepared = _prepare(s, ws, account)
        run_id = prepared.run_id

        # A mutating execution is left RUNNING (interrupted before finish).
        _begin_mutation(s, run_id)

        # Resume must reconcile FIRST, then block on the new UNKNOWN.
        with pytest.raises(RecoveryRequiredError):
            s.lifecycle.start(run_id=run_id, workspace=ws, account_id=account)

        # Reconcile transitioned RUNNING -> UNKNOWN.
        assert s.ledger.for_call(run_id, "fc_1").state == TOOL_STATE_UNKNOWN
        # NO worker started.
        assert not s.runner.is_active(run_id)

    def test_existing_unknown_blocks_resume(self, db):
        s = _Services(db)
        account, ws = _seed(db)
        run_id = _prepare(s, ws, account).run_id
        _begin_mutation(s, run_id)
        s.ledger.recover_interrupted(run_id)

        with pytest.raises(RecoveryRequiredError):
            s.lifecycle.start(run_id=run_id, workspace=ws, account_id=account)
        assert not s.runner.is_active(run_id)


class TestResumeStates:
    def test_succeeded_not_resumable(self, db):
        s = _Services(db)
        account, ws = _seed(db)
        run_id = _prepare(s, ws, account).run_id
        s.runs.update_run_status(run_id, status="succeeded")
        with pytest.raises(NotResumableError):
            s.lifecycle.start(run_id=run_id, workspace=ws, account_id=account)

    def test_cancelled_not_resumable(self, db):
        s = _Services(db)
        account, ws = _seed(db)
        run_id = _prepare(s, ws, account).run_id
        s.runs.update_run_status(run_id, status="cancelled")
        with pytest.raises(NotResumableError):
            s.lifecycle.start(run_id=run_id, workspace=ws, account_id=account)


class TestWorkspaceExecutionExclusivity:
    def test_second_prepare_same_workspace_conflicts(self, db):
        s = _Services(db)
        account, ws = _seed(db)
        _prepare(s, ws, account)
        with pytest.raises(Exception):
            _prepare(s, ws, account)

    def test_claim_after_terminal_allows_next_run(self, db):
        s = _Services(db)
        account, ws = _seed(db)
        run_a = _prepare(s, ws, account).run_id
        s.runs.update_run_status(run_a, status="succeeded")
        run_b = _prepare(s, ws, account).run_id
        assert run_b is not None


class TestRecoveryResolution:
    def test_confirmed_applied_never_reruns(self, db):
        s = _Services(db)
        account, ws = _seed(db)
        run_id = _prepare(s, ws, account).run_id
        _begin_mutation(s, run_id)
        s.ledger.recover_interrupted(run_id)
        exec_row = s.ledger.for_call(run_id, "fc_1")

        resulting = s.ledger.resolve_recovery(
            run_id=run_id,
            execution_id=exec_row.execution_id,
            tool_call_id="fc_1",
            tool_name="write_file",
            owner_account_id=account,
            resolution="CONFIRMED_APPLIED",
        )
        assert resulting == TOOL_STATE_SUCCEEDED
        with pytest.raises(ToolAlreadySucceededError):
            _begin_mutation(s, run_id)

    def test_confirmed_not_applied_requires_new_call_id(self, db):
        s = _Services(db)
        account, ws = _seed(db)
        run_id = _prepare(s, ws, account).run_id
        _begin_mutation(s, run_id)
        s.ledger.recover_interrupted(run_id)
        exec_row = s.ledger.for_call(run_id, "fc_1")

        s.ledger.resolve_recovery(
            run_id=run_id,
            execution_id=exec_row.execution_id,
            tool_call_id="fc_1",
            tool_name="write_file",
            owner_account_id=account,
            resolution="CONFIRMED_NOT_APPLIED",
        )
        assert s.ledger.for_call(run_id, "fc_1").state == TOOL_STATE_FAILED
        with pytest.raises(ToolAlreadyFailedError):
            _begin_mutation(s, run_id)
        # A NEW call id may proceed.
        _begin_mutation(s, run_id, call_id="fc_2")

    def test_resolution_durable_across_restart(self, db):
        s = _Services(db)
        account, ws = _seed(db)
        run_id = _prepare(s, ws, account).run_id
        _begin_mutation(s, run_id)
        s.ledger.recover_interrupted(run_id)
        exec_row = s.ledger.for_call(run_id, "fc_1")
        s.ledger.resolve_recovery(
            run_id=run_id,
            execution_id=exec_row.execution_id,
            tool_call_id="fc_1",
            tool_name="write_file",
            owner_account_id=account,
            resolution="CONFIRMED_APPLIED",
        )

        restarted = _Services(db)
        assert restarted.ledger.for_call(run_id, "fc_1").state == TOOL_STATE_SUCCEEDED
        with pytest.raises(ToolAlreadySucceededError):
            _begin_mutation(restarted, run_id)


class TestEnvelopeAuthority:
    def test_prompt_hash_persisted_and_validated(self, db):
        s = _Services(db)
        account, ws = _seed(db)
        run_id = _prepare(s, ws, account).run_id
        envelope = s.preparation.load_envelope(run_id)
        assert envelope.prompt_sha256 == prompt_sha256("build it")

    def test_prompt_hash_mismatch_fails_closed(self, db):
        s = _Services(db)
        account, ws = _seed(db)
        run_id = _prepare(s, ws, account).run_id
        # Tamper: change the persisted prompt without updating the envelope.
        with db.connect() as c:
            with c.cursor() as cur:
                cur.execute(
                    "UPDATE coder_runs SET prompt=%s WHERE run_id=%s",
                    ("tampered", run_id),
                )
        from defend_coder.lifecycle import EnvelopeValidationError

        with pytest.raises(EnvelopeValidationError):
            s.lifecycle.start(run_id=run_id, workspace=ws, account_id=account)
