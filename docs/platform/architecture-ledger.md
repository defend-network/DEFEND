# DEFEND Platform / Control Center — Architecture Ledger

Durable owner-facing architecture ledger for the DEFEND platform and the
Control Center supervision lane.

This is **documentation / observability**, not runtime authority. Product
lanes own the internal behavior of DEFEND AI, DEFENDcoder, DEFENDMarkets and
SCS; Control Center supervises; `shared_platform/` holds genuinely neutral
infrastructure. Keep this file updated through code and tests where practical.

Last updated: P0.3R strict legacy excision (`agent/platform-legacy-quarantine-r1`).

---

## Product authorities

| Product | Application id (Control Center) | Runtime owner | Control Center role |
| --- | --- | --- | --- |
| DEFEND AI | `defend` | DEFEND AI lane (controller/orchestrator) | Supervise only |
| DEFENDcoder | `coder` | DEFENDcoder lane (`defend_coder/runtime`, `defend_coder.launch`) | Supervise only; provider construction REMOVED (R3) |
| DEFENDMarkets | `markets` | DEFENDMarkets lane (`defend_markets/`, `defendmarkets-ui`, `defend_markets.launch`) | Supervise only |
| DEFEND Sports (legacy) | `sports` | transition/data-inspection only | Legacy; never masquerades as Markets |
| SCS | `scs` | SCS lane (`scs_data/supervision`, `scs_data/settings`, `scs_api/`) | Supervise only |

Control Center may START/STOP/observe product processes it owns and display
product-reported health. It may NOT own product models, tools, ports,
databases, provider decisions, risk/reasoning policy, GPU lifecycle, or call
provider APIs on a product's behalf.

## Product supervision manifests

- Neutral contract: `ProductSupervisionManifest` (`defend_control/supervision.py`).
  The product owns manifest values; Control Center consumes them.
- Compatibility adapter `build_compatibility_manifests()` stamps provenance
  per product (P0.2):
  - CODER: `product:defend_coder.launch.build_launch_manifest` (8301/3301/8403).
  - MARKETS: `product:defend_markets.launch.build_manifest` (8500/3500).
  - SCS: `product:scs_data.supervision.supervision_manifest` (SCS-owned env
    config; no side-effect import of `scs_api.runtime`).
  - DEFEND AI: `COMPATIBILITY_LEGACY` + `PRODUCT_CONTRACT_REQUIRED` — no
    canonical application supervision manifest; `defend_ai.launch` holds GPU
    LaunchSpecs only (not an app manifest).
  - DEFEND Sports: `COMPATIBILITY_LEGACY` transition surface.
- Status vocabulary: `ProductSupervisionState` — STOPPED / STARTING / RUNNING /
  DEGRADED / FAILED / EXTERNAL / UNKNOWN. RUNNING is never inferred from
  port-open alone (process identity + product health required).

## Ports (product-owned manifests) — P0.2 authority states

| Product | Component | Port | Source | Authority state |
| --- | --- | --- | --- | --- |
| DEFEND AI | api | 8401 | controller/runtime | COMPATIBILITY_LEGACY (PRODUCT_CONTRACT_REQUIRED) |
| DEFENDcoder | api | 8301 | `defend_coder.launch` | CANONICAL_PRODUCT |
| DEFENDcoder | ui | 3301 | `defend_coder.launch` | CANONICAL_PRODUCT |
| DEFENDcoder | model forward | 8403 | `defend_coder.launch` | CANONICAL_PRODUCT |
| DEFENDMarkets | api | 8500 | `defend_markets.launch` | CANONICAL_PRODUCT |
| DEFENDMarkets | ui | 3500 | `defend_markets.launch` | CANONICAL_PRODUCT |
| SCS | api | 8100 | `scs_data.supervision` | CANONICAL_PRODUCT |
| SCS | web | 3100 | `scs_data.supervision` | CANONICAL_PRODUCT |
| DEFEND Sports (legacy) | api | 8200 | `SPORTS_API_PORT` | COMPATIBILITY_LEGACY |
| DEFEND Sports (legacy) | web | 3200 | `SPORTS_WEB_PORT` | COMPATIBILITY_LEGACY |

Collision validator over the product-owned contracts: PASS.

Collision result on the integrated repository: PASS (no duplicates in the
current compatibility manifest set). Cross-product validation:
`validate_product_manifests()` returns PASS / COLLISION / UNKNOWN and never
modifies values.

## Databases / persistence

| Area | Location (env) | Durability | Backup | Private | Migration risk |
| --- | --- | --- | --- | --- | --- |
| DEFEND AI data | `DEFEND_DATA_ROOT` (default `C:\DEFEND_DATA`) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| Coder workspace | `CODER_WORKSPACE_ROOT` (default `C:\DEFEND_CODER_DATA`) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| SCS data | `SCS_DATA_ROOT` (default `C:\SCS_DATA`) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| Markets data | `SPORTS_DATA_ROOT` (default `C:\DEFEND_SPORTS_DATA`) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |

Hosted PostgreSQL / pgvector / object storage remain a FUTURE architecture,
not an approved migration. The P0 milestone is inventory + observability only.

## Secret namespaces (P0.1 — one implementation)

- CANONICAL physical store: `shared_platform/secure_store.py`
  (`DpapiSecretStore`, DPAPI) — the single implementation body.
- `shared_platform/dpapi.py` — TEMPORARY compatibility re-export -> secure_store
  (early coder callers); identity-proven same class object.
- `defend_control/secrets.py` — TEMPORARY legacy compatibility re-export ->
  secure_store.
- `shared_platform/secrets.py` (`NamespacedSecrets`) — LOGICAL namespaced views.
- Provider registry / secret catalog: `defend_integrations/registry.py`
  (`PROVIDERS`, `PRODUCT_PROVIDERS`, `REGISTRY_SECRET_NAMES`), consumed via
  `defend_integrations.stores.SecretRegistry`.
- One secret, one authority. `products=(...)` registry metadata expresses
  INTENDED/eligible products only — `PRODUCT_USE_ENFORCEMENT=NOT_IMPLEMENTED`
  (no runtime secret-resolution enforcement yet). Never duplicate copies.

## Model / runtime owners

| Artifact | Owner |
| --- | --- |
| DEFEND AI model registry / runtime | DEFEND AI lane (`defend_control/model_registry.py` is Control Center observation only) |
| Coder model routing / Vast runtime | DEFENDcoder lane |
| Markets M5 / prediction / settlement | DEFENDMarkets lane |
| SCS AI model gateway | SCS lane |

Control Center records runtime *state* (`ProductRuntimeRegistry`) but never
chooses product models or manages product GPU lifecycle directly.

## Provider owners

| Provider family | Owner |
| --- | --- |
| Vast low-level transport/client | `shared_platform/vast.py` (neutral authority: offers, instances, transport, inventory, create/destroy requests, state reads). No product GPU/approval/budget policy here. `defend_control/vast.py` is a shim. |
| Coder Vast runtime policy | DEFENDcoder lane (active Control Center path remains LEGACY_ACTIVE until Coder R3) |
| HF / model hubs | Platform credential (shared); product decides use |
| Odds/sports/financial APIs | DEFENDMarkets lane (credentials shared via platform vault) |
| Cloudflare tunnels | Per-product; Control Center supervises local tunnel it owns (SCS) |
| Email / billing providers | Platform (future; billing NOT_ESTABLISHED) |

## Active Control Center dependencies (Section 32 audit)

| ID | Product | Control Center path | Why it exists | Replacement | Action |
| --- | --- | --- | --- | --- | --- |
| CC-01 | DEFEND AI | `defend_control/orchestrator.py`, `controller.py` | DEFEND AI has no standalone launch manifest yet; CC orchestrates vast/ollama locally | Product-owned launch contract | Retain as `LEGACY_PRODUCT_AUTHORITY`; do not expand |
| CC-02 | Coder Vast runtime | `tools/defend_control_center.py::_build_coder_plane` (CoderControlPlane, CoderRemoteVllmBootstrap, VastCoderBackend, SshTunnel, VastClient) | Coder R3 owns migration of the active coder runtime | `defend_coder` runtime | `CONTROL_CENTER_CODER_PROVIDER_PATH=LEGACY_ACTIVE` until Coder R3 |
| CC-03 | Coder billing | `defend_control/coder_billing.py` | Coder-associated legacy primitives (NOT neutral authority) | Neutral platform billing (future) | `LEGACY_CODER_BILLING=EXISTS`; no consumer charging |
| CC-04 | Markets launch | `tools/defend_sports_server` via `products.py` | Markets API process spec | Markets-owned manifest | Compatibility; latest Markets lane PENDING |

## Membership / billing authority (P0.2 — unchanged)

- Identity: `LEGACY_OWNER_IDENTITY=defend_data.identity_store` (historically
  DEFEND-AI-owned/mixed — NOT a neutral-platform identity authority).
  `NEUTRAL_PLATFORM_IDENTITY_AUTHORITY=NOT_ESTABLISHED`. Membership
  (account/org/role/entitlement): `NOT_IMPLEMENTED`.
- Markets shared-owner auth bootstrap reads the existing shared store; it does
  NOT establish neutral identity ownership.
- Billing: `LEGACY_CODER_BILLING=EXISTS` (`defend_control.coder_billing` is
  Coder-associated/legacy mixed, NOT accepted as neutral authority).
  `NEUTRAL_PLATFORM_BILLING_AUTHORITY=NOT_ESTABLISHED`. `CONSUMER_BILLING=NOT_IMPLEMENTED`.
  No Stripe, no customer money, no token-ledger expansion.

## Shared platform modules (`shared_platform/`)

| Module | Responsibility |
| --- | --- |
| `secure_store.py` | CANONICAL physical DPAPI secret persistence (`DpapiSecretStore`) |
| `dpapi.py` | TEMPORARY compat re-export -> secure_store |
| `secrets.py` | `NamespacedSecrets` logical views |
| `vast.py` | Generic low-level Vast transport/client authority (NO product policy) |
| `ssh_tunnel.py` | Generic SSH transport/safety primitives (NO product approval policy) |
| `processes.py` | `ProcessSupervisor` / `ProcessSpec` (owned vs external) |
| `redaction.py` | `redact_text` neutral redaction |
| `windows_job.py` | `WindowsJob` process-group ownership |
| `compute_types.py` | `LaunchSpec` / `ResourceProfile` neutral compute dataclasses |
| `application.py` | `ApplicationContext` (ports, origins, namespaces, cookies) + collision validation |
| `services.py` | `ServiceProfile` / `RouteProfile` / `DeploymentProfile` / `validate_deployment` |
| `phase0.py` | phase-0 deployment helpers |

`defend_control/{secrets,redaction,processes,windows_job,vast,ssh_tunnel}.py`
are TEMPORARY legacy compatibility shims -> the shared_platform implementations.

## Public origins (product-owned)

| Product | Origin |
| --- | --- |
| DEFEND AI | `https://ai.defend-network.org` |
| DEFENDcoder | `https://defendcoder.defend-network.org` |
| DEFENDMarkets | `https://defendsports.defend-network.org` |
| SCS | `https://ai.sunshineclimatesolutions.com` |

## Legacy debt

- DEFEND AI launch remains controller-orchestrated; no product application
  supervision manifest (`PRODUCT_CONTRACT_REQUIRED` — Section 9).
- `CODER_LAUNCH_MANIFEST_CONFIG_DRIFT=OPEN`: `defend_coder.launch` still carries
  hardcoded constants (8301/3301/8403) while claiming env settings are
  canonical. Coder R3 owns that correction.
- `CONTROL_CENTER_CODER_PROVIDER_PATH=NONE` (R3 removed `_build_coder_plane`
  construction); remaining coder lifecycle wiring belongs to the NEXT Coder lane.
- Legacy `defend_control/products.py` still holds bespoke product service
  classes (SportsService, ScsService, CoderService, DefendService) — a thin
  generic-supervisor convergence is the target (Section 10), not completed here.
- Old Control Center `SetupDialog` (tkinter secret catalog) coexists with the
  registry-driven web Setup (`defend-ui-v2`). Both read the same DPAPI store.

## P0.2 integration state

| Lane | State |
| --- | --- |
| DEFEND AI | standalone PASS; C6-RZ PARTIAL; paid canary NOT READY; no app supervision manifest (PRODUCT_CONTRACT_REQUIRED) |
| DEFENDcoder | standalone PASS; runtime implementation ownership PASS; runtime manager/lifecycle wiring PARTIAL; Control Center provider authority CLOSED; launch manifest EXISTS |
| DEFENDMarkets | standalone PASS; setup/auth backend READY; owner login OWNER_ACTION_REQUIRED; `defend_markets.launch` + `defendmarkets-ui` + 8500/3500 integrated |
| SCS | standalone PASS; Setup V1 PASS; real-data acceptance OWNER_ACTION_REQUIRED; `scs_data.settings`/`scs_data.supervision` integrated |
| Platform | four-product integration PASS; neutral identity NOT_ESTABLISHED; neutral billing NOT_ESTABLISHED |
| Shared | secure store PASS; logical secrets PASS; Vast neutral PASS (VAST_PRODUCT_POLICY=NO); SSH neutral PASS (SSH_PRODUCT_POLICY=NO); processes PASS |

## P0.3R strict legacy excision (see `docs/platform/stack-registry.json`)

### CANONICAL PRODUCTS
`defend_ai/`, `defend_coder/`, `defend_markets/`, `defend_data/` (DEFEND AI),
`scs_*`, `defendmarkets-ui/`, `defendcoder-ui/`, `defend-ui-v2/`.

### NEUTRAL SHARED
`shared_platform/`, `defend_integrations/`.

### CONTROL CENTER
`defend_control/` — supervision/platform only. NOTE: still contains DEFEND-AI
orchestration (controller/orchestrator) and bespoke product service classes;
see OPEN MIGRATIONS.

### LEGACY ACTIVE (transitional)
`legacy_stack/defend_sports/`, `legacy_stack/control_center/coder_billing.py`,
`legacy_stack/table_tennis/`, `legacy_stack/tools/`.

### COMPATIBILITY SHIMS
NONE — the 13 defend_control shims were deleted in P0.3R (consumers migrated to
`shared_platform.*` / `defend_coder.runtime.*` / `defend_ai.deployment_profiles`).

### HISTORICAL REQUIRED
`legacy_stack/defend_sports/migrations/`, `evals/`, `bench/`.

### ARCHIVED
(none yet — `archive/` reserved, non-importable, no `__init__.py`).

### OPEN MIGRATIONS (P0.3R residual debt)
- AUDIT-01 (CRITICAL): `defend_markets/collector.py` still imports AND writes
  `legacy_stack.defend_sports.*` (TheOddsApiSportsProvider, IngestionService,
  SportsRepository, SportsDatabase). `MARKETS_LEGACY_SPORTS_DB_WRITE=ACTIVE`.
  Owner: DEFENDMarkets lane — migrate collector to `MarketsDatabase`/
  `MarketsRepository`/`FeedService`.
- AUDIT-02/03: `defend_control/{controller,orchestrator,local_model,remote_vllm,
  preflight}.py` still contain DEFEND-AI provider authority (Vast rent/destroy,
  Ollama). Owner: DEFEND AI lane (whole-product runtime isolation, Section 22).
- AUDIT-02/06: `defend_control/products.py` still holds product settings +
  `build_*_process_spec` + bespoke service classes (DefendService, SportsService,
  ScsService, CoderService). Owner: Platform generic-supervisor convergence.
- AUDIT-07: old `SetupDialog` (tkinter) still in `defend_control/ui.py`.
- DEFEND AI application supervision manifest (`PRODUCT_CONTRACT_REQUIRED`) — AI lane.
- Root-level DEFEND-AI runtime files (`api_server.py`, `control_plane.py`, ...)
  classified `CANONICAL_DEFEND_AI_MISPLACED` — NEXT DEFEND AI directive moves them.
- Neutral identity + neutral billing — future Platform milestone (NOT started).
