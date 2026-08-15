# DEFENDcoder UI + Control Center V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the production DEFENDcoder login/workspace shell with PostgreSQL auth and integrate DEFEND AI, DEFEND Sports, DEFENDcoder, and SCS AI into one operational Control Center.

**Architecture:** Keep the four products isolated behind `ProductService`. DEFENDcoder gets an independent FastAPI service plus Next.js UI; browser clients authenticate to the DEFENDcoder service, which owns sessions/workspaces and talks to model/runtime adapters rather than directly exposing vLLM. SCS AI keeps a separate tunnel lifecycle composed into its product card.

**Tech Stack:** Python 3.12, FastAPI, PostgreSQL/psycopg, Argon2id-compatible password hashing library already approved for project dependencies (or `argon2-cffi` if absent), server-side opaque sessions, Next.js/TypeScript frontend, existing DEFEND process supervisor/Control Center, pytest, existing frontend test runner.

## Global Constraints

- Preserve existing DEFEND AI, Sports, SCS, and Coder behavior outside this integration.
- No secrets in source, browser bundles, logs, tests, trace JSON, or CLI arguments where avoidable.
- PostgreSQL is the DEFENDcoder auth/workspace source of truth.
- Consumer and admin share one auth system with role-based authorization.
- Public users must never connect directly to vLLM/provider APIs.
- DEFENDcoder workspaces must be repo-agnostic and enforce workspace-root containment.
- SCS AI starts/stops only its own cloudflared process.
- Coder runtime metadata must reflect the proven live baseline: vLLM 0.27.1, `qwen3_xml`, BF16, 8192 first-stable context, H100 NVL proven live.
- No Stripe implementation in this increment.
- Approved login artwork must be used unchanged as the page background asset.

---

### Task 1: Integration branch and accepted-tip merge

**Files:**
- Branch: `platform/control-center-v2-integrate`
- No source edits until merge conflicts are resolved and baseline tests pass.

**Interfaces:**
- Consumes: `sports/ds0-task7`, `defendcoder/runtime-v1`, `scs/ai-foundation-v1`.
- Produces: one branch containing all accepted product foundations.

- [ ] **Step 1: Create isolated worktree for the integration branch**

```powershell
cd C:\Users\thoma\Documents\Codex\DEFEND
git fetch origin
git worktree add .worktrees\control-center-v2-integrate platform/control-center-v2-integrate
cd .worktrees\control-center-v2-integrate
```

- [ ] **Step 2: Merge Coder runtime**

```powershell
git merge --no-ff origin/defendcoder/runtime-v1 -m "merge: integrate DEFENDcoder runtime v1"
```

Resolve conflicts by preserving the four-product `ProductService` surface and the newer coder runtime/observation logic; never discard either product-card or coder-runtime functionality.

- [ ] **Step 3: Merge SCS AI foundation**

```powershell
git merge --no-ff origin/scs/ai-foundation-v1 -m "merge: integrate SCS AI foundation"
```

Preserve `scs_ai.TunnelController` ownership boundaries.

- [ ] **Step 4: Run baseline regression**

```powershell
C:\Users\thoma\Documents\Codex\DEFEND\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --basetemp=C:\Users\thoma\AppData\Local\Temp\control-center-v2-baseline
```

Expected: no failures after conflict resolution.

- [ ] **Step 5: Push the merge checkpoint**

```powershell
git push -u origin platform/control-center-v2-integrate
```

---

### Task 2: Record proven DEFENDcoder deployment runtime

**Files:**
- Modify: `defend_control/coder_deployment.py`
- Modify: `tests/test_coder_deployment.py`

**Interfaces:**
- Consumes: `CoderDeploymentArtifact` and deployment registry.
- Produces: default artifact metadata matching the proven live runtime.

- [ ] **Step 1: Write failing tests for the proven runtime**

Add assertions that the default artifact uses:

```python
assert artifact.minimum_vllm_version == "0.27.1"
assert artifact.image_tag == "v0.27.1"
assert artifact.tool_call_parser == "qwen3_xml"
assert artifact.enable_auto_tool_choice is True
assert artifact.max_model_len == 8192
assert artifact.required_min_gpu_ram_mb == 81_920
```

- [ ] **Step 2: Run the deployment tests and observe the old-runtime failure**

```powershell
C:\Users\thoma\Documents\Codex\DEFEND\.venv\Scripts\python.exe -m pytest tests/test_coder_deployment.py -q -p no:cacheprovider --basetemp=C:\Users\thoma\AppData\Local\Temp\coder-runtime-contract-red
```

- [ ] **Step 3: Update only the default deployment artifact**

Set vLLM runtime metadata to `0.27.1` / `v0.27.1`, parser to `qwen3_xml`, auto tool choice true, BF16 and 8192 unchanged. Do not alter Heavy in this task.

- [ ] **Step 4: Re-run tests**

```powershell
C:\Users\thoma\Documents\Codex\DEFEND\.venv\Scripts\python.exe -m pytest tests/test_coder_deployment.py tests/test_coder_control_plane.py tests/test_coder_m0_1_vast.py -q -p no:cacheprovider --basetemp=C:\Users\thoma\AppData\Local\Temp\coder-runtime-contract-green
```

- [ ] **Step 5: Commit**

```powershell
git add defend_control/coder_deployment.py tests/test_coder_deployment.py
git commit -m "fix(coder): record proven default runtime"
```

---

### Task 3: DEFENDcoder PostgreSQL schema and repository

**Files:**
- Create: `defend_coder/__init__.py`
- Create: `defend_coder/db.py`
- Create: `defend_coder/repositories.py`
- Create: `tests/test_defend_coder_db.py`

**Interfaces:**
- Produces: `CoderDatabase`, `CoderRepository`, schema version 1.
- Tables: `coder_accounts`, `coder_sessions`, `coder_workspaces`, `coder_audit_events`.

- [ ] **Step 1: Write failing PostgreSQL tests**

Tests must assert:

```python
# account roles are constrained
assert role in {"admin", "consumer"}
# usernames/emails are unique
# sessions store only a hash of the opaque session token
# sessions have expires_at/revoked_at
# workspace owner FK is required
# audit events never contain password/password_hash columns
```

- [ ] **Step 2: Run red test**

```powershell
C:\Users\thoma\Documents\Codex\DEFEND\.venv\Scripts\python.exe -m pytest tests/test_defend_coder_db.py -q -p no:cacheprovider --basetemp=C:\Users\thoma\AppData\Local\Temp\coder-db-red
```

- [ ] **Step 3: Implement schema/migration**

`CoderDatabase.migrate()` must be idempotent and transactional. `CoderRepository` provides account/session/workspace CRUD needed by Tasks 4-6; no HTTP concerns belong in this file.

- [ ] **Step 4: Run green test**

Use `CODER_TEST_DATABASE_URL`; skip integration only when it is genuinely unset.

- [ ] **Step 5: Commit**

```powershell
git add defend_coder tests/test_defend_coder_db.py
git commit -m "feat(coder): add PostgreSQL account and workspace foundation"
```

---

### Task 4: Unified Admin/Consumer authentication service

**Files:**
- Create: `defend_coder/auth.py`
- Create: `tests/test_defend_coder_auth.py`

**Interfaces:**
- Produces: `AuthService`, `AuthenticatedAccount`, `SessionToken`.
- Consumes: `CoderRepository`.

- [ ] **Step 1: Write failing auth tests**

Tests cover:
- password hash/verify round trip;
- plaintext never returned/stored;
- same login path accepts either role but role checks remain enforceable;
- wrong username and wrong password return the same public error;
- opaque random session token is returned once, only token hash stored;
- revoked/expired session is rejected.

- [ ] **Step 2: Run red tests**

```powershell
C:\Users\thoma\Documents\Codex\DEFEND\.venv\Scripts\python.exe -m pytest tests/test_defend_coder_auth.py -q -p no:cacheprovider --basetemp=C:\Users\thoma\AppData\Local\Temp\coder-auth-red
```

- [ ] **Step 3: Implement `AuthService`**

Use Argon2id password hashes and `secrets.token_urlsafe(32)` session tokens. Hash session tokens with SHA-256 before persistence. Never log raw credentials or raw session tokens.

- [ ] **Step 4: Run green tests**

- [ ] **Step 5: Commit**

```powershell
git add defend_coder/auth.py tests/test_defend_coder_auth.py
git commit -m "feat(coder): add role-based PostgreSQL authentication"
```

---

### Task 5: DEFENDcoder FastAPI application

**Files:**
- Create: `defend_coder/app.py`
- Create: `defend_coder/config.py`
- Create: `tools/defend_coder_server.py`
- Create: `tests/test_defend_coder_app.py`

**Interfaces:**
- Produces: `build_coder_app(settings, db, auth, runtime_status)`.
- Routes:
  - `GET /health`
  - `POST /v1/auth/login`
  - `POST /v1/auth/logout`
  - `GET /v1/auth/session`
  - `GET /v1/workspaces`
  - `POST /v1/workspaces`
  - `GET /v1/admin/status` (admin only)

- [ ] **Step 1: Write failing API tests**

Assert secure cookie properties, generic login failures, consumer/admin authorization, no secrets in `/health` or admin status, and CSRF rejection for state-changing cookie-authenticated requests.

- [ ] **Step 2: Run red tests**

- [ ] **Step 3: Implement API factory and entrypoint**

Server binds locally; public exposure happens only through the product/tunnel layer. Cookie name: `defendcoder_session`; `HttpOnly`, `SameSite=Lax`, `Secure` when public HTTPS mode is enabled.

- [ ] **Step 4: Run green tests**

- [ ] **Step 5: Commit**

```powershell
git add defend_coder tools/defend_coder_server.py tests/test_defend_coder_app.py
git commit -m "feat(coder): add authenticated DEFENDcoder API"
```

---

### Task 6: Approved DEFENDcoder login UI

**Files:**
- Create: `defendcoder-ui/package.json`
- Create: `defendcoder-ui/app/layout.tsx`
- Create: `defendcoder-ui/app/page.tsx`
- Create: `defendcoder-ui/app/globals.css`
- Create: `defendcoder-ui/components/LoginPortal.tsx`
- Create: `defendcoder-ui/components/LoginPortal.test.tsx`
- Add binary asset: `defendcoder-ui/public/defendcoder-login-bg.png`

**Interfaces:**
- Consumes: `POST /v1/auth/login`, `GET /v1/auth/session`.
- Produces: unauthenticated login portal and redirect into `/workspace` after successful login.

- [ ] **Step 1: Copy the approved image exactly**

Use the user-approved image supplied in the conversation; do not regenerate, crop, recolor, or change its lettering. Save it as `defendcoder-ui/public/defendcoder-login-bg.png`.

- [ ] **Step 2: Write failing component tests**

Tests assert both `Admin Login` and `Consumer Login`, password fields, no crown element, form keyboard accessibility, role submitted with login, and generic error rendering.

- [ ] **Step 3: Implement the page**

Use the approved image as a full-screen CSS background. Forms are real HTML forms layered over the approved artwork; keep extra UI minimal so the artwork remains the visual authority.

- [ ] **Step 4: Run frontend tests/build**

```powershell
cd defendcoder-ui
npm ci
npm test -- --runInBand
npm run build
cd ..
```

- [ ] **Step 5: Commit**

```powershell
git add defendcoder-ui
git commit -m "feat(coder-ui): add approved admin and consumer login"
```

---

### Task 7: DEFENDcoder authenticated workspace shell

**Files:**
- Create: `defendcoder-ui/app/workspace/page.tsx`
- Create: `defendcoder-ui/components/WorkspaceShell.tsx`
- Create: `defendcoder-ui/components/WorkspaceShell.test.tsx`

**Interfaces:**
- Consumes: session/workspace APIs and later coder execution APIs.
- Produces: repo-agnostic shell with navigation and execution panes.

- [ ] **Step 1: Write failing shell tests**

Assert `Projects`, `Git Repos`, `Workspaces`, `Terminal`, `Tests`, `Diff`, `Logs`, model status, and role-specific Admin link visibility.

- [ ] **Step 2: Implement shell layout**

Do not fake model cost/status values. Unknown values render `—`/`Unavailable`.

- [ ] **Step 3: Build/test frontend**

- [ ] **Step 4: Commit**

```powershell
git add defendcoder-ui
git commit -m "feat(coder-ui): add authenticated workspace shell"
```

---

### Task 8: General-purpose workspace containment

**Files:**
- Create: `defend_coder/workspaces.py`
- Create: `tests/test_defend_coder_workspaces.py`

**Interfaces:**
- Produces: `WorkspaceService.resolve_owned_path(account_id, workspace_id, relative_path) -> Path`.

- [ ] **Step 1: Write traversal/ownership tests**

Reject `..`, absolute paths, alternate-drive escapes on Windows, symlink/junction escapes, and workspaces owned by another account.

- [ ] **Step 2: Implement containment**

Resolve against the configured workspace root and require the resolved target to remain under that root.

- [ ] **Step 3: Run tests and commit**

```powershell
git add defend_coder/workspaces.py tests/test_defend_coder_workspaces.py
git commit -m "feat(coder): enforce general-purpose workspace isolation"
```

---

### Task 9: Real DEFENDcoder ProductService

**Files:**
- Modify: `defend_control/products.py`
- Modify: `tools/defend_control_center.py`
- Create/modify tests covering Coder product lifecycle.

**Interfaces:**
- Replaces observation-only `CoderService` with lifecycle-aware service while preserving `ProductService`.
- Consumes: coder API process supervisor + coder control plane/runtime status.

- [ ] **Step 1: Write lifecycle tests**

Cover attach-to-existing healthy endpoint, start local coder API/UI, truthful status, stop only owned local services, and no fabricated provider/cost metadata.

- [ ] **Step 2: Implement lifecycle**

`Open` launches the dedicated DEFENDcoder URL/UI. Provisioning remains policy-controlled and does not silently buy a replacement instance after a failed approved plan.

- [ ] **Step 3: Run product/control tests**

- [ ] **Step 4: Commit**

```powershell
git add defend_control/products.py tools/defend_control_center.py tests
git commit -m "feat(control): wire operational DEFENDcoder product card"
```

---

### Task 10: Operational SCS AI ProductService with independent tunnel

**Files:**
- Modify: `defend_control/products.py`
- Modify: `tools/defend_control_center.py`
- Modify only if required: `scs_ai/runtime.py`
- Test: SCS product/tunnel ownership tests.

**Interfaces:**
- Consumes: `scs_ai.runtime`, `TunnelController`.
- Produces: real SCS AI start/stop/status/open/log behavior.

- [ ] **Step 1: Write tests proving ownership isolation**

Assert SCS Launch starts SCS API + its tunnel; SCS Stop stops only those objects; no global `cloudflared` kill/query; DEFEND tunnel mocks remain untouched.

- [ ] **Step 2: Implement composition**

Open URL: `https://ai.sunshineclimatesolutions.com`.

- [ ] **Step 3: Run SCS/control tests and commit**

```powershell
git add defend_control scs_ai tools/defend_control_center.py tests
git commit -m "feat(control): wire SCS AI runtime and owned tunnel"
```

---

### Task 11: Four-product Control Center polish and acceptance

**Files:**
- Modify: `defend_control/ui.py`
- Modify: `defend_control/products.py`
- Modify: `tools/defend_control_center.py`
- Tests: Control Center/product integration suites.

**Interfaces:**
- Produces exactly four independently operable cards: DEFEND AI, DEFEND Sports, DEFENDcoder, SCS AI.

- [ ] **Step 1: Write final card contract tests**

Assert four unique application IDs, correct URLs, correct ownership boundaries, and stable `Launch/Stop/Open/Logs` actions.

- [ ] **Step 2: Implement final UI state presentation**

Keep DEFEND-specific backend controls labeled as DEFEND AI identity/model controls; do not make them global settings for all four products.

- [ ] **Step 3: Run focused regression**

```powershell
C:\Users\thoma\Documents\Codex\DEFEND\.venv\Scripts\python.exe -m pytest tests -k "control or products or sports or coder or scs" -q -p no:cacheprovider --basetemp=C:\Users\thoma\AppData\Local\Temp\control-center-v2-focused
```

- [ ] **Step 4: Run full Python suite**

```powershell
C:\Users\thoma\Documents\Codex\DEFEND\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --basetemp=C:\Users\thoma\AppData\Local\Temp\control-center-v2-full
```

- [ ] **Step 5: Run frontend build/tests and manual smoke**

Manual smoke sequence:
1. Control Center opens.
2. Four cards are visible.
3. DEFEND Sports starts/stops without touching other products.
4. SCS AI starts its API/tunnel and opens its public origin.
5. DEFENDcoder opens approved login when unauthenticated.
6. Admin and consumer logins both work against PostgreSQL.
7. Consumer reaches workspace shell; admin reaches shell with admin navigation.
8. Coder status reports real runtime state.

- [ ] **Step 6: Commit final integration checkpoint**

```powershell
git add defend_control tools defend_coder defendcoder-ui scs_ai tests docs
git commit -m "feat(platform): complete four-product Control Center v2"
git push
```
