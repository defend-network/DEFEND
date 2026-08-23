"""Control Center PLATFORM service (owner interface for shared infrastructure).

The PLATFORM tab is the owner interface for genuinely NEUTRAL shared
infrastructure - never product settings. This service assembles the sections
the first milestone must deliver honestly (Section 30):

- OVERVIEW        four-product supervision summary + posture
- CREDENTIALS     read-only entitlement view over the shared secure store
- INFRASTRUCTURE  real observable host/runtime/data-root facts
- AUDIT           neutral, redacted platform events
- DATABASE/STORAGE  read-only inventory of known persistence roots
- MEMBERSHIP        identity authority note (consumer membership NOT_CONFIGURED)
- BILLING           neutral primitives note (consumer charging NOT_IMPLEMENTED)
- NETWORKING        product-owned origins/ports (Cloudflare NOT_CONFIGURED)

Where repository truth does not exist yet the section is explicitly reported
NOT_CONFIGURED / NOT_IMPLEMENTED - never fabricated.
"""

from __future__ import annotations

import os
import platform as _platform
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from .platform_audit import PlatformAuditLog
from .platform_credentials import PlatformCredentialRegistry
from .supervision import ProductSupervisionManifestStore, validate_product_manifests

_PRODUCT_PROCESS_PREFIXES = {
    "sports": "sports",
    "coder": "coder",
    "scs": "scs",
    "scs-ai": "scs",
    "defend": "defend",
    "defend-ai": "defend",
}


def _canonical_product_state(raw: str) -> str:
    lowered = (raw or "").strip().casefold()
    if lowered in ("running", "ready"):
        return "RUNNING"
    if lowered in (
        "starting",
        "starting_local",
        "preparing",
        "provisioning",
        "approval_required",
        "runtime ready",
    ):
        return "STARTING"
    if lowered in ("stopped", "not configured", "not_configured", "stopped_retained"):
        return "STOPPED"
    if lowered in ("degraded",):
        return "DEGRADED"
    if lowered in ("failed", "no_offer", "unavailable", "no offer"):
        return "FAILED"
    return "UNKNOWN"


def _node_version() -> str:
    try:
        completed = subprocess.run(
            ["node", "--version"],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
        value = (completed.stdout or "").strip()
        return value if value else "UNKNOWN"
    except Exception:
        return "UNKNOWN"


class PlatformService:
    """Read-only owner-facing aggregation of neutral platform facts."""

    def __init__(
        self,
        *,
        supervision: ProductSupervisionManifestStore | None = None,
        credential_registry: PlatformCredentialRegistry | None = None,
        audit: PlatformAuditLog | None = None,
        supervisor: object | None = None,
        products: tuple[object, ...] = (),
        settings: object | None = None,
        repository: Path | None = None,
    ) -> None:
        self._supervision = supervision
        self._credentials = credential_registry
        self._audit = audit
        self._supervisor = supervisor
        self._products = tuple(products)
        self._settings = settings
        self._repository = Path(repository) if repository is not None else None
        self._seen_states: dict[str, str] = {}
        self._seen_collisions: set[tuple[str, str, int]] = set()

    def record(
        self,
        event_type: str,
        *,
        product_id: str | None = None,
        detail: str | None = None,
    ) -> None:
        """Forward a neutral platform event into the audit log (best effort)."""
        if self._audit is not None:
            try:
                self._audit.record(
                    event_type, product_id=product_id, detail=detail
                )
            except Exception:
                pass

    # ------------------------------------------------------------------ core

    def product_status_rows(self) -> tuple[dict[str, Any], ...]:
        manifests = (
            self._supervision.all() if self._supervision is not None else ()
        )
        by_id = {product_id: manifest for product_id, manifest in (
            (m.product_id, m) for m in manifests
        )}
        services = {
            getattr(product, "application_id", ""): product
            for product in self._products
        }
        process_rows = self._process_rows()
        rows: list[dict[str, Any]] = []
        for product_id in sorted(by_id):
            manifest = by_id[product_id]
            service = services.get(product_id)
            reported = None
            last_error = None
            if service is not None:
                try:
                    status = service.status()
                    reported = getattr(status, "state", None)
                    last_error = getattr(status, "last_error", None)
                except Exception:
                    reported = None
            owned = process_rows.get(product_id, ())
            rows.append(
                {
                    "product_id": product_id,
                    "display_name": manifest.display_name,
                    "state": _canonical_product_state(reported or "stopped"),
                    "reported_state": reported or "unavailable",
                    "owned_processes": list(owned),
                    "api_port": manifest.api_port,
                    "web_port": manifest.web_port,
                    "open_url": manifest.open_url,
                    "last_error": last_error,
                }
            )
        return tuple(rows)

    def collision_report(self) -> dict[str, Any]:
        if self._supervision is None:
            return {"result": "UNKNOWN", "collisions": [], "unknown": []}
        report = validate_product_manifests(self._supervision.all())
        for collision in report.get("collisions", []):
            signature = (
                str(collision["product_a"]),
                str(collision["product_b"]),
                int(collision["port"]),
            )
            if signature in self._seen_collisions:
                continue
            self._seen_collisions.add(signature)
            self.record(
                "manifest_collision",
                detail=(
                    f"{collision['product_a']} ({collision['component_a']}) "
                    f"and {collision['product_b']} ({collision['component_b']}) "
                    f"share port {collision['port']}"
                ),
            )
        return report

    def overview(self) -> dict[str, Any]:
        rows = self.product_status_rows()
        self._record_health_transitions(rows)
        running = sum(1 for row in rows if row["state"] == "RUNNING")
        starting = sum(1 for row in rows if row["state"] == "STARTING")
        attention = sum(
            1
            for row in rows
            if row["state"] in ("DEGRADED", "FAILED", "UNKNOWN", "EXTERNAL")
        )
        stopped = sum(1 for row in rows if row["state"] == "STOPPED")
        credentials = (
            self._credentials.to_dict() if self._credentials is not None else {}
        )
        return {
            "products": list(rows),
            "posture": {
                "total": len(rows),
                "running": running,
                "starting": starting,
                "stopped": stopped,
                "attention": attention,
            },
            "collisions": self.collision_report(),
            "credentials": {
                "total": credentials.get("total", 0),
                "configured": credentials.get("configured", 0),
                "verified": credentials.get("verified", 0),
            },
            "audit_entries": (
                len(self._audit.snapshot()) if self._audit is not None else 0
            ),
        }

    def credentials_view(self) -> dict[str, Any]:
        if self._credentials is None:
            return {
                "credentials": [],
                "total": 0,
                "configured": 0,
                "verified": 0,
                "status": "NOT_CONFIGURED",
            }
        data = self._credentials.to_dict()
        data["status"] = "CONFIGURED"
        return data

    def infrastructure(self) -> dict[str, Any]:
        host = _platform.node() or os.environ.get("COMPUTERNAME") or "UNKNOWN"
        os_name = f"{_platform.system()} {_platform.release()}".strip() or "UNKNOWN"
        data_roots = self._data_roots()
        disk: dict[str, Any] = {}
        for label, root in data_roots.items():
            try:
                usage = shutil.disk_usage(root)
                disk[label] = {
                    "root": str(root),
                    "total_gb": round(usage.total / (1024**3), 1),
                    "free_gb": round(usage.free / (1024**3), 1),
                }
            except (OSError, ValueError):
                disk[label] = {"root": str(root), "status": "UNKNOWN"}
        return {
            "host": host,
            "os": os_name,
            "python": sys.version.split()[0] if sys.version else "UNKNOWN",
            "node": _node_version(),
            "data_roots": {
                label: {"root": str(root)} for label, root in data_roots.items()
            },
            "disk": disk,
            "processes": self._supervisor_process_rows(),
            "shared_secret_store": "DEFEND DPAPI (secrets.dpapi)",
        }

    def audit_view(self) -> dict[str, Any]:
        if self._audit is None:
            return {"entries": [], "status": "NOT_CONFIGURED"}
        return self._audit.to_dict()

    def database_storage(self) -> dict[str, Any]:
        data_roots = self._data_roots()
        inventory = [
            {
                "area": label,
                "location": str(root),
                "durability": "UNKNOWN",
                "backup": "UNKNOWN",
                "contains_private_data": "UNKNOWN",
                "migration_risk": "UNKNOWN",
            }
            for label, root in data_roots.items()
        ]
        return {
            "status": "INVENTORY",
            "hosted_postgres": "NOT_CONFIGURED",
            "inventory": inventory,
        }

    def membership(self) -> dict[str, Any]:
        return {
            "status": "NOT_CONFIGURED",
            "identity_authority": "defend_data.identity_store (canonical local owner identity)",
            "note": "Consumer account/org/membership/entitlement system is a future neutral-platform milestone.",
        }

    def billing(self) -> dict[str, Any]:
        return {
            "status": "NOT_IMPLEMENTED",
            "neutral_primitives": "defend_control.coder_billing (account, credit balance, usage ledger, spending limits)",
            "note": "No consumer charging, no Stripe, no customer money in this milestone. Numbers are owner-configurable policy later.",
        }

    def networking(self) -> dict[str, Any]:
        origins: list[dict[str, str]] = []
        if self._supervision is not None:
            for manifest in self._supervision.all():
                if manifest.open_url:
                    origins.append(
                        {
                            "product_id": manifest.product_id,
                            "origin": manifest.open_url,
                            "api_port": str(manifest.api_port) if manifest.api_port else "—",
                            "web_port": str(manifest.web_port) if manifest.web_port else "—",
                        }
                    )
        return {
            "status": "OBSERVED",
            "product_origins": origins,
            "cloudflare": "NOT_CONFIGURED",
            "tunnel_state": "NOT_OBSERVABLE",
            "collisions": self.collision_report(),
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "overview": self.overview(),
            "credentials": self.credentials_view(),
            "infrastructure": self.infrastructure(),
            "database_storage": self.database_storage(),
            "membership": self.membership(),
            "billing": self.billing(),
            "networking": self.networking(),
            "audit": self.audit_view(),
        }

    def _record_health_transitions(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            product_id = str(row.get("product_id") or "?")
            state = str(row.get("state") or "UNKNOWN")
            previous = self._seen_states.get(product_id)
            if previous is None:
                self._seen_states[product_id] = state
                continue
            if previous != state:
                self._seen_states[product_id] = state
                self.record(
                    "health_transition",
                    product_id=product_id,
                    detail=f"{previous} -> {state}",
                )

    # ------------------------------------------------------------- internals

    def _data_roots(self) -> dict[str, Path]:
        roots: dict[str, Path] = {}
        candidates = {
            "defend_data": os.environ.get("DEFEND_DATA_ROOT"),
            "coder_data": os.environ.get("CODER_WORKSPACE_ROOT"),
            "scs_data": os.environ.get("SCS_DATA_ROOT"),
            "sports_data": os.environ.get("SPORTS_DATA_ROOT"),
        }
        for label, raw in candidates.items():
            if raw and raw.strip():
                roots[label] = Path(raw)
        if self._settings is not None:
            for attr, label in (
                ("coder_workspace_root", "coder_data"),
                ("scs_data_root", "scs_data"),
                ("sports_data_root", "sports_data"),
            ):
                value = getattr(self._settings, attr, None)
                if value is not None and label not in roots:
                    roots[label] = Path(value)
        if self._repository is not None:
            roots.setdefault("repository", self._repository)
        return roots

    def _supervisor_process_rows(self) -> list[dict[str, Any]]:
        snapshot = getattr(self._supervisor, "snapshot", None)
        if not callable(snapshot):
            return []
        try:
            items = snapshot()
        except Exception:
            return []
        rows: list[dict[str, Any]] = []
        for item in items or ():
            rows.append(
                {
                    "name": getattr(item, "name", "?"),
                    "pid": getattr(item, "pid", None),
                    "owned": bool(getattr(item, "owned", False)),
                    "running": bool(getattr(item, "running", False)),
                    "health_url": getattr(item, "health_url", None),
                }
            )
        return rows

    def _process_rows(self) -> dict[str, tuple[dict[str, Any], ...]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in self._supervisor_process_rows():
            prefix = (row["name"] or "").split(":")[0]
            product_id = _PRODUCT_PROCESS_PREFIXES.get(prefix)
            if product_id is None:
                continue
            grouped.setdefault(product_id, []).append(row)
        return {
            product_id: tuple(rows) for product_id, rows in grouped.items()
        }
