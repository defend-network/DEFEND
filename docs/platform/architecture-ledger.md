# DEFEND Platform / Control Center — Architecture Ledger

Durable owner-facing architecture ledger for the DEFEND platform and the
Control Center supervision lane.

This is **documentation / observability**, not runtime authority. Product
lanes own the internal behavior of DEFEND AI, DEFENDcoder, DEFENDMarkets and
SCS; Control Center supervises; `shared_platform/` holds genuinely neutral
infrastructure. Keep this file updated through code and tests where practical.

Last updated: P0 Control Center / Platform Setup Foundation milestone.

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
- Compatibility adapter: `build_compatibility_manifests()` sources values from
  product-owned environment configuration (`ProductsSettings.from_env`) and is
  stamped `manifest_source=compatibility:...`. Products do not yet ship
  canonical manifest files; until they do, this bounded adapter is the source
  and the debt is tracked below.
- Status vocabulary: `ProductSupervisionState` — STOPPED / STARTING / RUNNING /
  DEGRADED / FAILED / EXTERNAL / UNKNOWN. RUNNING is never inferred from
  port-open alone (process identity + product health required).

## Ports (product-owned manifests)

| Product | API | Web | Source |
| --- | --- | --- | --- |
| DEFEND AI | 8401 | — | controller/runtime |
| DEFENDcoder | 8301 | 3301 | `CODER_API_PORT` / `CODER_WEB_PORT` |
| DEFENDMarkets | 8200 | 3200 | `SPORTS_API_PORT` / `SPORTS_WEB_PORT` |
| SCS | 8100 (core), 8300 (AI) | 3100 | `SCS_API_PORT` / `SCS_AI_API_PORT` / `SCS_WEB_PORT` |

Cross-product collision validation: `validate_product_manifests()` returns
PASS / COLLISION / UNKNOWN and never modifies values.

## Databases / persistence

| Area | Location (env) | Durability | Backup | Private | Migration risk |
| --- | --- | --- | --- | --- | --- |
| DEFEND AI data | `DEFEND_DATA_ROOT` (default `C:\DEFEND_DATA`) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| Coder workspace | `CODER_WORKSPACE_ROOT` (default `C:\DEFEND_CODER_DATA`) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| SCS data | `SCS_DATA_ROOT` (default `C:\SCS_DATA`) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| Markets data | `SPORTS_DATA_ROOT` (default `C:\DEFEND_SPORTS_DATA`) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |

Hosted PostgreSQL / pgvector / object storage remain a FUTURE architecture,
not an approved migration. The P0 milestone is inventory + observability only.

## Secret namespaces

- Single encrypted secret store: DPAPI `%LOCALAPPDATA%\DEFEND\secrets.dpapi`
  (`defend_control/secrets.py` `DpapiSecretStore`, consumed via
  `defend_integrations.stores.SecretRegistry`).
- Provider registry / secret catalog: `defend_integrations/registry.py`
  (`PROVIDERS`, `PRODUCT_PROVIDERS`, `REGISTRY_SECRET_NAMES`).
- `shared_platform/NamespacedSecrets` gives application-scoped logical views.
- One secret, one authority. Product-specific entitlement decides whether a
  product may use a credential — never duplicate copies per product.

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
| Vast (compute) | DEFENDcoder lane (coder provisioning). Control Center exposes no direct destroy path for product compute. |
| HF / model hubs | Platform credential (shared); product decides use |
| Odds/sports/financial APIs | DEFENDMarkets lane (credentials shared via platform vault) |
| Cloudflare tunnels | Per-product; Control Center supervises local tunnel it owns (SCS) |
| Email / billing providers | Platform (future) |

## Active Control Center dependencies (Section 32 audit)

| ID | Product | Control Center path | Why it exists | Replacement | Action |
| --- | --- | --- | --- | --- | --- |
| CC-01 | DEFEND AI | `defend_control/orchestrator.py`, `controller.py` | DEFEND AI has no standalone launch manifest yet; CC orchestrates vast/ollama locally | Product-owned launch contract | Retain as `LEGACY_PRODUCT_AUTHORITY`; do not expand |
| CC-02 | Coder Vast runtime | `defend_control/coder_vast_backend.py`, `coder_control_plane.py` | Compatibility while coder lane lands its runtime | `defend_coder` runtime | Migrating in coder lane; CC observes |
| CC-03 | Coder billing | `defend_control/coder_billing.py` | Neutral billing primitives | Neutral platform billing (future) | Keep neutral; no consumer charging |
| CC-04 | Markets launch | `tools/defend_sports_server` via `products.py` | Markets API process spec | Markets-owned manifest | Compatibility; not expanded |

## Membership / billing authority

- Identity authority: `defend_data.identity_store` (canonical local owner
  identity today).
- Membership (account/organization/role/entitlement): NOT_CONFIGURED — future
  neutral-platform milestone.
- Billing: `defend_control.coder_billing` holds neutral primitives (account,
  credit balance, usage ledger, spending limits). Consumer charging /
  Stripe / customer money: NOT_IMPLEMENTED.
- Future policy knobs (FREE_FLASH/PRO allowance, provider cost, overhead %,
  min balance, SOL access) are owner-configurable commercial policy later;
  usage accounting must be server-authoritative.

## Shared platform modules (`shared_platform/`)

| Module | Responsibility |
| --- | --- |
| `application.py` | `ApplicationContext` (ports, origins, namespaces, cookies) + cross-application collision validation |
| `services.py` | `ServiceProfile` / `RouteProfile` / `DeploymentProfile` / `validate_deployment` |
| `secrets.py` | `NamespacedSecrets` logical views |
| `phase0.py` | phase-0 deployment helpers |

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
- Old Control Center `SetupDialog` (tkinter secret catalog) coexists with the
  registry-driven web Setup (`defend-ui-v2`). Both read the same DPAPI store.
