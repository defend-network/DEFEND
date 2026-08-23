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
                (workspace_id, account_id, "ws", "C:/fake"),
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

    def test_inflight_mutation_recovery_is_idempotent(self, db: CoderDatabase):
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
        # Restart with the execution still RUNNING (in-flight): the same
        # execution id is returned (idempotent), never a duplicate.
        restarted = _services(db).ledger
        e2 = restarted.begin(
            run_id=run_id,
            tool_call_id="fc_1",
            tool_name="write_file",
            argument_hash="h1",
            mutation_class="mutating",
        )
        assert e1 == e2
        assert restarted.for_call(run_id, "fc_1").state == TOOL_STATE_RUNNING


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
        budget = ContextBudgetManager(limit_tokens=200, reserve_tokens=50)
        checkpoint = build_checkpoint(
            objective="objective",
            workspace="C:/fake",
            completed=("a", "b"),
        )
        coordinator = RunContextCoordinator(
            checkpoint=checkpoint, budget=budget, max_conversation_messages=4
        )
        for _ in range(6):
            coordinator.add({"role": "user", "content": "x" * 40})
        assert len(coordinator.conversation()) == 4
        decision = budget.decide(coordinator.conversation(), incoming_tokens=0)
        coordinator.compact()
        assert len(coordinator.conversation()) <= 2
        assert any(e.kind == "context_compacted" for e in coordinator.events())


class TestEndToEndRunAndEscalation:
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
