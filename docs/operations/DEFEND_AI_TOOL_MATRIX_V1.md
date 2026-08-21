<!-- DEFEND-AI-INGEST: EXCLUDE -->
# DEFEND AI tool matrix — V1

Operator document, not DEFEND AI training language. Never ingest into RAG,
memory, prompts, or model training data.

Audit date: 2026-08-20. Branch: `defend-ai/operational-readiness-v1`.
Status key: LIVE = exercised live this audit; CODE = verified by code read only;
N/A = not applicable to current deployment state.

## Registered tools (12, via `registry.py`; health payload confirms)

| # | Tool | Description | Risk | Side effect | Live status | Notes / evidence |
|---|---|---|---|---|---|---|
| 1 | documents.search | Search indexed docs | LOW | READ | LIVE | Executed before and after API restart against a controlled fixture; bounded result counts are now included in redacted traces |
| 2 | rag.query | Semantic/lexical/hybrid query of knowledge index | LOW | READ | LIVE | vector + BM25 hits on temp doc (distance 0.43); score method rrf/vector_distance/bm25 |
| 3 | rag.ingest | Permanent ingest (admin-gated) | LOW | WRITE | LIVE | `ALLOWED_TOOLS` policy excludes for public; verified via admin API: 202 → job → indexed (1 chunk), meta + vector round-trip |
| 4 | research.cache_ingest | Cache research findings into index | LOW | WRITE | CODE | present in registry; fires inside research finalize on PDF content |
| 5 | calculator.evaluate | Safe expression evaluation | LOW | READ | LIVE | exact `3*4 → 12`; bad-arg `hello world` → invalid syntax error surfaced honestly |
| 6 | time.now | Current UTC time | LOW | READ | LIVE | Executed in single-tool and two-tool paths; current UTC returned after router repair |
| 7 | web.search | Tavily web search (provider-gated) | LOW | READ | LIVE | executed in research job (statistics_or_data) with Tavily key present in-memory |
| 8 | web.fetch | Fetch URL with SSRF guard + size caps | LOW | READ | LIVE | 3 URLs fetched in research job; 1 failed, 2 rejected as `access_denied_or_thin` (Cloudflare-guarded pages) |
| 9 | documents.fetch | Fetch document by id | LOW | READ | CODE | no corpus to exercise |
| 10 | documents.read | Read/parse stored document (PDF/DOCX) | LOW | READ | CODE | pdfplumber pipeline; pdfplumber 0.11.10 installed |
| 11 | memory.search | Semantic memory recall | LOW | READ | LIVE | direct search hit after commit (namespace-scoped) |
| 12 | memory.propose | Propose durable memory (owner approves) | LOW | WRITE | LIVE | pending proposal created via public chat (SINGLE_TOOL route), visitor-namespaced, provenance-linked; committed + cleaned up |

Memory tools register only when a MemoryManager is present (true in the API
process).

## Policy gates (verified)

- `production_policy.py` `ALLOWED_TOOLS` allowlist applied at compile time for
  public agents (`rag.ingest` denied; research tools permitted).
- `admin_auth.require_admin` on all `/api/admin/*` (401 verified live).
- Ingest validation: extension allowlist (PDF/DOCX), 25 MB cap, ≤20 files per
  batch, ingest-exclusion marker (`DEFEND-AI-INGEST: EXCLUDE`) respected —
  [CODE] + unit tests (`test_admin_rag.py`, `test_rag_ingest_policy.py`).
- Rate limits: admin login gate returns 429 after ~6 rapid failures (verified
  live); per-IP bounded limiter present [CODE].

## Agent-path execution model (verified)

- System-compiled tool calls (research path): execute reliably (web.search +
  parallel web.fetch observed, job-level outcomes).
- Model-initiated tool calls (SingleToolDecision / ProposedPlan): execute only
  after the schema-injection repair; live evidence: calculator 2-step plan
  (step 1 succeeded, step 2 $ref resolution failed with
  `Unsupported expression node: Set`, model recovered manually), time.now
  executed, bad-args honestly declined.
- Silent-DIRECT fallback removed by the repair for hallucinated names; the
  compile step still rejects unknown names with ValueError (regression-tested).

## User-path routing matrix (continuation)

| Case | Expected | Observed | Status |
|---|---|---|---|
| Calculator request | `calculator.evaluate` | `SINGLE_TOOL`, succeeded, 12 | VERIFIED |
| Current-time request | `time.now` | `SINGLE_TOOL`, succeeded | VERIFIED |
| Explicit calculator tool | `calculator.evaluate` | `SINGLE_TOOL`, succeeded, 84 | VERIFIED |
| Web research | research + external tools | `RESEARCH`, `web.fetch` ×2, honest `partial` | PARTIALLY_VERIFIED |
| Memory lookup | `memory.search` | `COMPLEX`, succeeded, empty after cleanup | VERIFIED |
| Document lookup | document retrieval | `COMPLEX`, `documents.search`, empty corpus | VERIFIED_EMPTY |
| Calculation + current time | two tools | `COMPLEX`, `calculator.evaluate` + `time.now`, both succeeded; trace `8501368e-…` | VERIFIED |
| Invalid calculator argument | honest tool error | `invalid_input`, plan failed, no fabricated result | VERIFIED |
| Mixed execution failure | success + failure visible | `time.now` succeeded; calculator failed `invalid_input` | VERIFIED |
| Unknown tool attempt | no unknown invocation | `DIRECT`; no `quantum_compute` call, final arithmetic was inaccurate | PARTIAL |

Tool tests pass only when the user-facing response includes execution evidence;
model-only answers are not counted as tool success.

## RAG restart evidence

- Fixture job `ragjob_c641361d06de44bcaad3` indexed one chunk for
  `doc_perm_f34b3a5e4f5c1b8a66ce3728`.
- LanceDB rows: 0 before ingest, 1 after ingest, 1 after API restart, 0 after
  exact cleanup. Document directory and admin metadata were also absent after
  cleanup.
- Public path executed `documents.search` both before and after restart. The
  model’s final prose claimed no hit, so content quality is not upgraded to a
  verified retrieval claim; the persistence/index state is verified.
- No supported admin delete endpoint exists; direct targeted cleanup is a
  documented audit-only gap, not normal production behavior.

## Runtime trace contract

Public/persisted execution summaries include route trace ID, plan status, tool
name, status, attempts, error code, latency, and bounded result metadata such as
`hits_count`; arguments and result text remain redacted.

## Observed limitations (to record, not defects)

- Model tool-selection consistency remains a risk for unknown-tool/factual
  fallback behavior; the explicit multi-intent router defect is repaired and
  the two-tool live regression now passes.
- Dependent-step argument passing ($ref) remains the weakest link in plans;
  budget/recovery keeps failures honest.
- Fetched-page rejection (`access_denied_or_thin`) dominates on
  Cloudflare-guarded government sites; no retry-with-different-source
  refinement was observed in the 1-round budget.
- Research job state remains process-local `_JOBS`; durable job persistence is
  deferred and must be addressed before multi-worker production operation.
