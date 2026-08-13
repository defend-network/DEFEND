# Admin Permanent RAG Ingestion Design

## Objective

Make DEFEND's existing Knowledge / RAG admin panel a working, authenticated operator surface for permanently indexing PDF and DOCX documents. The first corpus is the 13 PDF/DOCX files under `C:\Users\thoma\Downloads\RAG`. CSV, JSON, ZIP, and other formats remain out of scope until they receive dataset-aware ingestion designs.

## User experience

The Knowledge / RAG panel will let an authenticated administrator select PDF and DOCX files, start a batch, monitor per-document progress, and refresh the permanent corpus. The browser will upload files to DEFEND; it will not grant the server arbitrary access to a local folder path.

Each file will show one of these states: queued, extracting, embedding, indexed, skipped, or failed. A batch summary will report indexed, skipped, and failed counts. A failure in one document will not prevent later documents from running.

The existing Documents panel will list real permanent-index metadata rather than returning an empty placeholder. It will show at least title, document ID, content hash, chunk count, embedding model, ingestion time, and tags where available.

## API and authorization

All new routes require the existing admin authentication dependency. The API will provide:

- a multipart batch-ingestion endpoint accepting PDF/DOCX files only;
- a job-status endpoint for bounded polling and per-file progress;
- a permanent-document listing endpoint backed by the RAG index.

Uploads are limited by the existing 25 MB per-file limit. Batch size is limited to 20 files. Filenames are normalized to basename-only values. Files are validated by extension and readable content, and the existing AI-ingestion exclusion policy is enforced before storage or indexing.

The API copies accepted originals and metadata into the configured DEFEND data root. It never stores operator documents in Git or trusts a browser-supplied filesystem path.

## Identity, deduplication, and updates

Each permanent document receives a stable ID derived from its SHA-256 content hash. Re-uploading identical content returns `skipped` without recomputing embeddings. A changed file receives a new content-derived ID; it does not silently overwrite a different document merely because the filename matches.

Ingestion remains idempotent at the document-ID boundary. Index replacement occurs only after extraction and embedding succeed, preserving any previously valid index entries if processing fails.

## Processing architecture

The API creates an in-memory bounded job record and processes accepted files sequentially in a background task. Sequential execution prevents a 13-document batch from overwhelming the embedding backend. Job records contain safe metadata and errors only, are bounded in count, and may be lost on API restart; indexed documents and stored originals remain durable.

The permanent ingestion service reuses DEFEND's existing document storage, document reader, chunking rules, `RagIngestTool`, and permanent LanceDB table. Any necessary wrapper will keep HTTP/job concerns outside the tool itself.

The current embedding backend is checked before the batch begins. If it is unavailable, the job fails clearly with remediation instead of accepting work that cannot complete. The H200/vLLM inference backend and the embedding backend are treated as separate dependencies.

## Listing and retrieval

Permanent document listing is derived from permanent LanceDB rows and grouped by document ID. The endpoint must tolerate an empty or not-yet-created table. It must not expose stored absolute paths or secrets.

No change is made to public-chat authorization: permanent `rag.ingest` remains admin-only. Existing `rag.query` retrieval continues to search the permanent index according to current policy.

## Error handling and safety

- Unsupported formats are rejected before persistence.
- Oversized files are rejected before persistence.
- Developer-only/excluded documents are rejected by the existing ingestion policy.
- Extraction, embedding, or indexing errors are recorded per file with safe messages.
- Partial batches continue after individual failures.
- Duplicate content is reported as skipped.
- No endpoint deletes permanent documents in this version.
- No ZIP extraction, CSV/JSON ingestion, recursive folder access, or remote URL ingestion is added.

## Testing and verification

Backend tests will cover admin authentication, format and size validation, exclusion-policy enforcement, stable IDs, duplicate skipping, sequential partial-failure behavior, safe job status, and real permanent-document aggregation.

Frontend tests will cover file filtering, batch submission, progress rendering, partial failures, completion summaries, and document refresh. Existing backend and frontend suites must remain green, and the Next.js production build and Control Center preflight must pass.

The initial 13-document ingestion is an operator action after deployment. It will run through the completed admin panel so the same path used in production is exercised. The implementation will not ingest the corpus silently during tests or startup.

## Out of scope

- CSV, JSON, ZIP, spreadsheet, image, and OCR corpus ingestion
- document deletion or corpus rollback UI
- distributed/durable job queues
- multi-tenant corpus partitioning
- changes to model training or fine-tuning
- automatic ingestion from arbitrary local folders
