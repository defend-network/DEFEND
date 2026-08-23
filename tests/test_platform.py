"""PlatformService tests (PLATFORM tab data layer).

Verifies the neutral owner-facing view: supervision overview, real
infrastructure facts (or UNKNOWN, never fabricated), credential counts, audit
recording of health transitions and collisions, and honest
NOT_CONFIGURED / NOT_IMPLEMENTED for Database/Storage, Membership, Billing and
Networking sections that have no repository truth yet.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from defend_control.platform import PlatformService
from defend_control.platform_audit import (
    EVENT_HEALTH_TRANSITION,
    EVENT_MANIFEST_COLLISION,
    PlatformAuditLog,
)
from defend_control.products import ProductStatus
from defend_control.supervision import (
    ProductSupervisionManifest,
    ProductSupervisionManifestStore,
    build_compatibility_manifests,
)


class _Process:
    def __init__(self, name, pid, owned, running):
        self.name = name
        self.pid = pid
        self.owned = owned
        self.running = running
        self.health_url = f"http://127.0.0.1:{pid}/health"
        self.returncode = None if running else 1


class _FakeSupervisor:
    def __init__(self, processes):
        self._processes = processes

    def snapshot(self):
        return tuple(self._processes)


class _FakeProduct:
    def __init__(self, application_id, display_name, state, last_error=None):
        self.application_id = application_id
        self.display_name = display_name
        self._state = state
        self._last_error = last_error

    def status(self):
        return ProductStatus(
            application_id=self.application_id,
            display_name=self.display_name,
            state=self._state,
            status_text=self._state,
            last_error=self._last_error,
        )


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


def _platform(tmp_path, *, processes=(), product_states=None, manifests=None):
    settings = _SettingsStub()
    if manifests is None:
        manifests = build_compatibility_manifests(
            settings, Path(r"C:\DEFEND"), "python.exe"
        )
    supervision = ProductSupervisionManifestStore(manifests)
    audit = PlatformAuditLog(tmp_path / "audit.json")
    states = product_states or {}
    products = tuple(
        _FakeProduct(
            product_id,
            {"defend": "DEFEND AI", "coder": "DEFENDcoder",
             "sports": "DEFENDmarkets", "scs": "SCS AI"}[product_id],
            states.get(product_id, "stopped"),
        )
        for product_id in ("defend", "coder", "sports", "scs")
    )
    service = PlatformService(
        supervision=supervision,
        audit=audit,
        supervisor=_FakeSupervisor(list(processes)),
        products=products,
        settings=settings,
        repository=Path(r"C:\DEFEND"),
    )
    return service, audit


def test_overview_reports_four_products_and_posture(tmp_path):
    service, _ = _platform(
        tmp_path,
        product_states={"defend": "ready", "coder": "running", "scs": "stopped"},
    )
    overview = service.overview()
    assert len(overview["products"]) == 4
    posture = overview["posture"]
    assert posture["total"] == 4
    assert posture["running"] == 2
    assert posture["stopped"] == 2
    states = {row["product_id"]: row["state"] for row in overview["products"]}
    assert states["defend"] == "RUNNING"
    assert states["coder"] == "RUNNING"
    assert states["sports"] == "STOPPED"


def test_overview_includes_owned_process_identity(tmp_path):
    service, _ = _platform(
        tmp_path,
        processes=[_Process("coder:api", 1001, owned=True, running=True)],
        product_states={"coder": "running"},
    )
    rows = service.overview()["products"]
    coder = next(row for row in rows if row["product_id"] == "coder")
    assert coder["owned_processes"][0]["pid"] == 1001
    assert coder["owned_processes"][0]["owned"] is True


def test_collision_detection_reported(tmp_path):
    settings = _SettingsStub()
    # Force a collision between two manifests on the same port.
    manifests = (
        ProductSupervisionManifest(
            product_id="coder",
            display_name="DEFENDcoder",
            ports=(8301, 3301),
            api_port=8301,
            web_port=3301,
            manifest_source="test",
        ),
        ProductSupervisionManifest(
            product_id="sports",
            display_name="DEFENDmarkets",
            ports=(8301, 3200),
            api_port=8301,
            web_port=3200,
            manifest_source="test",
        ),
    )
    service, audit = _platform(
        tmp_path, manifests=manifests, product_states={}
    )
    report = service.collision_report()
    assert report["result"] == "COLLISION"
    assert any(
        collision["port"] == 8301
        and collision["product_a"] == "coder"
        and collision["product_b"] == "sports"
        for collision in report["collisions"]
    )
    # The collision is recorded to the audit log exactly once.
    recorded = [
        entry
        for entry in audit.snapshot()
        if entry.event_type == EVENT_MANIFEST_COLLISION
    ]
    assert len(recorded) == 1
    service.collision_report()
    recorded = [
        entry
        for entry in audit.snapshot()
        if entry.event_type == EVENT_MANIFEST_COLLISION
    ]
    assert len(recorded) == 1


def test_health_transitions_are_audited(tmp_path):
    service, audit = _platform(tmp_path, product_states={"coder": "stopped"})
    service.overview()  # initial state recorded, no transition
    transitions = [
        entry for entry in audit.snapshot()
        if entry.event_type == EVENT_HEALTH_TRANSITION
    ]
    assert transitions == []
    service._products = tuple(
        _FakeProduct(
            p.application_id,
            p.display_name,
            "running" if p.application_id == "coder" else "stopped",
        )
        for p in service._products
    )
    service.overview()
    transitions = [
        entry for entry in audit.snapshot()
        if entry.event_type == EVENT_HEALTH_TRANSITION
    ]
    assert len(transitions) == 1
    assert transitions[0].product_id == "coder"
    assert "STOPPED -> RUNNING" in transitions[0].detail


def test_infrastructure_reports_real_facts_or_unknown(tmp_path):
    service, _ = _platform(tmp_path)
    infra = service.infrastructure()
    assert infra["host"]
    assert infra["os"]
    assert infra["python"]
    assert infra["node"]
    assert infra["node"] == "UNKNOWN" or infra["node"].startswith("v")
    assert isinstance(infra["processes"], list)
    assert infra["shared_secret_store"] == "DEFEND DPAPI (secrets.dpapi)"


def test_database_storage_is_honest_inventory(tmp_path):
    service, _ = _platform(tmp_path)
    data = service.database_storage()
    assert data["status"] == "INVENTORY"
    assert data["hosted_postgres"] == "NOT_CONFIGURED"
    assert isinstance(data["inventory"], list)


def test_membership_billing_networking_are_honest(tmp_path):
    service, _ = _platform(tmp_path)
    membership = service.membership()
    assert membership["status"] == "NOT_CONFIGURED"
    assert "LEGACY_OWNER_IDENTITY" in membership["identity_authority"]
    assert membership["neutral_platform_identity_authority"] == "NOT_ESTABLISHED"
    assert membership["membership"] == "NOT_IMPLEMENTED"
    billing = service.billing()
    assert billing["status"] == "NOT_IMPLEMENTED"
    assert billing["legacy_coder_billing"].startswith("EXISTS")
    assert billing["neutral_platform_billing_authority"] == "NOT_ESTABLISHED"
    assert billing["consumer_billing"] == "NOT_IMPLEMENTED"
    networking = service.networking()
    assert networking["cloudflare"] == "NOT_CONFIGURED"
    assert networking["product_origins"]
    assert networking["collisions"]["result"] in ("PASS", "UNKNOWN")


def test_audit_view_redacted_and_functional(tmp_path):
    service, audit = _platform(tmp_path)
    audit.record(
        EVENT_HEALTH_TRANSITION, product_id="scs", detail="STOPPED -> RUNNING"
    )
    view = service.audit_view()
    assert view["entries"][0]["event_type"] == EVENT_HEALTH_TRANSITION


def test_snapshot_assembles_all_sections(tmp_path):
    service, _ = _platform(tmp_path)
    snapshot = service.snapshot()
    for section in (
        "overview",
        "credentials",
        "infrastructure",
        "database_storage",
        "membership",
        "billing",
        "networking",
        "audit",
    ):
        assert section in snapshot, section


def test_minimal_service_fails_closed(tmp_path):
    service = PlatformService()
    assert service.overview()["collisions"]["result"] == "UNKNOWN"
    assert service.credentials_view()["status"] == "NOT_CONFIGURED"
    assert service.audit_view()["status"] == "NOT_CONFIGURED"
    assert service.product_status_rows() == ()
