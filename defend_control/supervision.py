"""Control Center supervision contract (neutral, product-owned values).

Control Center is a SUPERVISOR, never a runtime authority. Products own their
lifecycle truth; this module defines the narrow manifest the Control Center
consumes plus two pure, fail-closed helpers:

- :class:`ProductSupervisionManifest` - the neutral supervision contract. The
  PRODUCT owns the values; Control Center only reads them.
- :func:`build_compatibility_manifests` - a BOUNDED compatibility adapter that
  sources manifest values from each product's OWNED environment configuration
  (``ProductsSettings.from_env`` reads product-owned env vars). It is explicitly
  labelled ``compatibility:`` because the products do not yet ship canonical
  manifest files of their own.
- :func:`validate_product_manifests` - cross-product collision validation that
  returns PASS / COLLISION / UNKNOWN and NEVER modifies anything.
- :func:`observe_product_state` - maps observed process/health signals onto the
  canonical status vocabulary. RUNNING is never inferred from port-open alone.

No product runtime policy lives here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from itertools import combinations
from pathlib import Path
from typing import Any


class ProductSupervisionState(str, Enum):
    """Canonical Control Center status vocabulary (Section 9).

    STOPPED    no supervised process and no reported runtime
    STARTING   owned process up, product not yet reporting healthy
    RUNNING    process identity + product health confirm readiness
    DEGRADED   partial readiness or health probe failing
    FAILED     owned process exited or start failed
    EXTERNAL   product running but NOT launched by Control Center
    UNKNOWN    insufficient evidence to classify
    """

    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    EXTERNAL = "EXTERNAL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ProductSupervisionManifest:
    """Narrow, product-owned supervision contract.

    The product owns every value. Control Center consumes it; it never defines
    competing product defaults. ``ports`` is the full set of ports the product
    binds so cross-product collisions can be detected even for products that
    own more than one service (e.g. SCS core API + AI API + web).
    """

    product_id: str
    display_name: str
    ports: tuple[int, ...] = ()
    api_port: int | None = None
    web_port: int | None = None
    api_launch: tuple[str, ...] | None = None
    ui_launch: tuple[str, ...] | None = None
    working_dir: Path | None = None
    health_url: str | None = None
    open_url: str | None = None
    status_url: str | None = None
    setup_url: str | None = None
    graceful_stop: str = "request_shutdown"
    manifest_source: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "display_name": self.display_name,
            "ports": list(self.ports),
            "api_port": self.api_port,
            "web_port": self.web_port,
            "api_launch": list(self.api_launch) if self.api_launch else None,
            "ui_launch": list(self.ui_launch) if self.ui_launch else None,
            "working_dir": str(self.working_dir) if self.working_dir else None,
            "health_url": self.health_url,
            "open_url": self.open_url,
            "status_url": self.status_url,
            "setup_url": self.setup_url,
            "graceful_stop": self.graceful_stop,
            "manifest_source": self.manifest_source,
        }


class ProductSupervisionManifestStore:
    """Owned collection of product manifests consumed by the Control Center."""

    def __init__(self, manifests: tuple[ProductSupervisionManifest, ...]) -> None:
        self._manifests: dict[str, ProductSupervisionManifest] = {}
        for manifest in manifests:
            if not isinstance(manifest, ProductSupervisionManifest):
                raise TypeError("manifests must be ProductSupervisionManifest")
            if manifest.product_id in self._manifests:
                raise ValueError(f"duplicate product manifest: {manifest.product_id}")
            self._manifests[manifest.product_id] = manifest

    def all(self) -> tuple[ProductSupervisionManifest, ...]:
        return tuple(self._manifests.values())

    def get(self, product_id: str) -> ProductSupervisionManifest | None:
        return self._manifests.get(product_id)

    def snapshot(self) -> dict[str, Any]:
        return {
            "manifests": [
                manifest.to_dict() for manifest in self.all()
            ],
        }


def build_compatibility_manifests(
    settings: Any,
    repository: Path,
    python_executable: str,
) -> tuple[ProductSupervisionManifest, ...]:
    """Bounded compatibility adapter around each product's OWNED config.

    Manifest provenance is stamped explicitly on every manifest:

    - CODER: consumed from the product-owned launch contract
      ``defend_coder.launch.build_launch_manifest()`` (8301/3301/8403).
    - MARKETS: consumed from the product-owned launch contract
      ``defend_markets.launch.build_manifest()`` (8500/3500).
    - SCS: consumed from the product-owned supervision contract
      ``scs_data.supervision.supervision_manifest()`` when an ApplicationContext
      can be built without side effects; else COMPATIBILITY_LEGACY.
    - DEFEND AI: no canonical application supervision manifest exists
      (``defend_ai.launch`` holds GPU LaunchSpecs, not an application process
      manifest) -> COMPATIBILITY_LEGACY / PRODUCT_CONTRACT_REQUIRED.
    - DEFEND Sports: LEGACY transition surface only (never masquerades as
      DEFENDmarkets).
    """
    repository = Path(repository).resolve()
    py = str(python_executable)

    def port_attr(name: str) -> int | None:
        value = getattr(settings, name, None)
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else None

    def text_attr(name: str) -> str | None:
        value = getattr(settings, name, None)
        return str(value) if isinstance(value, str) and value else None

    defend_api_port = port_attr("defend_ai_api_port") or 8401
    defend_health = f"http://127.0.0.1:{defend_api_port}/health"

    sports_api = port_attr("sports_api_port") or 8200
    sports_web = port_attr("sports_web_port") or 3200
    sports_origin = text_attr("sports_public_origin") or "https://defendsports.defend-network.org"

    coder_manifest = _load_coder_launch_manifest()
    if coder_manifest is not None:
        coder_api = int(coder_manifest.api_port)
        coder_web = int(coder_manifest.ui_port)
        coder_launch = tuple(coder_manifest.api_command)
        coder_ui_launch = tuple(coder_manifest.ui_command)
        coder_health = str(coder_manifest.health_url)
        coder_origin = str(coder_manifest.open_url)
        coder_source = "product:defend_coder.launch.build_launch_manifest"
    else:
        coder_api = port_attr("coder_api_port") or 8301
        coder_web = port_attr("coder_web_port") or 3301
        coder_launch = (py, "-m", "tools.defend_coder_server")
        coder_ui_launch = ("node", ".next/standalone/server.js")
        coder_health = f"http://127.0.0.1:{coder_api}/health"
        coder_origin = text_attr("coder_public_origin") or "https://defendcoder.defend-network.org"
        coder_source = "COMPATIBILITY_LEGACY"
    coder_workspace = getattr(settings, "coder_workspace_root", None)
    coder_workspace = (
        Path(coder_workspace).resolve()
        if coder_workspace is not None
        else repository / "defendcoder-ui"
    )

    markets_manifest = _load_markets_launch_manifest(repository)
    if markets_manifest is not None:
        markets_api = int(markets_manifest.api_port)
        markets_web = int(markets_manifest.ui_port)
        markets_launch = tuple(markets_manifest.api_argv(py))
        markets_ui_launch = tuple(markets_manifest.ui_argv())
        markets_health = str(markets_manifest.api_health_url)
        markets_origin = str(markets_manifest.open_url)
        markets_source = "product:defend_markets.launch.build_manifest"
    else:
        markets_api = None
        markets_web = None
        markets_launch = None
        markets_ui_launch = None
        markets_health = None
        markets_origin = None
        markets_source = "COMPATIBILITY_LEGACY"

    scs_manifest = _load_scs_supervision_manifest()
    if scs_manifest is not None:
        scs_api = int(scs_manifest["api_port"])
        scs_web = int(scs_manifest["web_port"])
        scs_health = str(scs_manifest["health_url"])
        scs_origin = str(scs_manifest["open_url"])
        scs_setup = scs_manifest.get("setup_url")
        scs_source = "product:scs_data.supervision.supervision_manifest"
    else:
        scs_api = port_attr("scs_ai_api_port") or port_attr("scs_api_port") or 8300
        scs_web = port_attr("scs_web_port") or 3100
        scs_health = f"http://127.0.0.1:{port_attr('scs_api_port') or 8100}/health"
        scs_origin = text_attr("scs_ai_public_origin") or text_attr("scs_public_origin") or "https://ai.sunshineclimatesolutions.com"
        scs_setup = None
        scs_source = "COMPATIBILITY_LEGACY"

    manifests = [
        ProductSupervisionManifest(
            product_id="defend",
            display_name="DEFEND AI",
            ports=(defend_api_port,),
            api_port=defend_api_port,
            web_port=None,
            api_launch=None,  # orchestrated via controller (vast/ollama)
            health_url=defend_health,
            open_url=text_attr("public_web_origin") or "https://ai.defend-network.org",
            graceful_stop="request_shutdown",
            manifest_source="COMPATIBILITY_LEGACY (PRODUCT_CONTRACT_REQUIRED: no canonical app supervision manifest; defend_ai.launch is GPU LaunchSpec)",
        ),
        ProductSupervisionManifest(
            product_id="coder",
            display_name="DEFENDcoder",
            ports=(coder_api, coder_web),
            api_port=coder_api,
            web_port=coder_web,
            api_launch=coder_launch,
            ui_launch=coder_ui_launch,
            working_dir=repository / "defendcoder-ui",
            health_url=coder_health,
            open_url=coder_origin,
            graceful_stop="request_shutdown",
            manifest_source=coder_source,
        ),
        ProductSupervisionManifest(
            product_id="markets",
            display_name="DEFENDmarkets",
            ports=tuple(p for p in (markets_api, markets_web) if p is not None),
            api_port=markets_api,
            web_port=markets_web,
            api_launch=markets_launch,
            ui_launch=markets_ui_launch,
            working_dir=repository,
            health_url=markets_health,
            open_url=markets_origin,
            graceful_stop="request_shutdown",
            manifest_source=markets_source,
        ),
        ProductSupervisionManifest(
            product_id="scs",
            display_name="SCS AI",
            ports=(scs_api, scs_web),
            api_port=scs_api,
            web_port=scs_web,
            api_launch=(py, "-m", "uvicorn", "scs_ai.runtime:app", "--host", "127.0.0.1", "--port", str(scs_api)),
            working_dir=repository,
            health_url=scs_health,
            open_url=scs_origin,
            setup_url=scs_setup,
            graceful_stop="request_shutdown",
            manifest_source=scs_source,
        ),
        ProductSupervisionManifest(
            product_id="sports",
            display_name="DEFEND Sports",
            ports=(sports_api, sports_web),
            api_port=sports_api,
            web_port=sports_web,
            api_launch=(py, "-m", "tools.defend_sports_server"),
            working_dir=repository,
            health_url=f"http://127.0.0.1:{sports_api}/health",
            open_url=sports_origin,
            graceful_stop="request_shutdown",
            manifest_source="COMPATIBILITY_LEGACY (transition/data-inspection surface; never masquerades as DEFENDmarkets)",
        ),
    ]
    return tuple(manifests)


def _load_coder_launch_manifest() -> object | None:
    """Best-effort load of the product-owned Coder launch contract.

    Returns the ``defend_coder.launch.LaunchManifest`` when it can be imported
    without side effects, else None so callers fall back to COMPATIBILITY_LEGACY.
    """
    try:
        from defend_coder.launch import build_launch_manifest

        return build_launch_manifest()
    except Exception:
        return None


def _load_markets_launch_manifest(repository: Path) -> object | None:
    """Best-effort load of the product-owned Markets launch contract."""
    try:
        from defend_markets.launch import build_manifest

        return build_manifest(repository)
    except Exception:
        return None


def _load_scs_supervision_manifest() -> dict[str, Any] | None:
    """Best-effort load of the product-owned SCS supervision manifest.

    Reads the SCS-owned environment configuration (SCS_API_PORT / SCS_WEB_PORT
    / SCS_PUBLIC_ORIGIN / SCS_DATA_ROOT) into an ``ApplicationContext`` and
    delegates to ``scs_data.supervision.supervision_manifest``. It does NOT
    import ``scs_api.runtime`` (which starts databases / mailer at import) and
    therefore never causes product side effects. Fails closed (None) otherwise.
    """
    import os

    try:
        from scs_data.supervision import supervision_manifest
        from shared_platform.application import ApplicationContext

        context = ApplicationContext(
            application_id="scs",
            data_root=Path(os.environ.get("SCS_DATA_ROOT", r"C:\SCS_DATA")),
            environment_prefix="SCS",
            secret_namespace="SCS",
            session_cookie="scs_employee_session",
            public_origin=os.environ.get(
                "SCS_PUBLIC_ORIGIN", "https://ai.sunshineclimatesolutions.com"
            ),
            api_port=int(os.environ.get("SCS_API_PORT", "8100")),
            web_port=int(os.environ.get("SCS_WEB_PORT", "3100")),
        )
        return supervision_manifest(context)
    except Exception:
        return None


def _component_for(manifest: ProductSupervisionManifest, port: int) -> str:
    if port == manifest.api_port:
        return "api"
    if port == manifest.web_port:
        return "web"
    return "service"


def validate_product_manifests(
    manifests: tuple[ProductSupervisionManifest, ...],
) -> dict[str, Any]:
    """Cross-product port collision validation (Section 26).

    Input: product-owned manifests. Output: PASS / COLLISION / UNKNOWN with
    per-collision detail identifying both products, components and the shared
    port. This function NEVER modifies ports or any other value.
    """
    if not manifests:
        return {
            "result": "UNKNOWN",
            "collisions": [],
            "unknown": [{"product_id": None, "reason": "no manifests supplied"}],
        }
    by_port: dict[int, list[tuple[str, str]]] = {}
    unknown: list[dict[str, str]] = []
    for manifest in manifests:
        if not manifest.ports:
            unknown.append(
                {"product_id": manifest.product_id, "reason": "no ports declared"}
            )
            continue
        for port in manifest.ports:
            by_port.setdefault(port, []).append(
                (manifest.product_id, _component_for(manifest, port))
            )

    collisions: list[dict[str, Any]] = []
    for port in sorted(by_port):
        owners = by_port[port]
        if len(owners) < 2:
            continue
        for (product_a, component_a), (product_b, component_b) in combinations(owners, 2):
            collisions.append(
                {
                    "port": port,
                    "product_a": product_a,
                    "component_a": component_a,
                    "product_b": product_b,
                    "component_b": component_b,
                }
            )
    result = "COLLISION" if collisions else ("UNKNOWN" if unknown else "PASS")
    return {"result": result, "collisions": collisions, "unknown": unknown}


def observe_product_state(
    *,
    process_present: bool = False,
    process_owned: bool = False,
    process_running: bool = False,
    health_ok: bool | None = None,
    reported: str | None = None,
) -> ProductSupervisionState:
    """Map observed signals to the canonical status vocabulary.

    RUNNING is only reported when there is a process identity AND product
    health confirms readiness (or the product itself reports running). A bare
    open port is never sufficient.
    """
    if not process_present:
        if reported is not None and reported != "":
            return ProductSupervisionState.EXTERNAL
        return ProductSupervisionState.STOPPED
    if not process_owned:
        return ProductSupervisionState.EXTERNAL
    if not process_running:
        return ProductSupervisionState.FAILED
    reported_norm = (reported or "").strip().casefold()
    if reported_norm in ("running", "ready"):
        return ProductSupervisionState.RUNNING
    if health_ok is True:
        return ProductSupervisionState.RUNNING
    if health_ok is False:
        return ProductSupervisionState.DEGRADED
    if reported_norm in ("starting", "degraded"):
        return ProductSupervisionState.DEGRADED
    return ProductSupervisionState.STARTING
