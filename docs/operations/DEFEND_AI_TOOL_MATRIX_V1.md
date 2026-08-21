<!-- DEFEND-AI-INGEST: EXCLUDE -->
# DEFEND AI tool matrix — V1

Operator document, not DEFEND AI training language. Never ingest into RAG,
memory, prompts, or model training data.

Audit date: 2026-08-20. Branch: `sports/ds0-shared-platform-3app`.
Status key: LIVE = exercised live this audit; CODE = verified by code read only;
N/A = not applicable to current deployment state.

## Registered tools (12, via `registry.py`; health payload confirms)

| # | Tool | Description | Risk | Side effect | Live status | Notes / evidence |
|---|---|---|---|---|---|---|
| 1 | documents.search | Search indexed docs | LOW | READ | CODE | N/A: no permanent corpus present at audit start; retrieval path verified via rag.query on temp doc |
| 2 | rag.query | Semantic/lexical/hybrid query of knowledge index | LOW | READ | LIVE | vector + BM25 hits on temp doc (distance 0.43); score method rrf/vector_distance/bm25 |
| 3 | rag.ingest | Permanent ingest (admin-gated) | LOW | WRITE | LIVE | `ALLOWED_TOOLS` policy excludes for public; verified via admin API: 202 → job → indexed (1 chunk), meta + vector round-trip |
| 4 | research.cache_ingest | Cache research findings into index | LOW | WRITE | CODE | present in registry; fires inside research finalize on PDF content |
| 5 | calculator.evaluate | Safe expression evaluation | LOW | READ | LIVE | exact `3*4 → 12`; bad-arg `hello world` → invalid syntax error surfaced honestly |
| 6 | time.now | Current UTC time | LOW | READ | LIVE | live run returned correct UTC 20:32:23 through agent path (route COMPLEX, tool executed) |
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

## Observed limitations (to record, not defects)

- Model tool-selection consistency is low: same-shaped requests sometimes
  route DIRECT (model refuses tools) — e.g. one `time_now` run answered
  without the tool, another executed it.
- Dependent-step argument passing ($ref) is the weakest link in multi-step
  plans; budget/recovery keeps failures honest.
- Fetched-page rejection (`access_denied_or_thin`) dominates on
  Cloudflare-guarded government sites; no retry-with-different-source
  refinement was observed in the 1-round budget.