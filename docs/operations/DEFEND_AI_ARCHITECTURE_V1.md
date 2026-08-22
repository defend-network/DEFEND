<!-- DEFEND-AI-INGEST: EXCLUDE -->
# DEFEND AI architecture map — V1

Operator document, not DEFEND AI training language. Never ingest into RAG,
memory, prompts, or model training data.

Audit date: 2026-08-20. Branch: `defend-ai/operational-readiness-v1`.
Auditor: operational readiness audit (P0–P18). All statements below were
verified live during the audit unless marked [CODE] (verified by code read).
Checkpoint: `e7927fe` (focused AI preservation) plus the continuation changes
being validated on this branch.

## 1. Deployment topology (as observed running)

| Component | Process / port | Status | Evidence |
|---|---|---|---|
| API (uvicorn) | `127.0.0.1:8000` | RUNNING | focused-branch process; `/live`, `/ready`, `/health` 200 |
| Ollama | `127.0.0.1:11434` | RUNNING | PID 85152; `/api/tags` lists `defend-ai:latest`, `qwen3-embedding:0.6b` |
| Model | `defend-ai:latest` = Qwen2.5 14B instruct Q4_K_M | LOADED (legacy plumbing) | Local-only evidence; not canonical model evidence. Canonical Qwen2.5-32B + LoRA requires authorized remote compute. |
| Embedding | `qwen3-embedding:0.6b` (1024 dims) | READY | healthcheck true; ingest+query round-trip verified |
| Data root | `C:\DEFEND_DATA` | READY | db/ persisted; controlled RAG restart fixture cleaned; permanent corpus empty after cleanup |
| UI | `defend-ui-v2/` | BUILD PRESENT | `.next` BUILD_ID `dXCoLvxIOidF1hR42l4Vu`; not launched this audit (port 3000 occupied by foreign build) |
| Public origin | `https://ai.defend-network.org` | DOWN | live probe returns HTTP 530 (Cloudflare origin error); tunnel `5f705a22-…` not serving DEFEND |
| Control Center | `tools/defend_control_center.py` | GUI-mode only | `--check` run; verdict NOT READY (ports blocked, invitation transport, public route) |

The continuation API was launched from the focused DEFEND AI worktree with
in-memory DPAPI secret resolution and `DEFEND_ENV=development` /
`DEFEND_COOKIE_SECURE=false`. The canonical Control Center settings still point
at the foreign `.worktrees/control-center-v2-integrate` repo_root; that
cross-lane discrepancy remains documented and untouched.

## 2. API surface (verified)

- `GET /health` — 200, `{"ok": true, "model": "defend-ai:latest", tools: [12]}`;
  identifies provider/model state but remains a compatibility health route.
- `GET /live` — process/core initialization liveness.
- `GET /ready` — control plane, data core, tool registry, configured model, and
  model inference readiness; live result had all five checks true.
- `POST /api/chat` — async chat job; visitor cookies `defend_vid` /
  `defend_vsid`; local process specs explicitly disable `Secure` for HTTP
  loopback development, while remote production specs explicitly retain
  `Secure=true`, `HttpOnly=true`, and `SameSite=lax`.
- `POST /api/chat/status/{job_id}` — job poll (in-memory `_JOBS`).
- Admin: `/api/admin/login`, `/api/admin/rag/{ingest,jobs,status,documents}`,
  `/api/admin/memory/{stats,proposals,commit,reject}`, analytics routes.
  All admin routes return 401 without bearer token (verified live).

## 3. Agent loop (verified live + [CODE])

- Routing: `control_plane.py` classifies into DIRECT / SINGLE_TOOL / COMPLEX /
  RESEARCH. Explicit calculation+time sequences now route `COMPLEX` before
  single-tool shortcuts; live execution produced two successful calls.
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
- Public responses and persisted assistant metadata expose bounded execution
  evidence (tool name, status, error code, latency, and result counts) without
  arguments or result text.
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
| RAG | `documents/` + `lancedb/` | Controlled fixture indexed, queried before and after API restart, then exact cleanup returned rows/docs to zero |
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
- HTTP + `Secure` cookies: the local-development path is repaired with an
  explicit environment policy; production HTTPS behavior remains unverified
  because the public origin is down.
- Research `_JOBS` remains process-local and is not durable across restart or
  multi-worker deployment; classify as an operational P1/P2 architecture gap,
  not silently fixed by the RAG restart test.

## 6. Canonical model reconciliation

The authoritative adapter metadata at the pinned private HF revision declares:

- Base: `unsloth/Qwen2.5-32B-Instruct-bnb-4bit`, revision
  `aa79e3472818bdec779075d80928602591d9f2a0`;
- Adapter: `Defend-network/defend-qwen-32b-lora`, revision
  `92c790d248012a5e6adac980b9759fb76bc7adda`;
- PEFT LoRA: r=16, alpha=16, dropout=0, target modules gate/down/q/o/k/v/up;
- Runtime: vLLM OpenAI-compatible remote deployment, served alias `defend-ai`;
- System prompt: `defend_system.py`, SHA-256
  `85f9ba6a40be7ba29774f00067b7d22e9f9da1834dc17997edfb313f790655b9`.

The directive’s Qwen3 assertion conflicts with immutable adapter metadata; the
manifest records the conflict. `defend-ai:latest`/Ollama Qwen2.5 14B remains a
legacy local plumbing alias and all dependent benchmarks are classified
`NON_CANONICAL_MODEL_RESULT` / `LOCAL_LEGACY_DEV_BASELINE`.

Re-verified 2026-08-22 against live Hugging Face metadata: adapter main sha is
unchanged (`92c790d…`), `adapter_config.json` still declares
`unsloth/Qwen2.5-32B-Instruct-bnb-4bit` as the base, and the org exposes no
Qwen3-32B DEFEND AI adapter (Qwen3-30B adapters belong to DEFENDmarkets and
DEFENDcoder only).

## 6a. Control Center model independence (verified 2026-08-22)

The shared admin surface (`api_server.py` launched by the Control Center) is
model-independent. It runs with `DEFEND_AI_PRODUCT_SERVICE=0` and therefore
does NOT construct a DEFEND AI model client, tool registry, ControlPlane, or
RAG embedding lane at startup. The `/health` payload reports
`model_state="stopped"` and `tools=[]`, and DEFEND AI capabilities report
explicitly unavailable. Only the DEFEND AI product runtime process specs
(`build_local_process_specs` / `build_remote_process_specs`) set
`DEFEND_AI_PRODUCT_SERVICE=1`, at which point the full product stack is built.
Regression coverage: `tests/test_admin_surface_model_independent.py`.

## 7. Continuation evidence

- User-path tool matrix: calculator, time, explicit calculator, memory,
  documents, invalid arguments, and mixed failure all executed or failed
  honestly; web research completed with honest `partial` status.
- Multi-tool regression: trace `8501368e-4f0f-4dfd-8ad5-f28425e7010d`, route
  `COMPLEX`, two successful calls (`calculator.evaluate`, `time.now`).
- RAG restart fixture: job `ragjob_c641361d06de44bcaad3`, document
  `doc_perm_f34b3a5e4f5c1b8a66ce3728`, rows 0→1 before restart and 1→0 after
  exact cleanup; no supported admin delete endpoint exists.
