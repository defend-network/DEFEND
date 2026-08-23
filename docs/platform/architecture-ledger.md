# DEFEND Platform / Control Center — Architecture Ledger

Durable owner-facing architecture ledger for the DEFEND platform and the
Control Center supervision lane.

This is **documentation / observability**, not runtime authority. Product
lanes own the internal behavior of DEFEND AI, DEFENDcoder, DEFENDMarkets and
SCS; Control Center supervises; `shared_platform/` holds genuinely neutral
infrastructure. Keep this file updated through code and tests where practical.

Last updated: P0.1 canonical integration anchor (`agent/platform-integration-v1`).

---

## Product authorities

| Product | Application id (Control Center) | Runtime owner | Control Center role |
| --- | --- | --- | --- |
| DEFEND AI | `defend` | DEFEND AI lane (controller/orchestrator) | Supervise only |
| DEFENDcoder | `coder` | DEFENDcoder lane (`defend_coder/`, `coder_*` plane) | Supervise only |
| DEFENDMarkets | `sports` | DEFENDMarkets lane (`defend_markets/`, `tools/defend_sports_server`) | Supervise only |
| SCS | `scs` | SCS lane (`scs_ai/`, `scs_api/`, `scs-ui/`) | Supervise only |

Control Center may START/STOP/observe product processes it owns and display
product-reported health. It may NOT own product models, tools, ports,
databases, provider decisions, risk/reasoning policy, GPU lifecycle, or call
provider APIs on a product's behalf.

## Product supervision manifests

- Neutral contract: `ProductSupervisionManifest` (`defend_control/supervision.py`).
  The product owns manifest values; Control Center consumes them.
- Compatibility adapter: `build_compatibility_manifests()` stamps explicit
  provenance per product (P0.1):
  - CODER: `product:defend_coder.launch.build_launch_manifest` (product-owned
    launch contract consumed; Control Center does NOT redefine ports/commands).
  - DEFEND AI: `COMPATIBILITY_LEGACY` — no canonical application supervision
    manifest; `defend_ai.launch` holds GPU LaunchSpecs only (not an app manifest).
  - SCS: `COMPATIBILITY_LEGACY` — no clean manifest loadable without side effects.
  - DEFENDMarkets: `COMPATIBILITY_LEGACY` + `MARKETS_MANIFEST_STATE=LEGACY/
    PENDING_LATEST_MARKETS_LANE` (latest Markets lane not integrated).
- Status vocabulary: `ProductSupervisionState` — STOPPED / STARTING / RUNNING /
  DEGRADED / FAILED / EXTERNAL / UNKNOWN. RUNNING is never inferred from
  port-open alone (process identity + product health required).

## Ports (product-owned manifests) — P0.1 authority states

| Product | Component | Port | Source | Authority state |
| --- | --- | --- | --- | --- |
| DEFEND AI | api | 8401 | controller/runtime | COMPATIBILITY_LEGACY |
| DEFENDcoder | api | 8301 | `defend_coder.launch` | CANONICAL_PRODUCT |
| DEFENDcoder | ui | 3301 | `defend_coder.launch` | CANONICAL_PRODUCT |
| DEFENDcoder | model forward | 8403 | `defend_coder.launch` | CANONICAL_PRODUCT |
| DEFENDMarkets | api | 8200 | `SPORTS_API_PORT` | COMPATIBILITY_LEGACY |
| DEFENDMarkets | web | 3200 | `SPORTS_WEB_PORT` | COMPATIBILITY_LEGACY |
| SCS | core api | 8100 | `SCS_API_PORT` | COMPATIBILITY_LEGACY |
| SCS | ai api | 8300 | `SCS_AI_API_PORT` | COMPATIBILITY_LEGACY |
| SCS | web | 3100 | `SCS_WEB_PORT` | COMPATIBILITY_LEGACY |

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

## Membership / billing authority (P0.1 corrected)

- Identity: `LEGACY_OWNER_IDENTITY=defend_data.identity_store` (historically
  DEFEND-AI-owned/mixed — NOT a neutral-platform identity authority).
  `NEUTRAL_PLATFORM_IDENTITY_AUTHORITY=NOT_ESTABLISHED`. Membership
  (account/org/role/entitlement): `NOT_IMPLEMENTED`.
- Billing: `LEGACY_CODER_BILLING=EXISTS` (`defend_control.coder_billing` is
  Coder-associated/legacy mixed, NOT accepted as neutral authority).
  `NEUTRAL_PLATFORM_BILLING_AUTHORITY=NOT_ESTABLISHED`. `CONSUMER_BILLING=NOT_IMPLEMENTED`.
  No Stripe, no customer money, no token-ledger expansion.
- Sequencing: membership/billing come AFTER product runtime boundaries + the
  Markets standalone migration complete.

## Shared platform modules (`shared_platform/`)

| Module | Responsibility |
| --- | --- |
| `secure_store.py` | CANONICAL physical DPAPI secret persistence (`DpapiSecretStore`) |
| `dpapi.py` | TEMPORARY compat re-export -> secure_store |
| `secrets.py` | `NamespacedSecrets` logical views |
| `vast.py` | Generic low-level Vast transport/client authority |
| `processes.py` | `ProcessSupervisor` / `ProcessSpec` (owned vs external) |
| `redaction.py` | `redact_text` neutral redaction |
| `windows_job.py` | `WindowsJob` process-group ownership |
| `compute_types.py` | `LaunchSpec` / `ResourceProfile` neutral compute dataclasses |
| `application.py` | `ApplicationContext` (ports, origins, namespaces, cookies) + collision validation |
| `services.py` | `ServiceProfile` / `RouteProfile` / `DeploymentProfile` / `validate_deployment` |
| `phase0.py` | phase-0 deployment helpers |

`defend_control/{secrets,redaction,processes,windows_job,vast}.py` are TEMPORARY
legacy compatibility shims -> the shared_platform implementations.

## Public origins (product-owned)

| Product | Origin |
| --- | --- |
| DEFEND AI | `https://ai.defend-network.org` |
| DEFENDcoder | `https://defendcoder.defend-network.org` |
| DEFENDMarkets | `https://defendsports.defend-network.org` |
| SCS | `https://ai.sunshineclimatesolutions.com` |

## Legacy debt

- Product launch defaults still live in `defend_control/products.py`
  (`ProductsSettings`, `build_*_process_spec`). Marked `LEGACY_PRODUCT_AUTHORITY`;
  the compatibility manifests consume the same product-owned env config so the
  values are not duplicated.
- `CODER_LAUNCH_MANIFEST_CONFIG_DRIFT=OPEN`: `defend_coder.launch` still carries
  hardcoded constants (8301/3301/8403) while claiming env settings are
  canonical. Coder R3 owns that correction.
- `CONTROL_CENTER_CODER_PROVIDER_PATH=LEGACY_ACTIVE`: `tools/defend_control_center.py`
  still constructs the coder provider plane (Vast path). Coder R3 removes it.
- Old Control Center `SetupDialog` (tkinter secret catalog) coexists with the
  registry-driven web Setup (`defend-ui-v2`). Both read the same DPAPI store.

## P0.1 integration state

| Lane | State |
| --- | --- |
| DEFEND AI | standalone product boundary PASS; C6-R PARTIAL; no canonical app supervision manifest (GPU LaunchSpec only) |
| DEFENDcoder | standalone API/UI PASS; product runtime lifecycle PARTIAL; active CC Vast path OPEN; product launch manifest EXISTS |
| DEFENDMarkets | latest standalone migration NOT INTEGRATED / PENDING (auditor convergence) |
| SCS | standalone PASS; B4 PASS; real-data M1.5C owner action pending |
| Platform | supervision foundation PASS; full provider-boundary convergence PARTIAL |
| Shared | physical secret store authority PASS; logical secret namespace PASS; Vast neutral authority PASS; process authority PASS; membership NOT_ESTABLISHED; billing NOT_ESTABLISHED |
