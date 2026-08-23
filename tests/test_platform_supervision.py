"""Control Center supervision contract tests.

Verifies the neutral ProductSupervisionManifest, the bounded compatibility
adapter (values sourced from product-owned env config, never new policy), the
fail-closed collision validator (PASS / COLLISION / UNKNOWN, no mutation), and
the canonical status vocabulary (RUNNING is never inferred from port-open
alone).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from defend_control.supervision import (
    ProductSupervisionManifest,
    ProductSupervisionManifestStore,
    ProductSupervisionState,
    build_compatibility_manifests,
    observe_product_state,
    validate_product_manifests,
)


def _manifest(product_id="a", *, ports=(8000,), api_port=8000, web_port=None):
    return ProductSupervisionManifest(
        product_id=product_id,
        display_name=product_id.upper(),
        ports=ports,
        api_port=api_port,
        web_port=web_port,
        manifest_source="test",
    )


# ------------------------------------------------------------- manifest model


def test_manifest_is_product_owned_contract():
    manifest = _manifest()
    assert manifest.product_id == "a"
    assert manifest.display_name == "A"
    assert manifest.graceful_stop == "request_shutdown"
    serialized = manifest.to_dict()
    assert serialized["product_id"] == "a"
    assert serialized["ports"] == [8000]
    assert serialized["manifest_source"] == "test"


def test_manifest_store_rejects_duplicates_and_non_manifests():
    store = ProductSupervisionManifestStore((_manifest("a"), _manifest("b")))
    assert store.get("a") is not None
    assert store.get("nope") is None
    assert len(store.all()) == 2
    with pytest.raises(ValueError, match="duplicate"):
        ProductSupervisionManifestStore((_manifest("a"), _manifest("a")))
    with pytest.raises(TypeError):
        ProductSupervisionManifestStore(("not-a-manifest",))  # type: ignore[arg-type]


# ------------------------------------------------------- compatibility adapter


class _SettingsStub:
    def __init__(self):
        self.defend_ai_api_port = 8401
        self.sports_api_port = 8200
        self.sports_web_port = 3200
        self.sports_public_origin = "https://defendsports.defend-network.org"
        self.coder_api_port = 8301
        self.coder_web_port = 3301
        self.coder_public_origin = "https://defendcoder.defend-network.org"
        self.coder_workspace_root = Path(r"C:\DEFEND_CODER_DATA")
        self.scs_api_port = 8100
        self.scs_ai_api_port = 8300
        self.scs_web_port = 3100
        self.scs_ai_public_origin = "https://ai.sunshineclimatesolutions.com"


def test_compatibility_manifests_source_product_owned_config():
    settings = _SettingsStub()
    manifests = build_compatibility_manifests(
        settings, Path(r"C:\DEFEND"), "python.exe"
    )
    by_id = {m.product_id: m for m in manifests}
    assert set(by_id) == {"defend", "coder", "markets", "sports", "scs"}
    coder = by_id["coder"]
    assert coder.api_port == 8301
    assert coder.web_port == 3301
    assert coder.open_url.startswith("http://127.0.0.1")
    markets = by_id["markets"]
    assert markets.api_port == 8500
    assert markets.web_port == 3500
    scs = by_id["scs"]
    assert scs.api_port == 8100
    assert scs.web_port == 3100


def test_markets_manifest_consumes_product_owned_launch_contract():
    settings = _SettingsStub()
    manifests = build_compatibility_manifests(
        settings, Path(r"C:\DEFEND"), "python.exe"
    )
    markets = next(m for m in manifests if m.product_id == "markets")
    assert markets.manifest_source == "product:defend_markets.launch.build_manifest"
    assert markets.api_port == 8500
    assert markets.web_port == 3500
    assert markets.health_url == "http://127.0.0.1:8500/health"


def test_coder_manifest_consumes_product_owned_launch_contract():
    settings = _SettingsStub()
    manifests = build_compatibility_manifests(
        settings, Path(r"C:\DEFEND"), "python.exe"
    )
    coder = next(m for m in manifests if m.product_id == "coder")
    assert (
        coder.manifest_source
        == "product:defend_coder.launch.build_launch_manifest"
    )
    from defend_coder.launch import build_launch_manifest

    product = build_launch_manifest()
    assert coder.api_port == product.api_port == 8301
    assert coder.web_port == product.ui_port == 3301
    assert coder.health_url == product.health_url
    assert coder.api_launch == tuple(product.api_command)


def test_ai_manifest_requires_product_contract_scs_and_markets_are_product_owned():
    settings = _SettingsStub()
    manifests = build_compatibility_manifests(
        settings, Path(r"C:\DEFEND"), "python.exe"
    )
    by_id = {m.product_id: m for m in manifests}
    assert by_id["defend"].manifest_source.startswith("COMPATIBILITY_LEGACY")
    assert "PRODUCT_CONTRACT_REQUIRED" in by_id["defend"].manifest_source
    assert by_id["scs"].manifest_source.startswith(
        "product:scs_data.supervision.supervision_manifest"
    )
    assert by_id["markets"].manifest_source.startswith(
        "product:defend_markets.launch.build_manifest"
    )
    assert by_id["sports"].manifest_source.startswith("COMPATIBILITY_LEGACY")


def test_compatibility_manifests_are_collision_free_by_default():
    settings = _SettingsStub()
    manifests = build_compatibility_manifests(
        settings, Path(r"C:\DEFEND"), "python.exe"
    )
    report = validate_product_manifests(manifests)
    assert report["result"] == "PASS"
    assert report["collisions"] == []


# ------------------------------------------------------------ collision check


def test_collision_detection_identifies_both_products_and_components():
    manifests = (
        _manifest("a", ports=(8000, 8001), api_port=8000, web_port=8001),
        _manifest("b", ports=(8001, 8002), api_port=8001, web_port=8002),
    )
    report = validate_product_manifests(manifests)
    assert report["result"] == "COLLISION"
    assert any(
        collision["port"] == 8001
        and collision["product_a"] == "a"
        and collision["component_a"] == "web"
        and collision["product_b"] == "b"
        and collision["component_b"] == "api"
        for collision in report["collisions"]
    )


def test_collision_validator_never_modifies_inputs():
    manifests = (
        _manifest("a", ports=(8000,), api_port=8000),
        _manifest("b", ports=(8000,), api_port=8000),
    )
    before = [m.to_dict() for m in manifests]
    report = validate_product_manifests(manifests)
    assert report["result"] == "COLLISION"
    after = [m.to_dict() for m in manifests]
    assert before == after


def test_no_manifests_is_unknown():
    report = validate_product_manifests(())
    assert report["result"] == "UNKNOWN"
    assert report["unknown"]


def test_missing_ports_is_unknown_not_pass():
    manifests = (
        ProductSupervisionManifest(
            product_id="a", display_name="A", manifest_source="test"
        ),
    )
    report = validate_product_manifests(manifests)
    assert report["result"] == "UNKNOWN"


def test_distinct_ports_pass():
    manifests = (
        _manifest("a", ports=(8000,), api_port=8000),
        _manifest("b", ports=(8001,), api_port=8001),
    )
    report = validate_product_manifests(manifests)
    assert report["result"] == "PASS"
    assert report["collisions"] == []


# ------------------------------------------------------------- status truth


def test_running_requires_process_identity_and_health_or_report():
    # A bare "port open" is never enough - there must be a process identity.
    assert (
        observe_product_state(
            process_present=False, health_ok=True
        )
        is ProductSupervisionState.STOPPED
    )
    assert (
        observe_product_state(
            process_present=True,
            process_owned=True,
            process_running=True,
            health_ok=True,
        )
        is ProductSupervisionState.RUNNING
    )
    assert (
        observe_product_state(
            process_present=True,
            process_owned=True,
            process_running=True,
            reported="running",
        )
        is ProductSupervisionState.RUNNING
    )


def test_externally_running_product_is_external_not_owned():
    assert (
        observe_product_state(
            process_present=False, reported="running"
        )
        is ProductSupervisionState.EXTERNAL
    )
    assert (
        observe_product_state(
            process_present=True,
            process_owned=False,
            process_running=True,
            health_ok=True,
        )
        is ProductSupervisionState.EXTERNAL
    )


def test_failed_when_owned_process_exited():
    assert (
        observe_product_state(
            process_present=True,
            process_owned=True,
            process_running=False,
        )
        is ProductSupervisionState.FAILED
    )


def test_owned_process_up_without_health_is_starting():
    assert (
        observe_product_state(
            process_present=True,
            process_owned=True,
            process_running=True,
            health_ok=None,
        )
        is ProductSupervisionState.STARTING
    )


def test_health_failure_is_degraded_not_running():
    assert (
        observe_product_state(
            process_present=True,
            process_owned=True,
            process_running=True,
            health_ok=False,
        )
        is ProductSupervisionState.DEGRADED
    )


# ---------------------------------------------------------- provider boundary


def test_neutral_platform_modules_import_no_provider_clients():
    """Section 8A: NEUTRAL_PLATFORM_MODULES_IMPORT_PROVIDER_CLIENTS=NO.

    The neutral platform/supervision layer imports no provider CLIENTS (Vast /
    model-provider HTTP transports). It MAY import product-owned manifest
    contracts (defend_markets.launch, scs_data.supervision, defend_coder.launch)
    because supervision CONSUMES those contracts - that is its job, not a
    provider call.
    """
    import defend_control.platform as platform_module
    import defend_control.platform_audit as audit_module
    import defend_control.platform_credentials as credentials_module
    import defend_control.supervision as supervision_module

    for module in (
        platform_module,
        audit_module,
        credentials_module,
        supervision_module,
    ):
        source = getattr(module, "__file__", None)
        assert source, module.__name__
        import_lines = "\n".join(
            line
            for line in open(source, encoding="utf-8").read().splitlines()
            if line.lstrip().startswith(("import ", "from "))
        )
        for forbidden in (
            "coder_vast_backend",
            "remote_vllm",
            "openai",
            "huggingface",
            "defend_control.vast",
            "shared_platform.vast",
            "VastClient",
        ):
            assert forbidden not in import_lines, (module.__name__, forbidden)


def test_control_center_coder_provider_path_is_removed():
    """P0.2 / Section 6: Coder R3 removed Control Center provider construction.

    ``_build_coder_plane`` returns None and must NOT construct CoderControlPlane
    / VastCoderBackend / CoderRemoteVllmBootstrap / SshTunnel / VastClient.
    The active coder runtime now lives under ``defend_coder.runtime``.
    """
    import tools.defend_control_center as tools_module

    source = open(tools_module.__file__, encoding="utf-8").read()
    assert "_build_coder_plane" in source
    assert "return None" in source
    for forbidden_construction in (
        "CoderControlPlane(",
        "CoderRemoteVllmBootstrap(",
        "VastCoderBackend(",
        "SshTunnel(",
        "VastClient(",
    ):
        assert forbidden_construction not in source, forbidden_construction


def test_coder_runtime_lives_under_product():
    """P0.2 / Section 6: the active coder runtime is product-owned."""
    import defend_coder.runtime  # noqa: F401

    from defend_coder.runtime.control_plane import CoderControlPlane  # noqa: F401
    from shared_platform.ssh_tunnel import SshTunnel  # noqa: F401


def test_shared_dpapi_is_single_implementation_identity():
    """Section 4: shared_platform.dpapi is the SAME body as secure_store.

    The canonical physical DPAPI implementation is shared_platform.secure_store;
    shared_platform.dpapi and defend_control.secrets are compatibility shims.
    """
    from shared_platform.dpapi import DpapiSecretStore as Shimmable
    from shared_platform.secure_store import (
        DpapiSecretStore,
        SecretBackend,
        UnsupportedPlatformError,
        WindowsDpapiBackend,
        restrict_to_current_user,
    )
    from defend_control.secrets import DpapiSecretStore as Legacy

    assert Shimmable is DpapiSecretStore
    assert Legacy is DpapiSecretStore
    assert SecretBackend is not None
    assert UnsupportedPlatformError is not None
    assert WindowsDpapiBackend is not None
    assert callable(restrict_to_current_user)


def test_control_center_cannot_destroy_train_or_mutate_product_policy():
    import defend_control.platform as platform_module
    import defend_control.platform_audit as audit_module
    import defend_control.platform_credentials as credentials_module
    import defend_control.supervision as supervision_module

    for module in (
        platform_module,
        audit_module,
        credentials_module,
        supervision_module,
    ):
        text = open(getattr(module, "__file__", ""), encoding="utf-8").read()
        for forbidden_surface in (
            "def stop_and_destroy",
            "def train(",
            "def mutate_risk",
            "def set_engineering_policy",
            "def set_reasoning_policy",
        ):
            assert forbidden_surface not in text, (module.__name__, forbidden_surface)
