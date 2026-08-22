"""Local/control-plane entrypoint for the DEFENDcoder API.

Startup:
CoderSettings -> PostgreSQL -> migrations -> repository -> authentication
-> model agent wiring -> FastAPI -> uvicorn.

The model runtime remains a separate service owned by Control Center. The
control plane publishes a shared status file (CODER_MODEL_STATUS_FILE)
that this process reads for the consumer runtime status; when the file is
missing or stale the status is honestly OFFLINE.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import uvicorn

from defend_coder.agent_client import AgentChatClient
from defend_coder.app import build_coder_app
from defend_coder.auth import AuthService
from defend_coder.config import CoderSettings
from defend_coder.db import CoderDatabase
from defend_coder.model_config import load_model_config
from defend_coder.repositories import CoderRepository
from defend_coder.runs import RunRunner, RunsRepository
from defend_coder.tools import CoderToolkit

DEFAULT_STATUS_FILE = str(
    Path(
        os.environ.get("LOCALAPPDATA", ".")
    )
    / "DEFEND"
    / "coder-model-status.json"
)

_STATUS_STATE_MAP = {
    "ready": "ready",
    "starting": "starting",
    "offline": "offline",
    "failed": "failed",
    "running": "ready",
    "starting_local": "starting",
    "provisioning": "starting",
    "preparing": "starting",
    "approval_required": "starting",
    "stopped": "offline",
    "no_offer": "offline",
}


def runtime_status() -> dict[str, object]:
    """Read the model status published by Control Center.

    The status file is the single source of truth for the consumer
    runtime view; the control plane writes it from its own observations.
    """
    status_path = os.environ.get("CODER_MODEL_STATUS_FILE")
    if not status_path:
        status_path = DEFAULT_STATUS_FILE

    try:
        raw = json.loads(
            Path(status_path).read_text(encoding="utf-8")
        )
    except OSError:
        return {
            "state": "offline",
            "provider": None,
            "model": None,
            "alias": None,
            "context_limit": None,
            "context_used": None,
            "detail": (
                "Control Center is not publishing coder runtime status"
            ),
        }
    except ValueError:
        return {
            "state": "offline",
            "provider": None,
            "model": None,
            "alias": None,
            "context_limit": None,
            "context_used": None,
            "detail": "published coder runtime status is malformed",
        }

    if not isinstance(raw, dict):
        return {
            "state": "offline",
            "provider": None,
            "model": None,
            "alias": None,
            "context_limit": None,
            "context_used": None,
            "detail": "published coder runtime status is malformed",
        }

    raw_state = str(raw.get("state") or "offline")
    state = _STATUS_STATE_MAP.get(raw_state, "offline")

    return {
        "state": state,
        "provider": raw.get("provider"),
        "model": raw.get("model_name"),
        "alias": raw.get("alias"),
        "context_limit": raw.get("context_limit"),
        "context_used": raw.get("context_used"),
        "detail": raw.get("detail"),
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
    from defend_coder.model_config import CoderModelConfig
    from defend_coder.providers import (
        DEFAULT_DEEPSEEK_MODEL,
        NEXT_MODEL,
        SOL_MODEL,
        build_client,
        deepseek_target,
        next_target,
        sol_target,
    )

    def _secret_store_loader() -> object:
        from pathlib import Path

        from defend_control.secrets import DpapiSecretStore

        local = os.environ.get("LOCALAPPDATA") or "."
        return DpapiSecretStore(Path(local) / "DEFEND" / "secrets.dpapi")

    credentials = CredentialStore(store_loader=_secret_store_loader)

    def _client_for(routing) -> object:
        model = (
            routing.selected_model
            if routing is not None and routing.selected_model
            else DEFAULT_DEEPSEEK_MODEL
        )
        live = {
            DEFAULT_DEEPSEEK_MODEL: deepseek_target(
                availability=credentials.configured("deepseek")
            ),
            NEXT_MODEL: next_target(),
            SOL_MODEL: sol_target(
                availability=credentials.configured("sol")
            ),
        }
        target = live.get(model)
        if target is None:
            raise ValueError(f"no configured target for model {model!r}")
        if target.managed_api:
            api_key = credentials.resolve(
                "deepseek" if model == DEFAULT_DEEPSEEK_MODEL else "sol"
            )
            if not api_key:
                raise ValueError(
                    f"provider {target.provider} requires a configured key"
                )
        else:
            api_key = None
        return build_client(target, api_key=api_key)

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
        # Base client is only used for policy/back-compat; real execution is
        # dispatched per-run through client_resolver.
        client=AgentChatClient(
            CoderModelConfig(
                alias="routing",
                model_name="routing",
                base_url="http://127.0.0.1:9/v1",
            )
        ),
        client_resolver=_client_for,
        proposal_factory=_proposal_for,
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
        runtime_status=runtime_status,
        repository=repository,
        runs_repository=runs_repository,
        runner=runner,
        configured_root=settings.workspace_root,
        targets=targets,
        secret_resolver=_secret_resolver,
    )

    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()