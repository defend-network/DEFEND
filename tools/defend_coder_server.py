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

    # Router integration: AUTO runs default to the DeepSeek managed-API
    # target when the product has a legitimate key configured; otherwise the
    # legacy single-model env path is preserved unchanged.
    from defend_coder.providers import (
        build_client,
        deepseek_target,
        next_target,
        sol_target,
    )

    deepseek = deepseek_target()
    targets = {
        "deepseek": deepseek,
        "Qwen/Qwen3-Coder-Next": next_target(),
        "gpt-5.6-sol": sol_target(),
    }

    def _secret_resolver(name: str) -> str | None:
        from defend_coder.providers import (
            DEEPSEEK_API_KEY_ENV,
            SOL_API_KEY_ENV,
        )
        from defend_control.secrets import DpapiSecretStore
        from pathlib import Path

        if name == "deepseek":
            value = os.environ.get(DEEPSEEK_API_KEY_ENV)
            if value:
                return value
        if name == "sol":
            value = os.environ.get(SOL_API_KEY_ENV)
            if value:
                return value
        try:
            store = DpapiSecretStore(
                Path(os.environ.get("LOCALAPPDATA", ".")) / "DEFEND" / "secrets.dpapi"
            )
            values = store.load()
        except Exception:
            return None
        return values.get("DEEPSEEK_API_KEY") or values.get("OPENAI_API_KEY")

    if model_config.base_url is not None or deepseek.availability:
        if deepseek.availability:
            key = _secret_resolver("deepseek")
            client = build_client(deepseek, api_key=key)
            print(
                "DEFENDcoder agent: AUTO default=deepseek "
                f"model={deepseek.model_id}",
                file=sys.stderr,
            )
        else:
            client = AgentChatClient(model_config)
            print(
                f"DEFENDcoder agent: model={model_config.model_name} "
                f"alias={model_config.alias}",
                file=sys.stderr,
            )
        runner = RunRunner(
            repository=runs_repository,
            client=client,
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
            f"DEFENDcoder agent: max_steps={settings.max_steps} "
            f"max_run_seconds={settings.max_run_seconds:.0f} "
            f"finalization_enabled={settings.finalization_enabled}",
            file=sys.stderr,
        )
    else:
        print(
            "DEFENDcoder agent: no model endpoint configured; "
            "agent runs are disabled until the model runtime is wired",
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