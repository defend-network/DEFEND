from __future__ import annotations

from pathlib import Path
import asyncio

import pytest

from defend_data.admin_rag import (
    MAX_PERMANENT_FILE_BYTES,
    PermanentRagFile,
    PermanentRagService,
    PermanentRagValidationError,
)


def test_pdf_identity_is_content_stable_and_name_is_safe(tmp_path):
    service = PermanentRagService(tmp_path)
    item = PermanentRagFile(r"C:\private\report.pdf", b"%PDF-1.7\nbody", "application/pdf")

    first = service.validate_file(item)

    assert first.name == "report.pdf"
    assert first.document_id.startswith("doc_perm_")
    assert service.validate_file(item).document_id == first.document_id
    assert not list(tmp_path.rglob("original.bin"))


def test_service_construction_does_not_create_data_directories(tmp_path):
    root = tmp_path / "not-created"
    PermanentRagService(root)
    assert not root.exists()


def test_docx_is_accepted(tmp_path):
    result = PermanentRagService(tmp_path).validate_file(
        PermanentRagFile("brief.docx", b"PK\x03\x04document", None)
    )
    assert result.media_type == "docx"


@pytest.mark.parametrize("name", ["data.csv", "dump.json", "bundle.zip", "fake.pdf.exe"])
def test_unsupported_permanent_formats_are_rejected(tmp_path, name):
    with pytest.raises(PermanentRagValidationError, match="PDF and DOCX"):
        PermanentRagService(tmp_path).validate_file(
            PermanentRagFile(name, b"content", "application/octet-stream")
        )


def test_oversized_file_is_rejected_before_persistence(tmp_path):
    service = PermanentRagService(tmp_path)
    with pytest.raises(PermanentRagValidationError, match="25 MB"):
        service.validate_file(
            PermanentRagFile("big.pdf", b"x" * (MAX_PERMANENT_FILE_BYTES + 1), "application/pdf")
        )
    assert not list(tmp_path.rglob("original.bin"))


def test_developer_only_document_is_rejected(tmp_path):
    with pytest.raises(PermanentRagValidationError, match="excluded"):
        PermanentRagService(tmp_path).validate_file(
            PermanentRagFile("notes.pdf", b"<!-- DEFEND-AI-INGEST: EXCLUDE -->", "application/pdf")
        )


def test_empty_file_is_rejected(tmp_path):
    with pytest.raises(PermanentRagValidationError, match="empty"):
        PermanentRagService(tmp_path).validate_file(
            PermanentRagFile("empty.pdf", b"", "application/pdf")
        )


def test_ingestion_rejects_unavailable_embedding_provider_before_persistence(tmp_path):
    async def unavailable():
        return False

    service = PermanentRagService(
        tmp_path,
        readiness_check=unavailable,
        provider_label="vLLM - Qwen/Qwen3-Embedding-0.6B",
    )

    async def exercise():
        with pytest.raises(PermanentRagValidationError, match="unavailable"):
            await service.create_job(
                [PermanentRagFile("one.pdf", b"%PDF", "application/pdf")],
                requested_by="owner",
            )

    asyncio.run(exercise())
    assert not list(tmp_path.rglob("original.bin"))


def test_embedding_status_is_safe_and_actionable(tmp_path):
    async def ready():
        return True

    service = PermanentRagService(
        tmp_path,
        readiness_check=ready,
        provider_label="vLLM - Qwen/Qwen3-Embedding-0.6B",
    )

    assert asyncio.run(service.embedding_status()) == {
        "ready": True,
        "provider": "vLLM - Qwen/Qwen3-Embedding-0.6B",
    }


def test_job_runs_sequentially_continues_after_failure_and_skips_indexed_duplicate(tmp_path):
    active = 0
    max_active = 0
    calls: list[str] = []

    async def runner(document_id: str, _requested_by: str):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        calls.append(document_id)
        active -= 1
        if document_id == bad_id:
            raise RuntimeError("synthetic extraction failure")
        return {"ok": True, "chunks_added": 2, "chunks_updated": 0}

    one = PermanentRagFile("one.pdf", b"one", "application/pdf")
    bad = PermanentRagFile("bad.docx", b"bad", None)
    two = PermanentRagFile("two.pdf", b"two", "application/pdf")
    bad_id = PermanentRagService(tmp_path).validate_file(bad).document_id
    indexed = {
        "document_id": PermanentRagService(tmp_path).validate_file(one).document_id,
        "content_hash": __import__("hashlib").sha256(b"one").hexdigest(),
    }
    service = PermanentRagService(tmp_path, runner=runner, row_source=lambda: [indexed])

    async def exercise():
        created = await service.create_job([one, bad, two], requested_by="owner")
        return await service.wait(created["job_id"])

    done = asyncio.run(exercise())

    assert [item["status"] for item in done["files"]] == ["skipped", "failed", "indexed"]
    assert done["indexed"] == 1
    assert done["skipped"] == 1
    assert done["failed"] == 1
    assert max_active == 1
    assert len(calls) == 2
    assert "synthetic extraction failure" in done["files"][1]["error"]


def test_list_documents_groups_chunks_and_uses_safe_metadata_title(tmp_path):
    document_id = "doc_perm_example"
    metadata_dir = tmp_path / "documents" / document_id
    metadata_dir.mkdir(parents=True)
    (metadata_dir / "meta.json").write_text('{"title":"Report.pdf"}', encoding="utf-8")
    rows = [
        {"document_id": document_id, "content_hash": "hash-a", "embedding_model": "embed", "ingested_at": "2026-01-01", "tags": "law,primary"},
        {"document_id": document_id, "content_hash": "hash-a", "embedding_model": "embed", "ingested_at": "2026-01-02", "tags": "primary"},
    ]

    documents = PermanentRagService(tmp_path, row_source=lambda: rows).list_documents()

    assert documents == [{
        "document_id": document_id,
        "title": "Report.pdf",
        "content_hash": "hash-a",
        "chunk_count": 2,
        "embedding_model": "embed",
        "ingested_at": "2026-01-02",
        "tags": ["law", "primary"],
    }]
