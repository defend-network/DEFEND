from dataclasses import dataclass
from pathlib import Path

from fastapi.testclient import TestClient

from scs_api.app import build_scs_app
from scs_data.customers import ScsCustomerStore
from scs_data.identity import ScsIdentityStore
from scs_data.mailer import DeliveryResult
from scs_data.config import ScsPaths
from scs_reports.store import MasterStore, ReportPaths
from shared_platform.application import ApplicationContext

MASTER_SOURCE = Path(r"C:\SCS_DATA\masters")


@dataclass
class NoopMailer:
    def send_invitation(self, email, activation_url):
        return DeliveryResult(True, "sent")


def setup_api(tmp_path):
    context = ApplicationContext("scs", (tmp_path / "SCS_DATA").resolve(), "SCS", "SCS", "scs_employee_session", "https://ai.sunshineclimatesolutions.com", 8100, 3100)
    paths = ScsPaths.from_context(context).ensure()
    identity = ScsIdentityStore(paths.database)
    owner = identity.bootstrap_owner("owner@example.com", "owner", "Owner", "owner-password")
    customers = ScsCustomerStore(identity.conn, identity.audit)
    reports_paths = ReportPaths(Path(tmp_path) / "reports").ensure()
    MasterStore(reports_paths).install_masters(MASTER_SOURCE)
    app = build_scs_app(context, identity, NoopMailer(), customers=customers, reports_paths=reports_paths)
    return TestClient(app, base_url=context.public_origin), identity, owner


def login(client):
    assert client.post("/api/scs/auth/login", json={"identifier": "owner", "password": "owner-password"}).status_code == 200


def test_reports_routes_require_auth(tmp_path):
    client, identity, _owner = setup_api(tmp_path)
    assert client.get("/api/scs/reports/contractors").status_code == 401
    assert client.get("/api/scs/reports/jobs").status_code == 401
    client.close(); identity.close()


def test_contractor_crud_flow(tmp_path):
    client, identity, _owner = setup_api(tmp_path)
    login(client)
    assert client.get("/api/scs/reports/contractors").json()["contractors"] == []
    created = client.post("/api/scs/reports/contractors", json={"name": "Remedy Heating and Cooling", "contact": "Aaron"})
    assert created.status_code == 201
    assert created.json()["company_name"] == "Remedy Heating and Cooling"
    duplicate = client.post("/api/scs/reports/contractors", json={"name": "remedy heating and cooling"})
    assert duplicate.status_code == 400
    listed = client.get("/api/scs/reports/contractors").json()["contractors"]
    assert len(listed) == 1
    client.close(); identity.close()


def test_job_lifecycle_through_compose(tmp_path):
    client, identity, _owner = setup_api(tmp_path)
    login(client)
    created = client.post("/api/scs/reports/jobs", json={
        "project_name": "API Test Warehouse", "project_number": "888888",
        "site_name": "API Site", "site_address": "2 Test Lane",
        "test_date": "2026-08-18", "technician": "Aaron Thomas",
    })
    assert created.status_code == 201
    job_id = created.json()["metadata"]["job_id"]
    assert job_id == "888888"
    equipment = client.post(f"/api/scs/reports/jobs/{job_id}/equipment", json={
        "equipment_id": "RTU-1", "equipment_type": "RTU", "tag": "RTU-1",
        "manufacturer": "Carrier", "model": "50TC-E08",
    })
    assert equipment.status_code == 201
    measurement = client.post(f"/api/scs/reports/jobs/{job_id}/equipment/RTU-1/measurements", json={
        "field": "voltage", "value": 208, "unit": "volts",
    })
    assert measurement.status_code == 201
    device = client.post(f"/api/scs/reports/jobs/{job_id}/air-devices", json={
        "device_id": "OA-1", "function": "Outside Air", "design_cfm": 2400,
        "as_found_cfm": 0, "final_cfm": 0, "status": "FAIL", "notes": "damper closed",
    })
    assert device.status_code == 201
    finding = client.post(f"/api/scs/reports/jobs/{job_id}/findings", json={
        "title": "OA damper closed", "details": "Zero outdoor airflow.",
    })
    assert finding.status_code == 201
    notes = client.post(f"/api/scs/reports/jobs/{job_id}/notes", json={"notes": "API flow notes"})
    assert notes.status_code == 204
    plan = client.get(f"/api/scs/reports/jobs/{job_id}/plan").json()["sections"]
    assert "rtu_nameplate" in plan
    assert "building_pressure" in plan
    assert "fan_test" not in plan
    composed = client.post(f"/api/scs/reports/jobs/{job_id}/compose")
    assert composed.status_code == 200
    result = composed.json()
    assert result["output"].startswith("API Test Warehouse_888888_TAB_2026-08-18")
    assert result["blocked"] is False
    statuses = {check["name"]: check["status"] for check in result["checks"]}
    assert statuses["no_formula_errors"] == "PASS"
    assert statuses["master_unchanged"] == "PASS"
    outputs = client.get(f"/api/scs/reports/jobs/{job_id}/outputs").json()["outputs"]
    assert len(outputs) == 1
    client.close(); identity.close()


def test_compose_requires_existing_job(tmp_path):
    client, identity, _owner = setup_api(tmp_path)
    login(client)
    missing = client.post("/api/scs/reports/jobs/nope/compose")
    assert missing.status_code == 404
    client.close(); identity.close()


def test_put_record_replace_allows_edit_and_delete(tmp_path):
    client, identity, _owner = setup_api(tmp_path)
    login(client)
    client.post("/api/scs/reports/jobs", json={
        "project_name": "Put Job", "project_number": "999111",
        "site_name": "Site", "site_address": "5 Ln",
        "test_date": "2026-08-18", "technician": "T",
    })
    client.post("/api/scs/reports/jobs/999111/equipment", json={
        "equipment_id": "RTU-1", "equipment_type": "RTU", "tag": "RTU-1", "manufacturer": "Carrier",
    })
    client.post("/api/scs/reports/jobs/999111/equipment", json={
        "equipment_id": "RTU-2", "equipment_type": "RTU", "tag": "RTU-2", "manufacturer": "Lennox",
    })
    fetched = client.get("/api/scs/reports/jobs/999111").json()
    fetched["metadata"]["design_engineer"] = "Alan"
    fetched["equipment"] = [e for e in fetched["equipment"] if e["equipment_id"] != "RTU-2"]
    fetched["equipment"][0]["model"] = "50TC-E09"
    replaced = client.put("/api/scs/reports/jobs/999111", json=fetched)
    assert replaced.status_code == 200
    body = replaced.json()
    assert body["metadata"]["design_engineer"] == "Alan"
    assert [e["equipment_id"] for e in body["equipment"]] == ["RTU-1"]
    assert body["equipment"][0]["model"] == "50TC-E09"
    tamper = client.put("/api/scs/reports/jobs/999111", json={**fetched, "job_id": "other"})
    assert tamper.status_code == 400
    bad = client.put("/api/scs/reports/jobs/999111", json={"metadata": {"project_name": ""}})
    assert bad.status_code == 400
    client.close(); identity.close()


def test_output_download_serves_xlsx(tmp_path):
    client, identity, _owner = setup_api(tmp_path)
    login(client)
    client.post("/api/scs/reports/jobs", json={
        "project_name": "Download Job", "project_number": "777001",
        "site_name": "Site", "site_address": "6 Ln",
        "test_date": "2026-08-18", "technician": "T",
    })
    client.post("/api/scs/reports/jobs/777001/equipment", json={
        "equipment_id": "RTU-1", "equipment_type": "RTU", "tag": "RTU-1", "manufacturer": "Carrier",
    })
    composed = client.post("/api/scs/reports/jobs/777001/compose").json()
    filename = composed["output"]
    downloaded = client.get(f"/api/scs/reports/jobs/777001/outputs/{filename}")
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert downloaded.content[:2] == b"PK"
    traversal = client.get("/api/scs/reports/jobs/777001/outputs/..%2F..%2Fsecret.xlsx")
    assert traversal.status_code in (400, 404)
    client.close(); identity.close()


def test_vision_status_reports_not_configured(tmp_path):
    client, identity, _owner = setup_api(tmp_path)
    login(client)
    payload = client.get("/api/scs/reports/vision/status")
    assert payload.status_code == 200
    assert payload.json()["status"] == "NOT_CONFIGURED"
    client.close(); identity.close()


def test_photo_upload_records_manifest(tmp_path):
    client, identity, _owner = setup_api(tmp_path)
    login(client)
    client.post("/api/scs/reports/jobs", json={
        "project_name": "Photo Job", "project_number": "777777",
        "site_name": "Site", "site_address": "4 Ln",
        "test_date": "2026-08-18", "technician": "T",
    })
    upload = client.post(
        "/api/scs/reports/jobs/777777/photos",
        files={"files": ("nameplate.txt", b"photo-bytes", "text/plain")},
    )
    assert upload.status_code == 201
    photos = upload.json()["photos"]
    assert len(photos) == 1
    assert photos[0]["photo_id"] == "PHOTO-001"
    assert len(photos[0]["sha256"]) == 64
    assert not list((Path(tmp_path) / "reports" / "config" / "_uploads").glob("**/*"))
    record = client.get("/api/scs/reports/jobs/777777").json()
    assert record["photos"][0]["original_filename"] == "nameplate.txt"
    client.close(); identity.close()