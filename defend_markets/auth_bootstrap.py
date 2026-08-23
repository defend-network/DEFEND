"""DEFENDmarkets owner-auth bootstrap (M4.8.2C-R).

Replaces the former silent ``try/except: pass`` around identity-store setup with
an explicit, observable auth state machine. Owner login availability is now a
first-class product health signal, not a hidden failure.

Credential resolution order (per M4.8.2C-R section 13):
    1. explicit process environment (DEFEND_OWNER_USER/PASS/EMAIL)
    2. existing neutral encrypted DEFEND credential store (DPAPI, the SAME
       single file the Control Center uses — no second secret file)
    3. NOT_CONFIGURED

No secret value is ever logged or returned. Only sanitized state is exposed.

Identity authority remains the legacy shared owner identity (defend_data
identity store). This module does NOT perform the neutral-platform identity
migration; that is a separate platform milestone.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

AuthBootstrapState = Literal[
    "READY",
    "NOT_CONFIGURED",
    "STORE_UNAVAILABLE",
    "INVALID_CONFIGURATION",
    "FAILED",
]

_OWNER_ENV_KEYS = ("DEFEND_OWNER_USER", "DEFEND_OWNER_PASS", "DEFEND_OWNER_EMAIL")


@dataclass(frozen=True)
class OwnerAuthBootstrap:
    state: AuthBootstrapState
    identity_store: str
    credentials_configured: bool
    detail: str = ""
    error_class: str = ""


def _resolve_from_environment() -> dict[str, str] | None:
    """Return owner credential env values when all required keys are present."""
    values: dict[str, str] = {}
    for key in _OWNER_ENV_KEYS:
        raw = os.environ.get(key, "")
        if not raw.strip():
            return None
        values[key] = raw.strip()
    return values


def _resolve_from_shared_store() -> dict[str, str] | None:
    """Resolve owner credentials from the SAME encrypted DPAPI store the
    Control Center uses. Never copies them into Markets-owned permanent storage.
    """
    try:
        from defend_integrations.stores import default_secret_path
        from shared_platform.secure_store import DpapiSecretStore

        store = DpapiSecretStore(default_secret_path())
        values = store.load()
    except Exception:
        # store unavailable or unreadable — report, do not crash
        return None

    resolved: dict[str, str] = {}
    for key in _OWNER_ENV_KEYS:
        raw = values.get(key, "")
        if not raw.strip():
            return None
        resolved[key] = raw.strip()
    return resolved


def resolve_owner_credentials() -> tuple[AuthBootstrapState, dict[str, str] | None, str]:
    """Resolve owner credentials with explicit state, in canonical order."""
    env = _resolve_from_environment()
    if env is not None:
        return "READY", env, "environment"

    store = _resolve_from_shared_store()
    if store is not None:
        return "READY", store, "shared_store"

    # Distinguish "no credential anywhere" from "store present but unreadable".
    try:
        from defend_integrations.stores import default_secret_path

        has_store_file = default_secret_path().exists()
    except Exception:
        has_store_file = False

    if not has_store_file and not any(os.environ.get(k, "") for k in _OWNER_ENV_KEYS):
        return "NOT_CONFIGURED", None, ""
    return "NOT_CONFIGURED", None, "store unavailable or incomplete"


def bootstrap_owner_auth() -> OwnerAuthBootstrap:
    """Configure the shared identity authority and return an explicit state.

    Does NOT swallow failure silently: a failure is captured as a distinct
    state so health/launcher can truthfully report the workstation is not
    owner-ready, while login remains mounted (and returns a truthful 503).
    """
    state, credentials, source = resolve_owner_credentials()

    if state != "READY" or credentials is None:
        return OwnerAuthBootstrap(
            state=state,
            identity_store="legacy_shared_owner_identity",
            credentials_configured=False,
            detail=source,
            error_class="" if state == "NOT_CONFIGURED" else "credential_resolution_failed",
        )

    # Inject only the required owner keys into the child process environment for
    # the legacy admin_auth compatibility API. Never print them.
    for key in _OWNER_ENV_KEYS:
        os.environ[key] = credentials[key]

    try:
        import admin_auth as _admin_auth
        from defend_data.data_core import DataCore

        _admin_auth.configure_identity_store(DataCore().identity)
    except Exception as exc:  # noqa: BLE001 - explicit state, not silent
        return OwnerAuthBootstrap(
            state="FAILED",
            identity_store="legacy_shared_owner_identity",
            credentials_configured=True,
            detail=f"identity store configuration failed: {type(exc).__name__}",
            error_class=type(exc).__name__,
        )

    return OwnerAuthBootstrap(
        state="READY",
        identity_store="legacy_shared_owner_identity",
        credentials_configured=True,
        detail=f"resolved from {source}",
        error_class="",
    )
