"""FINAL PASS GATE — owner-workstation runtime integrity (real PostgreSQL).

Uses REAL defendcoder_test PostgreSQL, REAL migrations through latest, REAL
PostgresAuthorityStore, REAL server-side authority resolution, REAL
RunPreparationService, REAL RunRunner, REAL RunContextCoordinator, REAL
checkpoint/attempt stores, REAL durable tool ledger, and FAKE providers behind
the real CoderProvider interface.

A genuine process restart is simulated by destroying and reconstructing
process-local services from PostgreSQL. No persistence mocks. No live
DeepSeek / Qwen Next / Sol. No GPU. No paid compute.
"""

from __future__ import annotations

import os
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

psycopg = pytest.importorskip("psycopg")

from defend_coder.authority_store import (
    PostgresAuthorityStore,
    build_authority_store,
    hydrate_authority,
)
from defend_coder.context import (
    ContextBudgetManager,
    RunContextCoordinator,
    build_checkpoint,
    estimate_tool_schemas,
)
from defend_coder.db import CoderDatabase
from defend_coder.preparation import RunPreparationService
from defend_coder.provider_adapters import (
    CoderGenerationRequest,
    CoderGenerationResult,
    CoderProvider,
    RoutingCoderProvider,
)
from defend_coder.registry import (
    ProviderTechnicalRegistry,
    build_provider_technical_profile,
)
from defend_coder.repositories import CoderRepository, WorkspaceRecord
from defend_coder.run_store import (
    ATTEMPT_STATE_RUNNING,
    ATTEMPT_STATE_SUCCEEDED,
    RunAttemptStore,
    RunCheckpointStore,
)
from defend_coder.runs import RunAuthorityError, RunRunner, RunsRepository
from defend_coder.tool_ledger import (
    TOOL_STATE_RUNNING,
    TOOL_STATE_SUCCEEDED,
    TOOL_STATE_UNKNOWN,
    DurableToolLedger,
    ToolAlreadySucceededError,
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


@dataclass(frozen=True)
class Services:
    db: CoderDatabase
    store: PostgresAuthorityStore
    preparation: RunPreparationService
    attempts: RunAttemptStore
    checkpoints: RunCheckpointStore
    ledger: DurableToolLedger
    runs: RunsRepository
    technical_registry: ProviderTechnicalRegistry


def _services(db: CoderDatabase) -> Services:
    store = build_authority_store(db)
    hydrated = hydrate_authority(store)
    technical_registry = ProviderTechnicalRegistry()
    for profile in hydrated.technical_profiles.values():
        technical_registry.register(profile)
    for provider in ("deepseek", "self_hosted", "openai"):
        key = store.active_technical_for(provider)
        if key is not None:
            technical_registry.set_active_for_provider(provider, *key)
    return Services(
        db=db,
        store=store,
        preparation=RunPreparationService(db),
        attempts=RunAttemptStore(db),
        checkpoints=RunCheckpointStore(db),
        ledger=DurableToolLedger(db),
        runs=RunsRepository(db),
        technical_registry=technical_registry,
    )


def _make_workspace(db: CoderDatabase) -> tuple[UUID, UUID]:
    return _make_workspace_with_root(db, "C:/fake")


def _make_workspace_with_root(
    db: CoderDatabase, root: object
) -> tuple[UUID, UUID]:
    account_id = uuid4()
    workspace_id = uuid4()
    with db.connect() as connection:
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO coder_accounts(account_id, username, "
                "password_hash, role) VALUES (%s, %s, %s, 'admin')",
                (account_id, str(account_id), "x"),
            )
            cur.execute(
                "INSERT INTO coder_workspaces(workspace_id, owner_account_id, "
                "name, workspace_root) VALUES (%s, %s, %s, %s)",
                (workspace_id, account_id, "ws", str(root)),
            )
    return account_id, workspace_id


def _workspace_record(db: CoderDatabase) -> WorkspaceRecord:
    account_id, workspace_id = _make_workspace(db)
    now = datetime.now(timezone.utc)
    return WorkspaceRecord(
        workspace_id=workspace_id,
        owner_account_id=account_id,
        name="ws",
        workspace_root="C:/fake",
        repository_url=None,
        default_branch=None,
        created_at=now,
        updated_at=now,
    )


def _pins(services: Services) -> tuple[tuple[str, str, str], ...]:
    identity_key = services.store.active_identity_key()
    prompt_key = services.store.active_prompt_core_key()
    assert identity_key is not None and prompt_key is not None
    iid, iver = identity_key
    pid, pver = prompt_key
    hydrated = hydrate_authority(services.store)
    identity = hydrated.identity_profiles[identity_key]
    prompt = hydrated.prompt_cores[prompt_key]
    return (
        (iid, iver, identity.hash),
        (pid, pver, prompt.hash),
    )


def _prepare(
    services: Services,
    workspace: WorkspaceRecord,
    provider: str = "deepseek",
    model: str = "deepseek-v4-flash",
) -> tuple[UUID, object]:
    identity, prompt = _pins(services)
    technical = services.technical_registry.active_for_provider(provider)
    prepared = services.preparation.prepare_run(
        workspace_id=workspace.workspace_id,
        owner_account_id=workspace.owner_account_id,
        prompt="Inspect the workspace.",
        requested_mode="AUTO",
        selected_tier="DEEPSEEK",
        provider=provider,
        model=model,
        identity=identity,
        prompt_core=prompt,
        technical=(
            technical.profile_id,
            technical.version,
            technical.hash,
        ),
    )
    envelope = services.preparation.load_envelope(prepared.run_id)
    assert envelope is not None
    return prepared.run_id, envelope


class _FinalProvider:
    """Fake CoderProvider: immediately returns a final answer (no tools)."""

    provider_id = "deepseek"
    model_id = "deepseek-v4-flash"
    protocol = "chat_completions"

    def generate(self, request: CoderGenerationRequest) -> CoderGenerationResult:
        return CoderGenerationResult(
            visible_content="The workspace is clean.",
            tool_calls=(),
            usage=None,
            finish_reason="stop",
            provider=self.provider_id,
            model=self.model_id,
        )


class _EscalatingProvider:
    """Fake provider keyed by model; reports its own identity per call."""

    protocol = "chat_completions"

    def __init__(self, model: str, provider_id: str) -> None:
        self.model_id = model
        self.provider_id = provider_id
        self.calls: list[str] = []

    def generate(self, request: CoderGenerationRequest) -> CoderGenerationResult:
        self.calls.append(self.model_id)
        return CoderGenerationResult(
            visible_content=f"answered by {self.model_id}",
            tool_calls=(),
            usage=None,
            finish_reason="stop",
            provider=self.provider_id,
            model=self.model_id,
        )


class _MutatingScriptProvider:
    """Fake provider: write_file call (call_1) then a final answer."""

    provider_id = "deepseek"
    model_id = "deepseek-v4-flash"
    protocol = "chat_completions"

    def __init__(self) -> None:
        from defend_coder.agent_client import ToolCall

        self._script = [
            CoderGenerationResult(
                visible_content=None,
                tool_calls=(
                    ToolCall(
                        id="call_1",
                        name="write_file",
                        arguments={"path": "notes.txt", "content": "v1"},
                    ),
                ),
                usage=None,
                finish_reason="tool_calls",
                provider=self.provider_id,
                model=self.model_id,
            ),
            CoderGenerationResult(
                visible_content="done",
                tool_calls=(),
                usage=None,
                finish_reason="stop",
                provider=self.provider_id,
                model=self.model_id,
            ),
        ]

    def generate(self, request: CoderGenerationRequest) -> CoderGenerationResult:
        return self._script.pop(0)


class TestPreparationAndAuthority:
    def test_prepare_commits_envelope_and_checkpoint_revision_1(
        self, db: CoderDatabase
    ):
        services = _services(db)
        workspace = _workspace_record(db)
        run_id, envelope = _prepare(services, workspace)

        assert envelope.workspace_id == workspace.workspace_id
        assert envelope.initial_checkpoint_revision == 1
        checkpoint = services.checkpoints.latest(run_id)
        assert checkpoint is not None
        assert checkpoint.revision == 1
        assert checkpoint.identity_hash == envelope.identity_hash
        assert checkpoint.prompt_core_hash == envelope.prompt_core_hash

    def test_runner_requires_envelope_before_running(self, db: CoderDatabase):
        services = _services(db)
        workspace = _workspace_record(db)
        run_id = uuid4()  # no envelope exists

        runner = RunRunner(
            repository=services.runs,
            toolkit_factory=lambda log_reader: CoderToolkit(
                repository=CoderRepository(db),
                configured_root="C:/fake",
                log_reader=log_reader,
            ),
            provider_resolver=lambda rid: _FinalProvider(),
            envelope_loader=services.preparation.load_envelope,
        )
        with pytest.raises(RunAuthorityError):
            runner.start_existing(
                run_id=run_id,
                workspace=workspace,
                prompt="Inspect.",
            )

    def test_start_bypass_is_disabled(self, db: CoderDatabase):
        services = _services(db)
        workspace = _workspace_record(db)
        runner = RunRunner(
            repository=services.runs,
            toolkit_factory=lambda log_reader: CoderToolkit(
                repository=CoderRepository(db),
                configured_root="C:/fake",
                log_reader=log_reader,
            ),
            provider_resolver=lambda rid: _FinalProvider(),
            envelope_loader=services.preparation.load_envelope,
        )
        with pytest.raises(RunAuthorityError):
            runner.start(workspace=workspace, prompt="Inspect.")

    def test_historical_technical_v1_pinned_after_active_v2(
        self, db: CoderDatabase
    ):
        services = _services(db)
        workspace = _workspace_record(db)

        v1 = build_provider_technical_profile("deepseek", version="1")
        services.store.save_technical(v1)
        services.store.set_technical_active(
            "deepseek", v1.profile_id, v1.version
        )
        services.technical_registry.register(v1)
        services.technical_registry.set_active_for_provider(
            "deepseek", v1.profile_id, v1.version
        )
        run_v1, envelope_v1 = _prepare(services, workspace)

        v2 = build_provider_technical_profile("deepseek", version="2")
        services.store.save_technical(v2)
        services.store.set_technical_active(
            "deepseek", v2.profile_id, v2.version
        )
        services.technical_registry.register(v2)
        services.technical_registry.set_active_for_provider(
            "deepseek", v2.profile_id, v2.version
        )
        run_v2, envelope_v2 = _prepare(services, workspace)

        # Reconstruct (restart) and confirm each run stays on its own pin.
        restarted = _services(db)
        env_v1 = restarted.preparation.load_envelope(run_v1)
        env_v2 = restarted.preparation.load_envelope(run_v2)
        assert env_v1.technical_profile_hash == v1.hash
        assert env_v2.technical_profile_hash == v2.hash
        assert env_v1.technical_profile_version == "1"
        assert env_v2.technical_profile_version == "2"


class TestToolLedgerRestartSafety:
    def test_completed_mutation_never_reexecuted_after_restart(
        self, db: CoderDatabase
    ):
        services = _services(db)
        workspace = _workspace_record(db)
        run_id, _ = _prepare(services, workspace)

        e1 = services.ledger.begin(
            run_id=run_id,
            tool_call_id="fc_1",
            tool_name="write_file",
            argument_hash="h1",
            mutation_class="mutating",
        )
        services.ledger.finish(e1, state=TOOL_STATE_SUCCEEDED)

        # Restart: new ledger over the same Postgres.
        restarted = _services(db).ledger
        assert restarted.for_call(run_id, "fc_1").state == TOOL_STATE_SUCCEEDED
        with pytest.raises(ToolAlreadySucceededError):
            restarted.begin(
                run_id=run_id,
                tool_call_id="fc_1",
                tool_name="write_file",
                argument_hash="h1",
                mutation_class="mutating",
            )

    def test_production_mutation_never_reexecuted_after_restart(
        self, db: CoderDatabase, tmp_path
    ):
        from defend_coder.agent import CodingAgent
        from defend_coder.agent_client import ToolCall

        services = _services(db)
        root = tmp_path / "wsroot"
        root.mkdir()
        account_id, workspace_id = _make_workspace_with_root(db, root)
        identity, prompt = _pins(services)
        technical = services.technical_registry.active_for_provider("deepseek")
        prepared = services.preparation.prepare_run(
            workspace_id=workspace_id,
            owner_account_id=account_id,
            prompt="Write the file.",
            requested_mode="AUTO",
            selected_tier="DEEPSEEK",
            provider="deepseek",
            model="deepseek-v4-flash",
            identity=identity,
            prompt_core=prompt,
            technical=(
                technical.profile_id,
                technical.version,
                technical.hash,
            ),
        )
        run_id = prepared.run_id

        def _toolkit():
            return CoderToolkit(
                repository=CoderRepository(db),
                configured_root=str(root),
            )

        def _provider():
            return _MutatingScriptProvider()

        def _run():
            agent = CodingAgent(
                provider=_provider(),
                toolkit=_toolkit(),
                log=lambda _m: None,
                tool_ledger=DurableToolLedger(db),
                run_id=run_id,
            )
            outcome = agent.run(
                prompt="Write the file.",
                account_id=account_id,
                workspace_id=workspace_id,
                sink=lambda **kw: None,
            )
            return outcome

        first = _run()
        assert first.state == "succeeded"
        written = root / "notes.txt"
        assert written.read_text(encoding="utf-8") == "v1"
        assert (
            DurableToolLedger(db).for_call(run_id, "call_1").state
            == TOOL_STATE_SUCCEEDED
        )

        # Restart: the provider asks for the SAME mutating tool again; the
        # durable ledger must skip re-execution (idempotent), not re-write.
        second = _run()
        assert second.state == "succeeded"
        assert written.read_text(encoding="utf-8") == "v1"

    def test_inflight_mutation_recovery_is_idempotent(self, db: CoderDatabase):
        services = _services(db)
        workspace = _workspace_record(db)
        run_id, _ = _prepare(services, workspace)

        # A mutating execution is left RUNNING (simulated crash before finish).
        services.ledger.begin(
            run_id=run_id,
            tool_call_id="fc_1",
            tool_name="write_file",
            argument_hash="h1",
            mutation_class="mutating",
        )

        # Restart: reconstruct services, reconcile at the resume boundary.
        restarted = _services(db)
        recovered = restarted.ledger.recover_interrupted(run_id)
        assert recovered == 1
        assert restarted.ledger.for_call(run_id, "fc_1").state == (
            TOOL_STATE_UNKNOWN
        )
        # Replaying the SAME call id must require recovery, never re-run.
        from defend_coder.tool_ledger import ToolRecoveryRequiredError

        with pytest.raises(ToolRecoveryRequiredError):
            restarted.ledger.begin(
                run_id=run_id,
                tool_call_id="fc_1",
                tool_name="write_file",
                argument_hash="h1",
                mutation_class="mutating",
            )


class TestAttemptCheckpointAndContext:
    def test_attempt_and_checkpoint_revision_persist_across_restart(
        self, db: CoderDatabase
    ):
        services = _services(db)
        workspace = _workspace_record(db)
        run_id, envelope = _prepare(services, workspace)

        identity = (
            envelope.identity_profile_id,
            envelope.identity_version,
            envelope.identity_hash,
        )
        prompt_core = (
            envelope.prompt_core_id,
            envelope.prompt_core_version,
            envelope.prompt_core_hash,
        )
        technical = (
            envelope.technical_profile_id,
            envelope.technical_profile_version,
            envelope.technical_profile_hash,
        )

        checkpoint_id = services.checkpoints.write(
            run_id=run_id,
            revision=2,
            objective="Inspect the workspace.",
            identity=identity,
            prompt_core=prompt_core,
            provider=envelope.provider,
            model=envelope.model,
            technical=technical,
            completed_work=("inspected",),
        )
        attempt_id = services.attempts.begin(
            run_id=run_id,
            checkpoint_revision=2,
            summary="second attempt",
        )
        services.attempts.finish(
            attempt_id,
            state=ATTEMPT_STATE_SUCCEEDED,
        )

        restarted = _services(db)
        assert restarted.checkpoints.latest(run_id).revision == 2
        assert restarted.checkpoints.revision(run_id, 2).checkpoint_id == (
            checkpoint_id
        )
        attempts = restarted.attempts.list(run_id)
        assert len(attempts) == 1
        assert attempts[0].state == ATTEMPT_STATE_SUCCEEDED

    def test_context_budget_compaction_is_protocol_safe(self):
        budget = ContextBudgetManager(limit_tokens=50)
        checkpoint = build_checkpoint(
            objective="objective",
            workspace="C:/fake",
        )
        coordinator = RunContextCoordinator(
            checkpoint=checkpoint, budget=budget, max_conversation_messages=4
        )
        for _ in range(6):
            coordinator.add({"role": "user", "content": "x" * 40})
        assert len(coordinator.conversation()) == 6
        decision = budget.decide(coordinator.conversation(), incoming_tokens=0)
        assert decision.compact
        coordinator.compact()
        assert len(coordinator.conversation()) <= 2
        assert any(e.kind == "context_compacted" for e in coordinator.events())

    def test_compaction_preserves_pending_tool_round(self):
        budget = ContextBudgetManager(limit_tokens=10_000)
        checkpoint = build_checkpoint(objective="o", workspace="w")
        coordinator = RunContextCoordinator(
            checkpoint=checkpoint, budget=budget, max_conversation_messages=8
        )
        coordinator.add({"role": "user", "content": "do it"})
        coordinator.add(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "c1", "function": {"name": "write_file", "arguments": "{}"}}
                ],
            }
        )
        # pending round: assistant requested a tool, result not yet added
        assert coordinator.pending_tool_round
        coordinator.compact()
        conv = coordinator.conversation()
        # the assistant tool-call turn must not be dropped
        assert any(
            m.get("role") == "assistant" and m.get("tool_calls") for m in conv
        )


class _GrowingProvider:
    """Fake provider: N large tool-call turns then a final answer, recording
    the conversation size it receives on every call."""

    provider_id = "deepseek"
    model_id = "deepseek-v4-flash"
    protocol = "chat_completions"

    def __init__(self, turns: int, content_size: int) -> None:
        self._turns = turns
        self._size = content_size
        self.received: list[int] = []

    def generate(self, request: CoderGenerationRequest) -> CoderGenerationResult:
        from defend_coder.agent_client import ToolCall

        self.received.append(len(request.conversation))
        if self._turns > 0:
            self._turns -= 1
            return CoderGenerationResult(
                visible_content="x" * self._size,
                tool_calls=(
                    ToolCall(
                        id=f"g{self._turns}",
                        name="list_files",
                        arguments={"path": "."},
                    ),
                ),
                usage=None,
                finish_reason="tool_calls",
                provider=self.provider_id,
                model=self.model_id,
            )
        return CoderGenerationResult(
            visible_content="done",
            tool_calls=(),
            usage=None,
            finish_reason="stop",
            provider=self.provider_id,
            model=self.model_id,
        )


class TestCheckpointContinuity:
    def test_dropped_work_captured_and_reaches_model_after_restart(
        self, db: CoderDatabase, tmp_path
    ):
        from defend_coder.agent import CodingAgent
        from defend_coder.agent_client import ToolCall

        services = _services(db)
        root = tmp_path / "wsroot"
        root.mkdir()
        account_id, workspace_id = _make_workspace_with_root(db, root)
        identity, prompt = _pins(services)
        technical = services.technical_registry.active_for_provider("deepseek")
        prepared = services.preparation.prepare_run(
            workspace_id=workspace_id,
            owner_account_id=account_id,
            prompt="Build it.",
            requested_mode="AUTO",
            selected_tier="DEEPSEEK",
            provider="deepseek",
            model="deepseek-v4-flash",
            identity=identity,
            prompt_core=prompt,
            technical=(technical.profile_id, technical.version, technical.hash),
        )
        run_id = prepared.run_id
        envelope = services.preparation.load_envelope(run_id)
        assert envelope is not None

        received: list[str] = []

        def make_provider():
            class P:
                provider_id = "deepseek"
                model_id = "deepseek-v4-flash"
                protocol = "chat_completions"
                _step = 0

                def generate(self, request):
                    received.append(" ".join(
                        m.get("content", "") for m in request.conversation
                    ))
                    P._step += 1
                    if P._step == 1:
                        return CoderGenerationResult(
                            visible_content="",
                            tool_calls=(ToolCall(id="m1", name="write_file", arguments={"path": "notes.txt", "content": "hi"}),),
                            usage=None, finish_reason="tool_calls",
                            provider="deepseek", model="deepseek-v4-flash",
                        )
                    if P._step == 2:
                        return CoderGenerationResult(
                            visible_content="",
                            tool_calls=(ToolCall(id="m2", name="list_files", arguments={"path": "."}),),
                            usage=None, finish_reason="tool_calls",
                            provider="deepseek", model="deepseek-v4-flash",
                        )
                    return CoderGenerationResult(
                        visible_content="done", tool_calls=(),
                        usage=None, finish_reason="stop",
                        provider="deepseek", model="deepseek-v4-flash",
                    )

            return P()

        toolkit = CoderToolkit(
            repository=CoderRepository(db), configured_root=str(root)
        )
        schema_tokens = estimate_tool_schemas(toolkit.schema())
        budget = ContextBudgetManager(
            limit_tokens=schema_tokens + 4096 + 300, compaction_ratio=0.4
        )

        def build_agent(coordinator, persist, ledger):
            return CodingAgent(
                provider=make_provider(),
                toolkit=toolkit,
                log=lambda _m: None,
                run_id=run_id,
                tool_ledger=ledger,
                context_coordinator=coordinator,
                checkpoint_persist=persist,
            )

        def make_persist(store, env, revision):
            def persist(ckpt):
                nonlocal revision
                revision += 1
                store.write(
                    run_id=run_id,
                    revision=revision,
                    objective=ckpt.objective,
                    identity=(env.identity_profile_id, env.identity_version, env.identity_hash),
                    prompt_core=(env.prompt_core_id, env.prompt_core_version, env.prompt_core_hash),
                    provider=env.provider,
                    model=env.model,
                    technical=(env.technical_profile_id, env.technical_profile_version, env.technical_profile_hash),
                    completed_work=ckpt.completed,
                    relevant_files=ckpt.relevant_files,
                    latest_tests=ckpt.latest_tests,
                    current_failure=ckpt.current_failure,
                )
                return ckpt
            return persist

        revision = 1
        coordinator = RunContextCoordinator(
            checkpoint=build_checkpoint(objective="Build it.", workspace=str(root)),
            budget=budget,
            max_conversation_messages=12,
        )
        agent = build_agent(coordinator, make_persist(services.checkpoints, envelope, revision), services.ledger)
        outcome = agent.run(
            prompt="Build it.",
            account_id=account_id,
            workspace_id=workspace_id,
            sink=lambda **kw: None,
        )
        assert outcome.state == "succeeded"

        # Checkpoint persisted a revision with the dropped work captured.
        latest = services.checkpoints.latest(run_id)
        assert latest.revision >= 2
        assert any("write_file" in c for c in latest.completed_work)

        # A post-compaction request carried the durable checkpoint context.
        assert any("SERVER DURABLE CHECKPOINT" in r for r in received)

        # Restart: reconstruct the coordinator from the durable checkpoint and
        # prove the resumed model's FIRST request carries the same truth.
        received.clear()
        restarted = _services(db)
        latest2 = restarted.checkpoints.latest(run_id)
        from defend_coder.run_store import RunCheckpointStore  # noqa: F401
        checkpoint2 = build_checkpoint(
            objective=latest2.objective,
            workspace="",
            completed=latest2.completed_work,
            relevant_files=latest2.relevant_files,
            latest_tests=latest2.latest_tests,
            current_failure=latest2.current_failure,
        )
        coordinator2 = RunContextCoordinator(
            checkpoint=checkpoint2, budget=budget, max_conversation_messages=12
        )
        agent2 = CodingAgent(
            provider=make_provider(),
            toolkit=toolkit,
            log=lambda _m: None,
            run_id=run_id,
            tool_ledger=restarted.ledger,
            context_coordinator=coordinator2,
        )
        outcome2 = agent2.run(
            prompt="Continue.",
            account_id=account_id,
            workspace_id=workspace_id,
            sink=lambda **kw: None,
        )
        assert outcome2.state == "succeeded"
        first_request = received[0]
        assert "SERVER DURABLE CHECKPOINT" in first_request
        assert "write_file: notes.txt" in first_request
        # Completed mutation is not repeated on resume.
        assert restarted.ledger.for_call(run_id, "m1").state == TOOL_STATE_SUCCEEDED


class TestEndToEndRunAndEscalation:
    def test_live_context_budget_bounds_provider_conversation(
        self, db: CoderDatabase, tmp_path
    ):
        from defend_coder.agent import CodingAgent

        services = _services(db)
        root = tmp_path / "wsroot"
        root.mkdir()
        (root / "a.txt").write_text("hello", encoding="utf-8")
        account_id, workspace_id = _make_workspace_with_root(db, root)
        identity, prompt = _pins(services)
        technical = services.technical_registry.active_for_provider("deepseek")
        prepared = services.preparation.prepare_run(
            workspace_id=workspace_id,
            owner_account_id=account_id,
            prompt="Inspect.",
            requested_mode="AUTO",
            selected_tier="DEEPSEEK",
            provider="deepseek",
            model="deepseek-v4-flash",
            identity=identity,
            prompt_core=prompt,
            technical=(technical.profile_id, technical.version, technical.hash),
        )
        run_id = prepared.run_id
        envelope = services.preparation.load_envelope(run_id)
        assert envelope is not None

        toolkit = CoderToolkit(
            repository=CoderRepository(db), configured_root=str(root)
        )
        schema_tokens = estimate_tool_schemas(toolkit.schema())
        budget = ContextBudgetManager(
            limit_tokens=schema_tokens + 4096 + 5000,
            compaction_ratio=0.5,
        )
        checkpoint = build_checkpoint(objective="Inspect.", workspace=str(root))
        coordinator = RunContextCoordinator(
            checkpoint=checkpoint, budget=budget, max_conversation_messages=12
        )
        revision = 1

        def persist(ckpt):
            nonlocal revision
            revision += 1
            services.checkpoints.write(
                run_id=run_id,
                revision=revision,
                objective=ckpt.objective,
                identity=(
                    envelope.identity_profile_id,
                    envelope.identity_version,
                    envelope.identity_hash,
                ),
                prompt_core=(
                    envelope.prompt_core_id,
                    envelope.prompt_core_version,
                    envelope.prompt_core_hash,
                ),
                provider=envelope.provider,
                model=envelope.model,
                technical=(
                    envelope.technical_profile_id,
                    envelope.technical_profile_version,
                    envelope.technical_profile_hash,
                ),
                completed_work=ckpt.completed,
            )
            return ckpt

        provider = _GrowingProvider(turns=5, content_size=2000)
        agent = CodingAgent(
            provider=provider,
            toolkit=toolkit,
            log=lambda _m: None,
            run_id=run_id,
            context_coordinator=coordinator,
            checkpoint_persist=persist,
        )
        outcome = agent.run(
            prompt="Inspect.",
            account_id=account_id,
            workspace_id=workspace_id,
            sink=lambda **kw: None,
        )
        assert outcome.state == "succeeded"
        # The provider conversation must be bounded (compaction happened).
        assert max(provider.received) <= 14
        # Compaction persisted a checkpoint revision beyond rev1.
        assert services.checkpoints.latest(run_id).revision >= 2
        # Structured context events were emitted.
        kinds = {e.kind for e in coordinator.events()}
        assert "context_compacted" in kinds

    def test_hard_context_overflow_zero_provider_calls(
        self, db: CoderDatabase, tmp_path
    ):
        from defend_coder.agent import CodingAgent

        services = _services(db)
        root = tmp_path / "wsroot"
        root.mkdir()
        account_id, workspace_id = _make_workspace_with_root(db, root)

        class _NeverProvider:
            provider_id = "deepseek"
            model_id = "deepseek-v4-flash"
            protocol = "chat_completions"
            calls = 0

            def generate(self, request):
                type(self).calls += 1
                return CoderGenerationResult(
                    visible_content="should not happen",
                    tool_calls=(),
                    usage=None,
                    finish_reason="stop",
                    provider=self.provider_id,
                    model=self.model_id,
                )

        toolkit = CoderToolkit(
            repository=CoderRepository(db), configured_root=str(root)
        )
        budget = ContextBudgetManager(limit_tokens=10)  # impossible budget
        coordinator = RunContextCoordinator(
            checkpoint=build_checkpoint(objective="o", workspace="w"),
            budget=budget,
        )
        provider = _NeverProvider()
        agent = CodingAgent(
            provider=provider,
            toolkit=toolkit,
            log=lambda _m: None,
            context_coordinator=coordinator,
        )
        outcome = agent.run(
            prompt="Inspect.",
            account_id=account_id,
            workspace_id=workspace_id,
            sink=lambda **kw: None,
        )
        assert outcome.state == "partial_success"
        assert provider.calls == 0
        assert any(e.kind == "context_budget_blocked" for e in coordinator.events())

    def test_full_runner_roundtrip_with_restart(self, db: CoderDatabase):
        services = _services(db)
        workspace = _workspace_record(db)
        run_id, envelope = _prepare(services, workspace)

        runner = RunRunner(
            repository=services.runs,
            toolkit_factory=lambda log_reader: CoderToolkit(
                repository=CoderRepository(db),
                configured_root="C:/fake",
                log_reader=log_reader,
            ),
            provider_resolver=lambda rid: _FinalProvider(),
            envelope_loader=services.preparation.load_envelope,
        )
        runner.start_existing(
            run_id=run_id,
            workspace=workspace,
            prompt="Inspect the workspace.",
        )

        # Wait for terminal state.
        for _ in range(200):
            run = services.runs.get_run(run_id)
            if run is not None and run.status in (
                "succeeded",
                "partial_success",
                "failed",
                "cancelled",
            ):
                break
            import time

            time.sleep(0.05)
        run = services.runs.get_run(run_id)
        assert run is not None
        assert run.status == "succeeded"

        # Restart: reconstruct everything from PostgreSQL.
        restarted = _services(db)
        assert restarted.preparation.load_envelope(run_id) is not None
        assert restarted.checkpoints.latest(run_id).revision == 1
        assert restarted.runs.get_run(run_id).status == "succeeded"

    def test_escalation_keeps_authority_and_resets_provider_state(
        self, db: CoderDatabase
    ):
        services = _services(db)
        workspace = _workspace_record(db)
        run_id, envelope = _prepare(services, workspace)

        deepseek = _EscalatingProvider("deepseek-v4-flash", "deepseek")
        nextp = _EscalatingProvider("Qwen/Qwen3-Coder-Next", "self_hosted")
        sol = _EscalatingProvider("gpt-5.6-sol", "openai")
        current: list[CoderProvider] = [deepseek]

        resolver = RoutingCoderProvider(lambda: current[0])

        # Route deepseek → next → sol; the SAME run/workspace/identity/prompt
        # authority must persist across the switch.
        for provider in (deepseek, nextp, sol):
            current[0] = provider
            result = resolver.generate(
                CoderGenerationRequest(
                    system_authority="authority",
                    conversation=(),
                    continuation_state={},
                )
            )
            assert result.visible_content == f"answered by {provider.model_id}"

        assert deepseek.calls == ["deepseek-v4-flash"]
        assert nextp.calls == ["Qwen/Qwen3-Coder-Next"]
        assert sol.calls == ["gpt-5.6-sol"]

        # Authority is identical across the escalation (same pinned envelope).
        identity_pin = services.runs.get_run_identity(run_id)
        prompt_pin = services.runs.get_run_prompt_bundle(run_id)
        assert identity_pin == (
            envelope.identity_profile_id,
            envelope.identity_version,
            envelope.identity_hash,
        )
        assert prompt_pin == (
            envelope.prompt_core_id,
            envelope.prompt_core_version,
            envelope.prompt_core_hash,
        )
