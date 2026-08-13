# SCS Phase 0 Platform Boundaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit shared-platform application boundaries that make DEFEND and SCS configuration, data, credentials, HTTP state, services, and public routes provably distinct without changing existing DEFEND runtime behavior.

**Architecture:** A new dependency-free `shared_platform` package defines immutable application contexts and validates a complete two-application deployment before either application is composed. Secret access is namespaced through an allowlisted view, while service and route profiles use application-qualified identities and reject port, origin, cookie, data-root, and environment-prefix collisions. Existing DEFEND composition remains untouched; later SCS phases must consume these explicit contexts and cannot infer a default application.

**Tech Stack:** Python 3.14, frozen dataclasses, pathlib, urllib parsing, pytest, existing DEFEND secret-store protocol.

## Global Constraints

- `ApplicationId` is exactly `defend` or `scs`; no implicit/default application is permitted.
- DEFEND and SCS must have distinct absolute data roots with no equality or ancestor/descendant overlap.
- Environment prefixes, secret namespaces, cookie names, API ports, web ports, public HTTPS origins, and service names must be distinct.
- DEFEND keeps `defend_account_session`; SCS uses `scs_employee_session`.
- DEFEND and SCS ordinary users, sessions, data, tools, RAG, uploads, audits, and backups remain isolated.
- Phase 0 performs no filesystem creation, provider mutation, billable action, network request, or SCS domain workflow.
- Existing DEFEND behavior and verification suites remain green.

---

### Task 1: Explicit application context

**Files:**
- Create: `shared_platform/__init__.py`
- Create: `shared_platform/application.py`
- Test: `tests/test_shared_application_context.py`

**Interfaces:**
- Produces: `ApplicationId`, `ApplicationContext`, and `validate_application_pair(defend, scs) -> tuple[ApplicationContext, ApplicationContext]`.
- `ApplicationContext` fields: `application_id`, `data_root`, `environment_prefix`, `secret_namespace`, `session_cookie`, `public_origin`, `api_port`, and `web_port`.

- [ ] **Step 1: Write failing tests** proving only `defend`/`scs` IDs are accepted, paths are absolute, origins are HTTPS origins without paths, ports are positive and different within one app, and the pair rejects equal/nested roots plus every cross-application namespace/cookie/origin/port collision.
- [ ] **Step 2: Run** `C:\Users\thoma\Documents\Codex\DEFEND\.venv\Scripts\python.exe -m pytest tests/test_shared_application_context.py -q` and verify collection fails because `shared_platform.application` is missing.
- [ ] **Step 3: Implement** frozen dataclasses and canonical comparisons using `Path.resolve(strict=False)`, `os.path.normcase`, and `urllib.parse.urlsplit`; return contexts ordered as `(defend, scs)` and reject missing/duplicate IDs.
- [ ] **Step 4: Run the focused test** and verify it passes.
- [ ] **Step 5: Commit** `Add explicit application contexts`.

### Task 2: Namespaced secret access

**Files:**
- Create: `shared_platform/secrets.py`
- Test: `tests/test_shared_secret_namespace.py`

**Interfaces:**
- Consumes: `ApplicationContext.secret_namespace`.
- Produces: `NamespacedSecrets(values: Mapping[str, str], context: ApplicationContext)` with `get(name)`, `require(*names)`, and `export(names)`; physical keys are `<NAMESPACE>_<NAME>` and returned mappings contain logical names only.

- [ ] **Step 1: Write failing tests** proving DEFEND cannot read `SCS_*`, SCS cannot read `DEFEND_*`, unknown/unprefixed names are rejected, required-name errors list logical names only, and `repr`/exceptions never contain values.
- [ ] **Step 2: Run** `C:\Users\thoma\Documents\Codex\DEFEND\.venv\Scripts\python.exe -m pytest tests/test_shared_secret_namespace.py -q` and verify RED because the module is missing.
- [ ] **Step 3: Implement** strict logical-name validation (`^[A-Z][A-Z0-9_]*$`), immutable copied storage, namespace-only lookup, secret-safe `repr`, and missing-name errors without values.
- [ ] **Step 4: Run the focused test** and verify GREEN.
- [ ] **Step 5: Commit** `Add isolated secret namespaces`.

### Task 3: Application-qualified service and route profiles

**Files:**
- Create: `shared_platform/services.py`
- Test: `tests/test_shared_service_profiles.py`

**Interfaces:**
- Consumes: a validated `ApplicationContext` pair.
- Produces: `ServiceProfile(application_id, role, service_name, port, health_path)`, `RouteProfile(application_id, public_origin, upstream_port)`, and `validate_deployment(contexts, services, routes)`.
- Service names must equal `<application_id>:<role>`; roles are `api`, `web`, `language`, `embedding`, `vision`, or `coding`.

- [ ] **Step 1: Write failing tests** for qualified service names, loopback port uniqueness, safe health paths, one exact route per app, origin/context agreement, upstream ownership, and rejection of a route pointing to the other app's port.
- [ ] **Step 2: Run** `C:\Users\thoma\Documents\Codex\DEFEND\.venv\Scripts\python.exe -m pytest tests/test_shared_service_profiles.py -q` and verify RED because the module is missing.
- [ ] **Step 3: Implement** immutable profiles and a pure validator with no process starts, file writes, DNS calls, or Cloudflare mutations.
- [ ] **Step 4: Run the focused test** and verify GREEN.
- [ ] **Step 5: Commit** `Add isolated application service profiles`.

### Task 4: Cross-application isolation contract and operations documentation

**Files:**
- Create: `tests/test_scs_phase0_isolation.py`
- Modify: `docs/operations/DEFEND-Control-Center.md`
- Modify: `docs/superpowers/specs/2026-08-13-scs-operations-platform-design.md`

**Interfaces:**
- Consumes: contexts, namespaced secrets, deployment validator.
- Produces: one executable Phase 0 contract fixture for later SCS composition roots.

- [ ] **Step 1: Write the failing integration test** constructing DEFEND (`C:\DEFEND_DATA`, `DEFEND`, `defend_account_session`, ports 8000/3000, `https://ai.defend-network.org`) and SCS (`C:\SCS_DATA`, `SCS`, `scs_employee_session`, ports 8100/3100, `https://ai.sunshineclimatesolutions.com`) contexts; assert distinct secret exports, roots, cookies, routes, qualified services, and rejection of deliberate cross-wiring.
- [ ] **Step 2: Run** `C:\Users\thoma\Documents\Codex\DEFEND\.venv\Scripts\python.exe -m pytest tests/test_scs_phase0_isolation.py -q` and verify RED until the complete contract is supported.
- [ ] **Step 3: Complete only the minimal shared-platform exports** required by the integration contract; do not connect SCS to DEFEND `DataCore`, identity, registry, or API.
- [ ] **Step 4: Document** the Phase 0 boundary, reserved ports/names, separate `C:\SCS_DATA`, separate backup/secret files, and that the SCS origin is not activated until Phase 1 health/auth exists. Record Phase 0 completion in the controlling spec without changing later-phase scope.
- [ ] **Step 5: Run** all Phase 0 tests together, then the complete backend suite with an isolated `--basetemp`, the complete frontend suite, and the Next.js production build.
- [ ] **Step 6: Run** `git diff --check`, a secret-pattern scan, and `git status --short`; inspect every changed file.
- [ ] **Step 7: Commit** `Establish SCS Phase 0 isolation contract`, push `agent/admin-permanent-rag`, and update PR #4 with verification evidence.
