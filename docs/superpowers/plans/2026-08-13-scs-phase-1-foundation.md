# SCS Phase 1 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver an isolated, invitation-only SCS employee operations application with identity, authorization, customers, sites, equipment, memberships, jobs, visits, assignments, audit, CSV preview, and a branded mobile-friendly workspace.

**Architecture:** `scs_data` owns SCS-only SQLite stores and domain services below an explicit Phase 0 `ApplicationContext`; it may reuse pure security/SQLite helpers but never DEFEND composition roots or stores. `scs_api` is a separate FastAPI application on port 8100, and `scs-ui` is a separate Next.js application on port 3100. Every protected service accepts an authenticated SCS principal and enforces permissions/assignment scope before reading or mutating records.

**Tech Stack:** Python 3.14, SQLite/WAL, FastAPI/Pydantic, pytest, Next.js 16, React 19, TypeScript, Vitest/Testing Library.

## Global Constraints

- SCS uses only `C:\SCS_DATA`, `SCS_*`, `scs_employee_session`, API 8100, web 3100, and `https://ai.sunshineclimatesolutions.com`.
- No SCS module imports `defend_data.DataCore`, DEFEND identity/API routers, DEFEND registry, or DEFEND frontend components.
- Customer registration and customer login do not exist.
- Raw passwords, invitation tokens, and session tokens are never persisted or logged.
- Ordinary employees see assigned jobs only unless an explicit permission grants broader scope.
- Technician level is visible/changeable only to owner, operations admin, service manager, and installation manager.
- Financial metrics without invoice/payment events return `{"state":"not_available","value":null}`.
- CSV import is preview-only and makes zero operational writes.
- Each schema change is versioned, transactional, idempotent, and tested from an empty database.
- Existing DEFEND behavior and all DEFEND verification suites remain green.

---

### Task 1: SCS paths, schema migration, composition root, and backup boundary

**Files:**
- Create: `scs_data/__init__.py`
- Create: `scs_data/config.py`
- Create: `scs_data/migrations.py`
- Create: `scs_data/core.py`
- Create: `tests/test_scs_data_core.py`

**Interfaces:**
- Produces: `ScsPaths.from_context(context)`, `ScsMigrator(conn).apply()`, `ScsDataCore(context)`, `ScsDataCore.health()`, `ScsDataCore.backup_manifest()`.

- [ ] Write failing tests proving only an `scs` context is accepted; paths remain under `C:\SCS_DATA`; construction creates only SCS directories/database; migrations record version 1 exactly once; health omits private paths outside the root; backup manifests identify application `scs` and reject DEFEND destinations.
- [ ] Run `python -m pytest tests/test_scs_data_core.py -q` and verify RED because `scs_data` is missing.
- [ ] Implement immutable paths (`db`, `uploads`, `exports`, `backups`, `tmp`, `logs`) and one SQLite database at `db/scs.sqlite3`; use the existing pure `connect_sqlite` helper and a `scs_schema_migrations(version, applied_at)` table.
- [ ] Implement a minimal `ScsDataCore` that applies migrations, exposes stores added by later tasks through explicit attributes, returns bounded health, and closes connections idempotently.
- [ ] Run focused tests and commit `Add isolated SCS data composition root`.

### Task 2: Employees, multi-role authorization, functions, qualifications, and audit

**Files:**
- Create: `scs_data/audit.py`
- Create: `scs_data/identity.py`
- Create: `scs_data/authorization.py`
- Test: `tests/test_scs_identity.py`
- Test: `tests/test_scs_authorization.py`

**Interfaces:**
- Produces: `ScsPrincipal`, `ScsIdentityStore.bootstrap_owner(...)`, `invite_employee(...)`, `activate_invitation(...)`, `authenticate(...)`, `create_session(...)`, `resolve_session(...)`, `revoke_session(...)`, `set_roles(...)`, `assign_function(...)`, `set_technician_level(...)`, `ScsAuthorizer.require(principal, permission)`.

- [ ] Write failing tests for single idempotent owner bootstrap, invitation-only employees, multi-role assignment, owner-only operations-admin changes, hashed invitations/sessions, expiration/revocation, append-only role/function/qualification history, and secret-safe audit payload rejection.
- [ ] Write failing authorization tests mapping roles/functions to explicit permissions and proving technician level visibility/mutation is limited to the approved four manager classes.
- [ ] Run focused tests and verify RED.
- [ ] Implement normalized employee/account tables, role memberships, function histories, qualification histories, invitations, sessions, and audit events. Reuse only pure `hash_password`, `verify_password`, `new_token`, `token_hash`, and `normalize_email` helpers.
- [ ] Implement permission constants and a deny-by-default authorizer; function-derived technician-level permission applies only to currently effective service/install manager assignments.
- [ ] Run focused tests and commit `Add SCS employee identity and authorization`.

### Task 3: Invitation mail boundary and SCS authentication API

**Files:**
- Create: `scs_data/mailer.py`
- Create: `scs_api/__init__.py`
- Create: `scs_api/app.py`
- Create: `scs_api/auth_routes.py`
- Create: `tests/test_scs_auth_api.py`

**Interfaces:**
- Produces: `build_scs_app(context, data, mailer) -> FastAPI`; fixed routes `/api/scs/auth/login`, `/logout`, `/session`, `/activate`, and manager invitation/retry/revoke routes.

- [ ] Write failing API tests proving no registration route exists; cookies use `scs_employee_session`, Secure, HttpOnly, SameSite=Lax, path `/`; DEFEND cookies never authenticate; invitation URLs put tokens in fragments; mail failure retains retry state and authorized manual-copy token regeneration.
- [ ] Run focused tests and verify RED.
- [ ] Implement an SCS-specific SMTP configuration using only `SCS_GMAIL_*`, bounded messages, safe delivery results, and no credential representation.
- [ ] Implement the separate FastAPI composition root and authentication dependencies with generic login failures, bounded throttling, and safe correlation IDs.
- [ ] Run focused tests and commit `Add SCS invitation and authentication API`.

### Task 4: Customers, contacts, sites, equipment, and service authorization

**Files:**
- Create: `scs_data/customers.py`
- Create: `scs_api/customer_routes.py`
- Test: `tests/test_scs_customers.py`
- Test: `tests/test_scs_customer_api.py`

**Interfaces:**
- Produces CRUD/archive methods for `Customer`, `Contact`, `Site`, `Equipment`; opaque IDs prefixed `scs_cus_`, `scs_con_`, `scs_site_`, `scs_eq_`.

- [ ] Write failing store tests for multiple contacts/sites, distinct billing/service addresses, customer/site/equipment ownership constraints, archive instead of destructive delete, bounded search, provenance, equipment history, and cross-customer link rejection.
- [ ] Write failing API tests for permission checks, field validation, secret-safe errors, and audit events for mutations/sensitive reads.
- [ ] Run focused tests and verify RED.
- [ ] Implement normalized tables and transactional service methods; every child lookup includes its owning customer/site constraint.
- [ ] Implement fixed `/api/scs/customers`, contacts, sites, and equipment routes with explicit Pydantic request/response types.
- [ ] Run focused tests and commit `Add SCS customer and equipment records`.

### Task 5: Membership plans and enrollment history

**Files:**
- Create: `scs_data/memberships.py`
- Create: `scs_api/membership_routes.py`
- Test: `tests/test_scs_memberships.py`

**Interfaces:**
- Produces: seeded plan code `maintenance-member`; versioned plan records; enrollment states `active|paused|expired|cancelled`.

- [ ] Write failing tests proving migration seeds exactly one Maintenance Member version, plan revisions never rewrite history, enrollments reference a version, coverage belongs to the same customer, invalid date/state transitions fail, and every change is audited.
- [ ] Run focused tests and verify RED.
- [ ] Implement effective-dated plan/version and append-only enrollment event tables plus permissioned routes.
- [ ] Run focused tests and commit `Add SCS membership plans and enrollments`.

### Task 6: Jobs, visits, assignments, notes, classifications, and scope

**Files:**
- Create: `scs_data/jobs.py`
- Create: `scs_api/job_routes.py`
- Test: `tests/test_scs_jobs.py`
- Test: `tests/test_scs_job_scope_api.py`

**Interfaces:**
- Produces approved job types, durable status events, visits, assignments, visibility-classified notes, controlled classification events, and `visible_jobs(principal)`.

- [ ] Write failing tests for all nine job types, customer/site ownership, append-only statuses, multiple visits/assignments, effective assignment scope, manager/permission expansion, note visibility, and auditing.
- [ ] Write failing classification tests proving TAB-only jobs reject `potential-member`, only one age bucket exists, confirmed dates produce 0-3/4-7/8-plus relative to job date, and missing/unconfirmed dates produce no age tag.
- [ ] Run focused tests and verify RED.
- [ ] Implement normalized jobs, events, visits, assignments, notes, and classification tables with service-layer scope predicates reused by list/detail/mutation routes.
- [ ] Run focused tests and commit `Add SCS job operations and visibility`.

### Task 7: Customer summary and CSV preview

**Files:**
- Create: `scs_data/customer_summary.py`
- Create: `scs_data/import_preview.py`
- Create: `scs_api/import_routes.py`
- Test: `tests/test_scs_customer_summary.py`
- Test: `tests/test_scs_import_preview.py`

**Interfaces:**
- Produces: `CustomerSummary`, `MetricValue(state, value)`, and `preview_customer_csv(data, mapping, store) -> ImportPreview`.

- [ ] Write failing summary tests for authoritative job/site/equipment/membership counts and explicit unavailable financial/payment metrics.
- [ ] Write failing CSV tests for UTF-8 only, 5 MiB/5,000-row/100-column/cell limits, duplicate headers, formula-like content neutralization, advisory normalized matching, rejected rows, expiry metadata, and zero writes.
- [ ] Run focused tests and verify RED.
- [ ] Implement deterministic SQL summaries and a pure bounded `csv` parser whose preview output contains creates/matches/conflicts/rejections only.
- [ ] Add permissioned preview route with no commit endpoint.
- [ ] Run focused tests and commit `Add SCS customer summaries and CSV preview`.

### Task 8: Branded SCS login and mobile employee workspace

**Files:**
- Create: `scs-ui/package.json`, `scs-ui/next.config.mjs`, `scs-ui/tsconfig.json`
- Create: `scs-ui/app/layout.tsx`, `scs-ui/app/page.tsx`, `scs-ui/app/globals.css`
- Create: `scs-ui/lib/api.ts`
- Create: `scs-ui/components/Login.tsx`, `Workspace.tsx`, `CustomerWorkspace.tsx`, `JobWorkspace.tsx`, `EmployeeAdmin.tsx`
- Test: `scs-ui/components/__tests__/Login.test.tsx`, `Workspace.test.tsx`

**Interfaces:**
- Consumes fixed `/api/scs/*` routes and cookie session; produces employee-only UI on port 3100.

- [ ] Write failing component tests proving logged-out users see only Sunshine Climate Solutions login, authenticated navigation respects permissions, assigned jobs render on narrow/mobile view, technician levels remain absent without permission, and unavailable financial metrics display `Not available`.
- [ ] Run focused Vitest tests and verify RED.
- [ ] Implement a distinct SCS visual identity, accessible login, responsive navigation, customer/site search, assigned jobs, job/visit detail, and permissioned employee administration without importing DEFEND UI modules.
- [ ] Run frontend tests and production build; commit `Add SCS employee operations workspace`.

### Task 9: Control Center profile, isolation acceptance, documentation, and release

**Files:**
- Modify: `shared_platform/phase0.py`
- Create: `tests/test_scs_phase1_isolation.py`
- Modify: `docs/operations/DEFEND-Control-Center.md`
- Modify: `docs/superpowers/specs/2026-08-13-scs-phase-1-foundation-design.md`

**Interfaces:**
- Produces a validated but explicit SCS API/web process profile; public-route activation remains separately gated.

- [ ] Write failing acceptance tests proving SCS processes receive only SCS environment/secret names, use ports 8100/3100, cannot open DEFEND roots/databases/cookies, and backup/restore manifests reject the other application.
- [ ] Implement non-billable local SCS process specifications and health checks; do not activate Cloudflare or Vast resources.
- [ ] Document owner bootstrap, invitations, backup/restore, port/service ownership, Phase 1 startup, and public activation checklist.
- [ ] Run all SCS tests, complete backend suite with isolated `--basetemp`, DEFEND and SCS frontend suites, and both production builds.
- [ ] Run `git diff --check`, secret-pattern scan, migration review, and clean-tree check.
- [ ] Commit `Complete SCS Phase 1 foundation`, push `agent/scs-phase1-foundation`, open a new PR, and report verification evidence.
