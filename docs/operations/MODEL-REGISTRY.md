<!-- DEFEND-AI-INGEST: EXCLUDE -->
# DEFEND AI model registry — audit summary and wiring checklist

Operator document, not DEFEND AI training language. Never ingest it into RAG,
memory, prompts, or model training data.

Scope: DEFEND AI model lane only (identity chat adapter, local Ollama tag,
embedding lane). DEFENDcoder lanes keep their own registry in
`defend_control/coder_m0.py`; this document does not change them.

## 1. Exact identifiers found in-repo (no guessing)

| Identity | Value | Source (exact paths) |
|---|---|---|
| PRODUCTION Adapter / LoRA HF repo | `Defend-network/defend-identity-lora-v002` | `defend_control/model_registry.py` (`ADAPTER_REPO`), imported by `defend_control/huggingface.py`, `defend_control/settings.py`, `defend_control/remote_vllm.py`, `tools/defend_control_center.py` |
| PRODUCTION Adapter revision | `46ade1686870210ef0ab4603c32fecb0e563330f` | `defend_control/model_registry.py` (`ADAPTER_REVISION`, owner-provided pin); overridable per deployment via `DEFEND_ADAPTER_REVISION` (strict SHA) |
| Legacy adapter (NOT production) | `Defend-network/defend-qwen-32b-lora` | `defend_control/model_registry.py` (`LEGACY_ADAPTER_REPO`); superseded — no launch path resolves or serves it. Historical refs: `docs/superpowers/plans/2026-08-10-defend-control-center-vast-vllm-implementation.md:19,256`, `:678-689` |
| Preserved GGUF sibling | `Defend-network/defend-qwen-32b-gguf` | `defend_control/huggingface.py:17`, plan doc `:20` (never served via vLLM) |
| Serving alias (vLLM) | `defend-ai` | `defend_control/remote_vllm.py:189` (`--lora-modules defend-ai=...`), `:279,292`; `defend_control/model_probe.py:162,172-173`; `defend_control/orchestrator.py:709` |
| Local Ollama tag | `defend-ai:latest` | `model_factory.py:12`, `api_server.py:49`, `ui_app.py:22`, `tools/defend_control_center.py:583` |
| Base model | NOT hardcoded in repo | Derived at deploy time from the adapter's `adapter_config.json` (`base_model_name_or_path` + `revision`): `defend_control/huggingface.py:130-148` |
| Embedding model | `qwen3-embedding:0.6b` / `Qwen/Qwen3-Embedding-0.6B` | `embedding_provider.py:85-87`, `defend_data/admin_rag.py:99` |

The production adapter name (`defend-identity-lora-v002`) and the
trained-weights claim are consistent with the mission statement's "trained
Qwen3 ~30B adapter/LoRA"; the exact base model string exists only inside the
adapter repo's `adapter_config.json`, not in this checkout. The first-
generation `defend-qwen-32b-lora` adapter is legacy metadata only.

## 2. Pin status — production pin recorded

`defend_control/model_registry.py:ADAPTER_REVISION` is pinned to the
owner-provided SHA `46ade1686870210ef0ab4603c32fecb0e563330f` for
`Defend-network/defend-identity-lora-v002`. `adapter_revision_pin()` returns
this pin by default; `DEFEND_ADAPTER_REVISION` overrides it per deployment
(strict 40-64 hex SHA; invalid values fail loudly, they do not fall back).

## 3. Wiring path: registry → client → /health

```
defend_control/model_registry.py        alias -> repo/revision/adapter metadata
        │  resolve_defend_alias("defend-ai")  -> DefendModelRef (identity-adapter)
        │  adapter_revision_pin()             -> env DEFEND_ADAPTER_REVISION (optional)
        ▼
defend_control/huggingface.py            HuggingFaceClient.resolve_adapter(repo, HF_TOKEN)
        │  returns AdapterSpec{adapter_repo, adapter_revision, base_repo,
        │                       base_revision, peft_type=LORA, lora_rank}
        ▼
defend_control/orchestrator.py           resolves adapter once per vast launch
        │  passes adapter=self._vast_adapter into
        ▼
defend_control/remote_vllm.py            build_remote_process_specs(..., adapter)
        │  injects DEFEND_MODEL_ADAPTER_REPO / _REVISION / DEFEND_MODEL_BASE_REPO / _REVISION
        ▼
api_server.py  (model_factory.py)        build_model_client() -> OpenAICompatibleModelClient
        │  DEFEND_MODEL_BACKEND=openai_compatible, DEFEND_MODEL=defend-ai,
        │  base 127.0.0.1:8001/v1, key from secrets
        ▼
api_server.py  /health                   {"ok", "application_id", "model", "model_state",
                                          "provider", "adapter_repo", "adapter_revision",
                                          "base_repo", "base_revision", "tools"}
```

Local Ollama path is unchanged: `build_local_process_specs` injects
`DEFEND_MODEL_BACKEND=ollama` + `DEFEND_MODEL=defend-ai:latest`
(`defend_control/local_model.py:117-119`); the Modelfile defines the local
tag. No adapter env is injected locally — the card reports "built-in local
Modelfile".

## 4. /health fields (added 2026-08-17, branch platform/control-center-v2-integrate)

| Field | Meaning | Values |
|---|---|---|
| `model_state` | READY/OFFLINE/FAILED equivalent | `ready` (ok + healthcheck pass), `offline` (client present, healthcheck fail), `failed` (no client) |
| `provider` | serving backend | `ollama` / `openai_compatible` |
| `adapter_repo` / `adapter_revision` | pinned identity adapter | from launch env; `null` when unset |
| `base_repo` / `base_revision` | base model resolved at deploy | from launch env; `null` when unset |
| `application_id` | product identity | `defend` |

No-silent-fallback guarantees:

- `OpenAICompatibleModelClient.healthcheck` requires the served `/v1/models`
  id to match `defend-ai` (`openai_compatible_client.py:67-89`); a generic
  Qwen alias fails the check → `model_state: offline`.
- `resolve_defend_alias` raises for unknown aliases; it never returns a
  generic base-model entry (`defend_control/model_registry.py`).
- `HuggingFaceClient.resolve_adapter` rejects non-LORA adapters, invalid
  ranks (1..512), invalid base repos, and non-SHA revisions
  (`defend_control/huggingface.py:121-148`).
- `RemoteVllmBootstrap` refuses any adapter whose repo differs from
  `Defend-network/defend-identity-lora-v002` (`defend_control/remote_vllm.py:74-86`).
- Secrets (HF_TOKEN, VLLM_API_KEY) never enter the registry, launch env of
  the web process, or `/health`; they flow only through Setup's DPAPI store
  into the API process env.

## 5. Product card / lifecycle notes (Control Center v2)

`DefendService.status()` (`defend_control/products.py:379-464`) now shows:

- Model backend (vast / ollama), owned services
- Serving alias, Provider, Adapter, Adapter revision

Gap (reported, not fixed): `UIState` (`defend_control/controller.py:23-61`)
does not carry the resolved `AdapterSpec`, so the card reads env values that
are accurate for the child API process only after launch; the orchestrator's
`self._vast_adapter` is not surfaced. Recommended owner window:
`platform/control-center-v2-integrate` — thread `AdapterSpec` through
`UIState` + `DefendService.status()` so the card shows the same
base/adapter/revision the API serves, without env indirection. Lifecycle
states remain `ServiceState` (`stopped/validating/provisioning/starting/
ready/degraded/stopping/failed`); no lifecycle changes were made.

## 6. Verification

- New tests: `tests/test_model_registry.py` (17 tests — alias resolution,
  read-only preservation of the production repo + pinned SHA, legacy adapter
  is non-resolvable, immutable entries, pin validation, no-secret status
  payload, no-silent-fallback failure modes).
- Control-center suites (settings/secrets, local, preflight, orchestrator,
  SSH/vLLM, HF/Vast, admin surface, entrypoint) updated to consume
  `ADAPTER_REPO` from the registry — no file keeps a legacy literal.
- No GPU compute was launched; nothing in this change provisions or bills
  Vast.ai. Next step (owner approval required): run the verified vLLM launch
  path with the pinned `defend-identity-lora-v002@46ade168...` and confirm
  `/health` reports `model_state: ready` with the pinned adapter/base
  revisions.