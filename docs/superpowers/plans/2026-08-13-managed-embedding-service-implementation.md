# Managed Embedding Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove RAG's implicit dependency on local Ollama by adding an explicit, testable embedding-provider boundary with vLLM/OpenAI-compatible support and a deliberate Ollama fallback.

**Architecture:** A factory builds one `EmbeddingClient` from validated environment configuration. RAG tools receive that interface rather than constructing Ollama directly. The first release changes no launcher topology: Ollama remains the default for compatibility, while vLLM can be selected and tested independently before remote service orchestration is added.

**Tech Stack:** Python 3.14, httpx, FastAPI, pytest, Ollama embeddings API, OpenAI-compatible `/v1/embeddings`.

## Global Constraints

- Existing DEFEND behavior and tests remain green.
- Provider endpoints must be loopback HTTP(S); credentials are environment-only and never rendered.
- Vector dimension is exactly 1024 for the current LanceDB generation.
- Empty inputs return an empty list without a network request.
- Every returned vector is finite, numeric, 1024-dimensional, and ordered exactly like the input.
- RAG ingestion must fail clearly at readiness time rather than accepting an unusable provider.

---

### Task 1: OpenAI-compatible embedding client

**Files:**
- Create: `openai_embedding_client.py`
- Test: `tests/test_embedding_clients.py`

**Interfaces:**
- Produces: `OpenAIEmbeddingClient(model: str, base_url: str, api_key: str, timeout: float = 120.0, batch_size: int = 32, vector_dim: int = 1024)` implementing `EmbeddingClient`.

- [ ] Write failing tests using `httpx.MockTransport` for batched `/v1/embeddings`, index-order restoration, bearer authentication, health/model verification, malformed dimensions, non-finite values, and secret-safe errors.
- [ ] Run `pytest tests/test_embedding_clients.py -q` and verify failure because the client is missing.
- [ ] Implement the minimal client, dependency injection for transport tests, bounded batches, schema validation, and `close()`.
- [ ] Run the focused tests and verify they pass.
- [ ] Commit `Add OpenAI-compatible embedding client`.

### Task 2: Provider configuration and factory

**Files:**
- Create: `embedding_provider.py`
- Modify: `embedding_client.py`
- Test: `tests/test_embedding_provider.py`

**Interfaces:**
- Produces: `EmbeddingSettings.from_env(env: Mapping[str, str])` and `build_embedding_client(settings: EmbeddingSettings) -> EmbeddingClient`.

- [ ] Write failing tests for default Ollama, explicit vLLM selection, required vLLM key, loopback endpoint enforcement, exact dimension, positive timeout/batch size, unknown settings, and sanitized exceptions.
- [ ] Run the focused tests and verify RED.
- [ ] Implement immutable settings and the provider factory.
- [ ] Run focused tests and verify GREEN.
- [ ] Commit `Add configurable embedding provider`.

### Task 3: Inject the provider into RAG tools

**Files:**
- Modify: `registry.py`
- Modify: `tools/rag_ingest.py`
- Modify: `tools/rag_query.py`
- Modify: `tools/research_cache_ingest.py`
- Modify: `api_server.py`
- Test: `tests/test_embedding_registry.py`
- Test: `tests/test_admin_rag.py`

**Interfaces:**
- `build_default_registry(memory_manager=None, embedding_client: EmbeddingClient | None = None)` injects one shared client into all RAG tools.

- [ ] Write failing tests proving the three RAG tools share the configured client and no longer instantiate Ollama when injected.
- [ ] Run focused tests and verify RED.
- [ ] Generalize tool type hints to `EmbeddingClient`, inject through the registry, build once in API lifespan, and close it during shutdown.
- [ ] Run focused tests and verify GREEN.
- [ ] Commit `Inject managed embeddings into RAG tools`.

### Task 4: Fail-fast permanent ingestion readiness

**Files:**
- Modify: `defend_data/admin_rag.py`
- Modify: `api_server.py`
- Modify: `defend-ui-v2/components/admin/KnowledgeRagPanel.tsx`
- Modify: `defend-ui-v2/lib/api.ts`
- Test: `tests/test_admin_rag.py`
- Test: `tests/test_admin_rag_api.py`
- Test: `defend-ui-v2/components/admin/__tests__/KnowledgeRagPanel.test.tsx`

**Interfaces:**
- `PermanentRagService(..., readiness_check: Callable[[], Awaitable[bool]], provider_label: str)` rejects a new job with a safe actionable error when unavailable.

- [ ] Write failing backend and frontend tests for unavailable/readied providers and visible provider/model status.
- [ ] Run focused tests and verify RED.
- [ ] Implement the readiness gate and status payload without exposing keys/endpoints.
- [ ] Run focused tests and verify GREEN.
- [ ] Commit `Add embedding readiness to permanent RAG`.

### Task 5: Documentation and full verification

**Files:**
- Modify: `docs/operations/DEFEND-Control-Center.md`
- Modify: `.env.example` if present, otherwise document variables without creating a secret-bearing file.

- [ ] Document `DEFEND_EMBEDDING_PROVIDER`, model, endpoint, dimension, timeout, batch size, encrypted API-key name, Ollama fallback, and re-indexing rule.
- [ ] Run the complete backend suite with an isolated `--basetemp`.
- [ ] Run the complete frontend suite.
- [ ] Run the Next.js production build.
- [ ] Run a secret-pattern scan and `git diff --check`.
- [ ] Commit `Document managed embedding operations`.
- [ ] Push the PR branch and update PR #4 with validation evidence.
