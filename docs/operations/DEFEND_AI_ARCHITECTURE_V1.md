<!-- DEFEND-AI-INGEST: EXCLUDE -->
# DEFEND AI architecture map — V1

Operator document, not DEFEND AI training language. Never ingest into RAG,
memory, prompts, or model training data.

Audit date: 2026-08-20. Branch: `sports/ds0-shared-platform-3app`.
Auditor: operational readiness audit (P0–P18). All statements below were
verified live during the audit unless marked [CODE] (verified by code read).

## 1. Deployment topology (as observed running)

| Component | Process / port | Status | Evidence |
|---|---|---|---|
| API (uvicorn) | `127.0.0.1:8000` | RUNNING | PID 98236 (restarted after fix); `/health` 200 |
| Ollama | `127.0.0.1:11434` | RUNNING | PID 85152; `/api/tags` lists `defend-ai:latest`, `qwen3-embedding:0.6b` |
| Model | `defend-ai:latest` = Qwen2.5 14B instruct Q4_K_M | LOADED | digest `d799217c…`; parent blob = `qwen2.5:14b-instruct-q4_K_M` (`7cdf5a01…`); 4.19 GB VRAM of 6.14 GB (partial offload) |
| Embedding | `qwen3-embedding:0.6b` (1024 dims) | READY | healthcheck true; ingest+query round-trip verified |
| Data root | `C:\DEFEND_DATA` | READY | db/, documents/ (empty), lancedb/ (empty), research_cache/ (empty) |
| UI | `defend-ui-v2/` | BUILD PRESENT | `.next` BUILD_ID `dXCoLvxIOidF1hR42l4Vu`; not launched this audit (port 3000 occupied by foreign build) |
| Public origin | `https://ai.defend-network.org` | DOWN | live probe returns HTTP 530 (Cloudflare origin error); tunnel `5f705a22-…` not serving DEFEND |
| Control Center | `tools/defend_control_center.py` | GUI-mode only | `--check` run; verdict NOT READY (ports blocked, invitation transport, public route) |

API was launched via temp launcher (in-memory DPAPI secret injection, secret
names only) from the main repo because the canonical Control Center launch
path currently points at the foreign worktree `.worktrees/control-center-v2-integrate`
(repo_root) and port 3000 is occupied by a foreign UI build. Deviation is
documented, not a product defect.

## 2. API surface (verified)

- `GET /health` — 200, `{"ok": true, "model": "defend-ai:latest", tools: [12]}`.
  Health checks Ollama `/api/tags` only — does NOT verify the model is loaded
  (HTTP 200 != model ready). [CODE] `ollama_client.py` healthcheck; debug
  `print("Installed models:", …)` left in `ollama_client.py:60`.
- `POST /api/chat` — async chat job; visitor cookies `defend_vid` /
  `defend_vsid`; `Secure` flag on cookies (default `DEFEND_COOKIE_SECURE=true`)
  breaks non-browser HTTP clients; browser loopback behavior unverified.
- `POST /api/chat/status/{job_id}` — job poll (in-memory `_JOBS`).
- Admin: `/api/admin/login`, `/api/admin/rag/{ingest,jobs,status,documents}`,
  `/api/admin/memory/{stats,proposals,commit,reject}`, analytics routes.
  All admin routes return 401 without bearer token (verified live).

## 3. Agent loop (verified live + [CODE])

- Routing: `control_plane.py` classifies into DIRECT / SINGLE_TOOL / COMPLEX /
  RESEARCH (greeting → COMPLEX/plan path; arithmetic → SINGLE_TOOL; research
  phrasing → RESEARCH).
- System prompt: `defend_system.py` (15 007 chars; sha256 `85f9ba6a…`);
  single system message on ControlPlane paths; grounding second system message
  only inside `generate_structured` on the real client. No `SYSTEM.txt`
  override. Modelfile: `FROM qwen2.5:14b-instruct-q4_K_M`, temp 0.65,
  num_ctx 8192, SYSTEM = DEFEND system prompt.
- Tool selection: `_ask_for_tool_call` (SingleToolDecision) and
  `_ask_for_plan` (ProposedPlan) build an `available` list from the registry.
  DEFECT FOUND AND REPAIRED during this audit: the list was built but never
  injected into the model prompt (dead code) — the model hallucinated tool
  names (e.g. `calculator` instead of `calculator.evaluate`) and
  `_compile_tool_call` raised ValueError → silent DIRECT fallback, so NO
  model-initiated tool call ever executed through the public agent path.
  Fix: append the serialized tool list (name/description/input_schema) to the
  system prompt in both functions. Regression tests added
  (`tests/test_control_plane_tools.py`, 3 tests). After fix, live API tests
  show route=COMPLEX with real tool execution.
- Tool execution: `_execute_step` → `_compile_tool_call` (name allowlist +
  `ALLOWED_TOOLS` policy via `production_policy.py`) → `_resolve_arguments`
  ($ref / ValueRef) → `tool.execute` → observations fed back; budget guard on
  plan steps.
- Research path: job → web.search (Tavily) → parallel web.fetch batch →
  evidence assessment (accept/reject `access_denied_or_thin`) → finalize.
  Verified end-to-end (1.4 min job, 3 sources attempted, honest
  `insufficient_evidence` abstention when all evidence rejected).

## 4. Data layer (verified)

| Store | File | State |
|---|---|---|
| identity | `C:\DEFEND_DATA\db\identity.db` | owner `chairman@defend-network.org` active; 0 invitations; invitation transport gate present |
| conversations | `db\conversations.db` | 8+ audit conversations persisted across API restart (P7B verified) |
| memory | `db\memory.db` | write→propose→commit→search round-trip verified; visitor-scoped namespaces (`user:vis_…`) |
| visitors | `db\visitors.db` | cookie/session issuance verified |
| catalog | `db\catalog.db` | artifact catalog |
| RAG | `documents/` + `lancedb/` | EMPTY at audit start; ingest→index→vector+BM25 retrieval round-trip verified (test doc added, queried, removed) |
| research cache | `research_cache/` | empty |

## 5. Key architectural findings

- P0 BLOCKER (repaired): tool schemas not injected into model prompts — fixed
  in `control_plane.py` with regression tests; re-verified live through API.
- Model-initiated tool use remains fragile: dependent-step $ref resolution
  failed once live (`Unsupported expression node: Set` — calculator received
  an unexpected argument structure from a resolved step-2 arg); model
  recovered honestly and answered manually.
- `rag_store.py` and `documents_store.py` resolve their index/store from the
  process CWD (`artifacts/lancedb`, default `artifacts`) when
  `DEFEND_DATA_ROOT` is absent. Canonical Control Center launch always sets
  `DEFEND_DATA_ROOT`; ad-hoc launches without it silently use a different
  index than the admin ingest path. Operational risk to record, not a
  product defect.
- Public agent path does not redact system-prompt echo: prompt-injection
  probe extracted the system prompt verbatim (~10k chars, P13 finding).
- Health endpoint reports model presence, not readiness (partial-load false
  positives after cold start).
- HTTP + `Secure` cookies: multi-turn chat and research job polls fail for
  compliant non-browser clients over plain HTTP; works in browser-over-HTTPS
  (unverified live because the public origin is down).