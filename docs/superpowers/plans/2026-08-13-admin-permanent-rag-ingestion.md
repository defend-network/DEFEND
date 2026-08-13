# Admin Permanent RAG Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add authenticated, permanent PDF/DOCX batch ingestion with progress, duplicate skipping, and real corpus listing to DEFEND's admin panel.

**Architecture:** `defend_data.admin_rag` owns validation, content-stable IDs, bounded sequential jobs, and permanent-index aggregation. A dedicated authenticated FastAPI router exposes ingest/status/list operations. Typed frontend helpers and a focused `KnowledgeRagPanel` upload and poll without changing public-chat permissions.

**Tech Stack:** Python 3.14, FastAPI, asyncio, LanceDB, existing document/RAG tools, Next.js 16, React 18, TypeScript, Vitest.

## Global constraints

- PDF/DOCX only; no CSV, JSON, ZIP, spreadsheet, image, URL, or arbitrary folder access.
- Maximum 20 files per batch and 25,000,000 bytes per file.
- Existing admin authentication on all routes.
- IDs use `doc_perm_<first-24-SHA256>`; identical bytes skip embedding.
- Sequential processing continues after individual failures.
- Originals live under configured DEFEND data, never Git.
- No paths, secrets, raw upstream bodies, deletion, or public policy changes.

## Task 1: Service validation and identity

**Files:** Create `defend_data/admin_rag.py`; create `tests/test_admin_rag.py`.

- [ ] Write failing tests for PDF/DOCX acceptance, basename normalization, unsupported types, size boundary, exclusion policy, and stable IDs.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest -q tests\test_admin_rag.py` and confirm RED.
- [ ] Implement `PermanentRagFile`, `ValidatedPermanentFile`, `PermanentRagValidationError`, `document_id_for`, and `PermanentRagService.validate_file`.
- [ ] Confirm focused tests GREEN and commit `Add permanent RAG file validation`.

```python
def test_pdf_identity_is_content_stable(tmp_path):
    service = PermanentRagService(tmp_path)
    item = PermanentRagFile("report.pdf", b"%PDF-1.7\nbody", "application/pdf")
    first = service.validate_file(item)
    assert first.document_id.startswith("doc_perm_")
    assert service.validate_file(item).document_id == first.document_id
```

## Task 2: Bounded sequential jobs

- [ ] Write failing async tests for ordered execution, state transitions, duplicate skipping, partial failure continuation, safe errors, and 50-completed-job eviction.
- [ ] Implement `create_job`, `get_job`, and `wait`; persist via `save_document`; invoke injected runner or production `RagIngestTool` with `RagIngestInput` and `ToolContext`.
- [ ] Keep embed-first replacement semantics and never destroy valid chunks on failure.
- [ ] Verify service tests and commit `Add sequential permanent RAG jobs`.

## Task 3: Real permanent corpus listing

- [ ] Write failing tests for empty index and multi-chunk grouping.
- [ ] Implement `list_documents() -> list[PermanentDocumentSummary]` using permanent LanceDB rows behind an injectable row source.
- [ ] Return document ID, safe title, hash, chunk count, model, newest ingestion time, and tags—never paths.
- [ ] Verify and commit `List permanent RAG documents`.

## Task 4: Authenticated API

**Files:** Create `api_admin_rag_routes.py`, create `tests/test_admin_rag_api.py`, modify `api_server.py`.

- [ ] Write failing tests proving 401 on all routes without auth; 202 multipart ingest; batch/size/type validation; safe status; 404 unknown job; real listing.
- [ ] Implement `build_admin_rag_router(service)` with `Depends(require_admin)` on POST `/api/admin/rag/ingest`, GET `/api/admin/rag/jobs/{job_id}`, and GET `/api/admin/rag/documents`.
- [ ] Read uploads with a 25,000,001-byte cap, initialize service with `DATA_ROOT`, and remove the placeholder documents route.
- [ ] Verify new API, ingestion-policy, and identity-admin tests; commit `Expose authenticated permanent RAG API`.

```python
def test_admin_rag_routes_require_auth(client):
    assert client.get("/api/admin/rag/documents").status_code == 401
    assert client.get("/api/admin/rag/jobs/job_x").status_code == 401
    assert client.post("/api/admin/rag/ingest", files={"files": ("a.pdf", b"%PDF", "application/pdf")}).status_code == 401
```

## Task 5: Typed frontend API

- [ ] Write failing `defend-ui-v2/lib/api.rag.test.ts` cases for multipart body, Bearer auth, credentials, no forced JSON content type, encoded job ID, timeout, and typed responses.
- [ ] Add `PermanentRagDocument`, `RagJobFile`, `RagJob`, `adminRagIngest`, `adminRagJob`, and typed `adminDocuments`.
- [ ] Verify and commit `Add admin RAG API client`.

## Task 6: Active panel

**Files:** Create `components/admin/KnowledgeRagPanel.tsx` and its test; modify `AdminWorkstation.tsx` and `globals.css`.

- [ ] Write failing UI tests for selection, 21-file rejection, start, two-second polling, accessible progress, partial failure, summary, and corpus refresh.
- [ ] Implement a multiple `.pdf,.docx` input, selected-file preview, disabled running controls, per-file state/errors, totals, and polling to terminal state.
- [ ] Replace the Knowledge placeholder and share refreshed documents with the Documents view.
- [ ] Verify component and AdminWorkstation tests; commit `Activate admin Knowledge RAG panel`.

## Task 7: Verification and handoff

- [ ] Run focused backend tests, full backend suite with workspace-local basetemp, full frontend tests, and production build.
- [ ] Stop active writers normally and require Control Center preflight `READY`.
- [ ] Document the verified operator flow and the initial 13 eligible documents; explicitly exclude 1,355 CSV, 4 JSON, and 1 ZIP files.
- [ ] Run `git diff --check`, confirm no corpus/secrets/data files, and commit `Document permanent RAG administration`.

## Acceptance

The authenticated admin can index the 13 PDF/DOCX files while DEFEND is online, monitor accurate progress, see failures, skip identical content, and view the real permanent corpus. Public permanent ingestion remains denied, and all relevant tests/build/preflight pass.
