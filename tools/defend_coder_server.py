"""Standalone entrypoint for the DEFENDcoder product.

Startup:
CoderSettings -> PostgreSQL -> migrations -> repository -> authentication
-> model agent wiring -> FastAPI -> uvicorn.

DEFENDcoder is an independent product and owns its own model runtime and
runtime status. Control Center is an OPTIONAL supervisor only: it may launch
this process, read health/status, and stop the child it launched. It is NOT
required for startup, model routing, providers, runtime status, configuration,
or persistence.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

import uvicorn

from defend_coder.app import build_coder_app
from defend_coder.auth import AuthService
from defend_coder.config import CoderSettings
from defend_coder.db import CoderDatabase
from defend_coder.context import resolve_context_budget
from defend_coder.model_config import load_model_config
from defend_coder.preparation import RunPreparationService
from defend_coder.repositories import CoderRepository
from defend_coder.run_store import RunAttemptStore, RunCheckpointStore
from defend_coder.runs import RunRunner, RunsRepository
from defend_coder.runtime_status import coder_runtime_status
from defend_coder.tool_ledger import DurableToolLedger
from defend_coder.tools import CoderToolkit


def runtime_status() -> dict[str, object]:
    """DEFENDcoder-owned runtime status (derived from product authority).

    This is a placeholder closure; ``main`` binds it to the live credential
    store so it reports truthful provider configuration. Never a
    Control-Center-published artifact.
    """
    return {
        "state": "starting",
        "provider": None,
        "model": None,
        "alias": "DEFENDcoder",
        "context_limit": None,
        "context_used": None,
        "detail": "runtime status not yet bound",
    }


def main() -> None:
    settings = CoderSettings.from_env()

    database = CoderDatabase(settings.database_url)

    try:
        database.migrate()
    except Exception as error:
        print(
            "DEFENDcoder migration failed: "
            f"{type(error).__name__}: {error}",
            file=sys.stderr,
        )
        raise SystemExit(1) from error

    repository = CoderRepository(database)
    auth = AuthService(repository)
    runs_repository = RunsRepository(database)

    runner = None
    try:
        model_config = load_model_config()
    except ValueError as error:
        print(
            "DEFENDcoder model configuration error: "
            f"{type(error).__name__}: {error}",
            file=sys.stderr,
        )
        raise SystemExit(1) from error

    # Router integration (M2.1): strict, dynamic credential routing. There is
    # NO silent legacy fallback: AUTO is DeepSeek V4 Flash, and each run's
    # client is dispatched per-run from its persisted routing.
    from defend_coder.credentials import CredentialStore
    from defend_coder.identity import default_identity_profile
    from defend_coder.provider_adapters import CoderProviderFactory
    from defend_coder.providers import DEFAULT_DEEPSEEK_MODEL
    from defend_coder.registry import (
        IdentityRegistry,
        PromptAuthorityComposer,
        PromptBundleRegistry,
        ProviderTechnicalRegistry,
        RunAuthorityResolver,
        build_prompt_core_bundle,
    )

    def _secret_store_loader() -> object:
        from pathlib import Path

        from shared_platform.dpapi import DpapiSecretStore

        local = os.environ.get("LOCALAPPDATA") or "."
        return DpapiSecretStore(Path(local) / "DEFEND" / "secrets.dpapi")

    credentials = CredentialStore(store_loader=_secret_store_loader)

    # Concrete product-owned runtime manager (production authority; never the
    # test fake). Fails closed: NEXT is ABSENT/STOPPED until provisioned.
    from defend_coder.runtime.factory import build_runtime_manager

    runtime_manager = build_runtime_manager(
        secret_source=_secret_store_loader(),
        state_directory=(
            str(Path(os.environ.get("LOCALAPPDATA", ".")) / "DEFEND" / "coder-lifecycle")
        ),
    )

    def _runtime_status() -> dict[str, object]:
        return coder_runtime_status(
            credentials,
            next_runtime=runtime_manager.runtime_status(),
        )

    # Durable authority: hydrate identity/prompt-core/technical profiles from
    # the immutable store. POSTGRES is the default production mode and FAILS
    # STARTUP on any store/hydration error (no silent memory fallback).
    from defend_coder.authority_store import (
        build_authority_store,
        hydrate_authority,
    )

    authority_store = build_authority_store(database)
    hydrated = hydrate_authority(authority_store)
    preparation = RunPreparationService(database)
    run_ledger = DurableToolLedger(database)
    checkpoint_store = RunCheckpointStore(database)
    attempt_store = RunAttemptStore(database)

    identity_registry = IdentityRegistry()
    for profile in hydrated.identity_profiles.values():
        identity_registry.register(profile)
    if hydrated.active_identity is not None:
        identity_registry.activate(
            hydrated.identity_profiles[hydrated.active_identity]
        )

    prompt_authority = PromptAuthorityComposer()
    prompt_registry = PromptBundleRegistry()
    for bundle in hydrated.prompt_cores.values():
        prompt_registry.register(bundle)
    if hydrated.active_prompt_core is not None:
        prompt_registry.activate(
            hydrated.prompt_cores[hydrated.active_prompt_core]
        )
    else:
        prompt_registry.activate(
            build_prompt_core_bundle(identity_registry.active(), prompt_authority)
        )

    technical_registry = ProviderTechnicalRegistry()
    for profile in hydrated.technical_profiles.values():
        technical_registry.register(profile)
    for provider in ("deepseek", "self_hosted", "openai"):
        active_key = authority_store.active_technical_for(provider)
        if active_key is not None:
            technical_registry.set_active_for_provider(provider, *active_key)

    authority_resolver = RunAuthorityResolver(
        identity_registry=identity_registry,
        prompt_registry=prompt_registry,
        technical_registry=technical_registry,
    )

    def _authority_for(run_id):
        """Resolve the EXACT pinned identity + provider-neutral prompt core,
        cross-validate, and compose the system authority. Fail closed."""
        identity_pin = runs_repository.get_run_identity(run_id)
        prompt_pin = runs_repository.get_run_prompt_bundle(run_id)
        routing = runs_repository.get_run_routing(run_id)
        route = None
        provider = DEFAULT_DEEPSEEK_MODEL
        if routing is not None:
            provider = routing.selected_model or DEFAULT_DEEPSEEK_MODEL
            route = (routing.requested_mode, routing.selected_model)
        if route is None:
            route = ("AUTO", provider)
        envelope = authority_resolver.resolve(
            run_id=str(run_id),
            identity_pin=identity_pin,
            prompt_pin=prompt_pin,
            route=route,
            provider=provider,
        )
        return authority_resolver.compose_authority(envelope)

    provider_factory = CoderProviderFactory(credentials)

    def _provider_for(run_id):
        """Resolve the ACTUAL CoderProvider from the current persisted route."""
        routing = runs_repository.get_run_routing(run_id)
        model = (
            routing.selected_model
            if routing is not None and routing.selected_model
            else DEFAULT_DEEPSEEK_MODEL
        )
        return provider_factory.for_model(model)

    def _proposal_for(run_id, outcome):
        # Deterministic, grounded auto-escalation: quality failures only, one
        # proposal per run (anti-spam), never for infrastructure failures.
        if outcome.state != "failed":
            return None
        if runs_repository.list_escalation_proposals(run_id):
            return None
        from defend_coder.router import (
            EscalationManager,
            EscalationReason,
        )
        from defend_coder.routing import propose_for_outcome

        routing = runs_repository.get_run_routing(run_id)
        current = (
            routing.selected_model
            if routing is not None
            else DEFAULT_DEEPSEEK_MODEL
        )
        return propose_for_outcome(
            manager=EscalationManager(),
            current_model=current,
            outcome=outcome,
            summary=(
                "Two repair attempts failed the same objective; "
                "DEFENDcoder recommends a stronger model."
            ),
            evidence=(str(outcome.reason or outcome.state),),
            attempt_count=2,
            tests_failed=1,
            reason_code=EscalationReason.REPEATED_TEST_FAILURE,
        )

    runner = RunRunner(
        repository=runs_repository,
        provider_resolver=_provider_for,
        proposal_factory=_proposal_for,
        authority_resolver=_authority_for,
        envelope_loader=preparation.load_envelope,
        tool_ledger=run_ledger,
        checkpoint_store=checkpoint_store,
        attempt_store=attempt_store,
        context_budget_factory=resolve_context_budget,
        toolkit_factory=lambda log_reader: CoderToolkit(
            repository=repository,
            configured_root=settings.workspace_root,
            log_reader=log_reader,
        ),
        max_steps=settings.max_steps,
        max_loop_seconds=settings.max_run_seconds,
        finalization_enabled=settings.finalization_enabled,
        finalization_timeout_seconds=settings.finalization_timeout_seconds,
    )
    print(
        f"DEFENDcoder agent: per-run routing (AUTO=deepseek-v4-flash) "
        f"max_steps={settings.max_steps} "
        f"max_run_seconds={settings.max_run_seconds:.0f} "
        f"finalization_enabled={settings.finalization_enabled}",
        file=sys.stderr,
    )

    app = build_coder_app(
        settings=settings,
        db=database,
        auth=auth,
        runtime_status=_runtime_status,
        repository=repository,
        runs_repository=runs_repository,
        runner=runner,
        configured_root=settings.workspace_root,
        credentials=credentials,
        identity_registry=identity_registry,
        prompt_registry=prompt_registry,
        prompt_authority=prompt_authority,
        technical_registry=technical_registry,
        preparation=preparation,
        attempt_store=attempt_store,
        checkpoint_store=checkpoint_store,
        tool_ledger=run_ledger,
        runtime_manager=runtime_manager,
    )

    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()