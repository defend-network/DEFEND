from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.testclient import TestClient

from admin_auth import AdminPrincipal, require_admin
from api_admin_rag_routes import build_admin_rag_router
from defend_data.admin_rag import PermanentRagValidationError


class FakeService:
    def __init__(self):
        self.received = []

    async def create_job(self, files, *, requested_by):
        self.received.append((files, requested_by))
        return {"job_id": "ragjob_1", "status": "queued", "total": len(files), "indexed": 0, "skipped": 0, "failed": 0, "files": []}

    def get_job(self, job_id):
        return {"job_id": job_id, "status": "complete", "total": 1, "indexed": 1, "skipped": 0, "failed": 0, "files": []} if job_id == "ragjob_1" else None

    def list_documents(self):
        return [{"document_id": "doc_perm_1", "title": "Report.pdf", "content_hash": "abc", "chunk_count": 2, "embedding_model": "embed", "ingested_at": "2026-08-13", "tags": []}]

    async def embedding_status(self):
        return {"ready": True, "provider": "vLLM - test-embedding"}


def make_client(*, authenticated: bool):
    service = FakeService()
    app = FastAPI()
    app.include_router(build_admin_rag_router(service))
    if authenticated:
        app.dependency_overrides[require_admin] = lambda: AdminPrincipal("acct_1", "owner", "owner", 9999999999)
    return TestClient(app), service


def test_all_admin_rag_routes_require_auth():
    client, _service = make_client(authenticated=False)
    assert client.get("/api/admin/rag/documents").status_code == 401
    assert client.get("/api/admin/rag/status").status_code == 401
    assert client.get("/api/admin/rag/jobs/ragjob_1").status_code == 401
    assert client.post("/api/admin/rag/ingest", files={"files": ("a.pdf", b"%PDF", "application/pdf")}).status_code == 401


def test_ingest_accepts_admin_multipart_and_returns_202_without_paths():
    client, service = make_client(authenticated=True)
    response = client.post("/api/admin/rag/ingest", files={"files": ("a.pdf", b"%PDF", "application/pdf")})
    assert response.status_code == 202
    assert response.json()["job_id"] == "ragjob_1"
    assert service.received[0][0][0].name == "a.pdf"
    assert service.received[0][1] == "acct_1"
    assert "C:\\" not in response.text


def test_job_and_real_document_listing_contracts():
    client, _service = make_client(authenticated=True)
    assert client.get("/api/admin/rag/jobs/missing").status_code == 404
    assert client.get("/api/admin/rag/jobs/ragjob_1").json()["indexed"] == 1
    response = client.get("/api/admin/rag/documents")
    assert response.status_code == 200
    assert response.json()["documents"][0]["chunk_count"] == 2
    assert client.get("/api/admin/rag/status").json() == {
        "ready": True,
        "provider": "vLLM - test-embedding",
    }


def test_batch_limit_is_rejected_before_service_call():
    client, service = make_client(authenticated=True)
    files = [("files", (f"{index}.pdf", b"%PDF", "application/pdf")) for index in range(21)]
    response = client.post("/api/admin/rag/ingest", files=files)
    assert response.status_code == 400
    assert service.received == []
