# DEFENDcoder UI + Control Center V2 Design

## Goal
Deliver a production-facing DEFENDcoder login/workspace surface and a unified Control Center that launches and observes four independent product spaces: DEFEND AI, DEFEND Sports, DEFENDcoder, and SCS AI.

## Product boundaries
- **DEFEND AI** remains the existing identity/chat product and keeps its current launch behavior.
- **DEFEND Sports** remains an independent FastAPI/PostgreSQL product with its own API/web lifecycle.
- **DEFENDcoder** becomes a general-purpose coding product for arbitrary repositories/workspaces; DEFEND/SCS repos are only first-party acceptance workloads.
- **SCS AI** remains an SCS-owned subservice with its own API/tool runtime and its own cloudflared tunnel lifecycle for `https://ai.sunshineclimatesolutions.com`.

## Control Center V2
The desktop Control Center presents four product cards. Every card exposes `Launch`, `Stop`, `Open`, `Logs`, state, health, and product-specific details through the existing `ProductService` boundary.

### DEFEND AI card
Launches the existing DEFEND stack through the existing controller. Existing mode/backend controls remain DEFEND-AI-specific rather than applying globally.

### DEFEND Sports card
Launches only Sports-owned services. Initial owned service is `sports:api`; later worker/web processes can be added without changing the product boundary. The card reports PostgreSQL health, API state, and feed/source health.

### DEFENDcoder card
Launch means: attach to a healthy existing coder endpoint when policy permits; otherwise provision/start an approved coder runtime, then expose the dedicated DEFENDcoder web application. The card reports alias, model, provider, GPU, context, instance/session state, endpoint health, and measured cost information when available.

### SCS AI card
Launches the SCS AI API/tool runtime and starts only its own `TunnelController`. The SCS tunnel is independent from DEFEND tunnels and must never stop or mutate another cloudflared process.

## DEFENDcoder authentication
V1 uses one PostgreSQL-backed authentication system for both roles.

- Roles: `admin`, `consumer`.
- Passwords are stored only as modern password hashes; plaintext passwords are never persisted or logged.
- Authentication creates server-side sessions using an opaque secure cookie.
- Session records are revocable and expire server-side.
- Login, logout, and current-session endpoints never expose password hashes or secrets.
- Admin and consumer share the same auth mechanism; authorization is role-based after authentication.
- V1 UI has separate Admin Login and Consumer Login panels, but both submit into the same auth service.

## Approved DEFENDcoder login design
The approved composition is the user-supplied cyber/server-room background with the U.S. map and American-flag shield, using the approved `DE★FENDcoder` branding treatment. The login page must preserve the approved composition rather than regenerate or reinterpret it.

UI behavior:
- Full-viewport background image with responsive `cover` behavior.
- Accessible dark overlay where needed for contrast without obscuring the approved artwork.
- Two login forms positioned over the artwork: Admin Login and Consumer Login.
- No crown above Admin Login.
- American-flag shield is the product symbol above/adjacent to DEFENDcoder branding.
- Admin action uses the approved red accent; Consumer uses the approved blue accent.
- Invalid login responses are generic and do not reveal whether an account exists.
- Keyboard navigation, visible focus states, autocomplete attributes, and password-manager compatibility are required.

## DEFENDcoder application shell after login
The first production shell is intentionally focused rather than cloning a full IDE.

### Shared layout
- Left: projects/workspaces/repository navigation.
- Center: coding-agent conversation and execution timeline.
- Bottom/secondary tabs: Terminal, Tests, Diff, Logs.
- Right/status area: current model alias, endpoint health, provider/GPU, context, session cost/credits where available.
- Top actions: new workspace, clone/open repository, run tests, review changes, commit.

### Consumer role
Can create/open owned workspaces, run coding sessions, use permitted tools, review diffs, run tests, and commit within authorized repositories. Consumer users cannot alter platform-wide provider credentials, billing policy, model registry, or other users.

### Admin role
Uses the same coding workspace plus an admin surface. V1 admin requirements are deliberately small: view system/model/runtime health, user/session counts, and product status. Full billing/user/provider administration remains a later increment.

## General-purpose workspace model
DEFENDcoder must not hard-code DEFEND repository assumptions.

A workspace belongs to an account and points to one authorized project source: a local/project path managed by the service, a cloned Git repository, or a newly initialized project. Tool calls resolve inside the selected workspace root, and path traversal outside that root is denied by default.

Future public-user isolation must be compatible with per-user sandbox/container execution; V1 interfaces must not prevent that migration.

## Coder model/runtime contract
The production configuration must reflect a runtime that has actually been proven, not stale smoke assumptions.

Proven live baseline as of 2026-08-15:
- Model: `Qwen/Qwen3-Coder-30B-A3B-Instruct`
- Logical revision remains pinned by the DEFENDcoder registry.
- Precision: BF16.
- Hardware proven live: NVIDIA H100 NVL (~95.8 GiB VRAM).
- vLLM proven live: `0.27.1`.
- Tool parser proven live: `qwen3_xml` with automatic tool choice enabled.
- First stable context: 8192 tokens.

The repository deployment profile should be amended to match the proven runtime before Control Center V2 claims the configuration is production-ready. Context expansion to 16K/32K is a separate measured validation, not part of this UI/auth increment.

## SCS AI launch contract
SCS AI uses its independent `TunnelController`. Control Center must compose/start the SCS API/tool runtime and its SCS-owned tunnel together, report both states, and stop only those owned processes. The external route is `https://ai.sunshineclimatesolutions.com`.

## Data and security
- PostgreSQL is the source of truth for DEFENDcoder accounts, password hashes, sessions, workspace metadata, and later billing/usage records.
- Secrets stay in protected secret stores/environment injection and never enter browser bundles, CLI arguments where avoidable, logs, trace JSON, or Git.
- The browser never receives Vast/HF/vLLM provider credentials.
- vLLM remains behind the application/backend boundary; public clients authenticate to DEFENDcoder, not directly to vLLM.
- CSRF protection is required for state-changing cookie-authenticated browser endpoints.
- Auth endpoints are rate-limited and audited without logging passwords.

## Testing and acceptance
The increment is accepted when:
1. Control Center shows exactly four product cards and each card operates only its owned services.
2. SCS AI launch/stop controls only its own tunnel/runtime.
3. DEFENDcoder opens directly to the approved login page when unauthenticated.
4. PostgreSQL-backed Admin and Consumer accounts can authenticate and receive revocable server-side sessions.
5. Role checks prevent consumer access to admin endpoints.
6. An authenticated consumer can enter the DEFENDcoder application shell and select/open a workspace.
7. DEFENDcoder can target an arbitrary test repository without DEFEND-specific assumptions.
8. The Coder card reports real endpoint/model/GPU/context state and never fabricates cost fields.
9. Relevant unit/integration suites and the broad regression suite remain green.

## Deferred from this increment
- Stripe checkout/real billing implementation.
- Full admin billing/provider console.
- Heavy/AUTO/MAXIMUM routing UI beyond displaying supported aliases/status.
- 16K/32K context promotion.
- Public multi-tenant container orchestration at scale.
- Sports arb/prediction feature work and additional SCS Office/business tools, except where needed to preserve integration compatibility.
