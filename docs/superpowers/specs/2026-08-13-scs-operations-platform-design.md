Exit code: 0
Wall time: 0.6 seconds
Output:
# Sunshine Climate Solutions AI Operations Platform Design

## Purpose

Build an employee-only AI operations application for Sunshine Climate Solutions (SCS) at `https://ai.sunshineclimatesolutions.com`. It will organize customers and HVAC/TAB jobs, analyze field photographs and technician summaries, prepare estimates and invoices, retrieve manufacturer and industry information, and generate reviewable project workbooks from a protected master template library.

SCS and DEFEND are separate applications. They may share secure platform infrastructure, but never application data, ordinary user identities, sessions, tools, indexes, files, or audit records. The owner's identity is the only identity mapped into both applications.

## Architectural approach

Use a shared internal platform with isolated applications.

Shared platform capabilities include:

- Control Center process and model-service supervision;
- encrypted secret handling;
- common tool SDK and policy primitives;
- model client interfaces;
- deployment, health, logging, and backup primitives;
- reusable audit-event conventions.

SCS retains independent:

- domain, branded frontend, and API;
- authentication database, roles, sessions, and cookies;
- data root, uploads, databases, workbooks, and backups;
- tool registry and model prompts;
- RAG collections and structured catalogs;
- audit logs, retention rules, and release controls;
- application configuration and secrets.

Neither application imports or queries the other's application stores. Shared code receives an explicit application context and cannot infer a default tenant.

## Access and identity

`ai.sunshineclimatesolutions.com` opens directly to a branded login page. There is no anonymous/public chat mode and no customer portal in the first release.

Initial roles:

- `owner`: complete SCS administration and the only identity also authorized for DEFEND;
- `operations_admin`: employee and configuration administration except owner-only secrets and platform transitions;
- `estimator`: jobs, catalogs, estimates, and draft invoices;
- `technician`: assigned jobs, visits, photographs, readings, summaries, and draft reports;
- `reviewer`: report/workbook review and approval;
- `billing`: approved estimates, invoices, Stripe synchronization, and payment status;
- `read_only`: explicitly assigned non-sensitive records.

Permissions apply at API and service boundaries, not only in navigation. Sensitive pricing, customer details, originals, exports, and financial actions have separate permissions. Sessions use SCS-scoped cookies and signing material that cannot authenticate to DEFEND.

## Core domain

The `Job` is the central operational record:

```text
Customer
â””â”€â”€ Site
    â””â”€â”€ Job
        â”œâ”€â”€ Visits
        â”œâ”€â”€ Equipment
        â”œâ”€â”€ Photos and evidence
        â”œâ”€â”€ Field summaries
        â”œâ”€â”€ Measurements and readings
        â”œâ”€â”€ Estimates and catalog selections
        â”œâ”€â”€ Reports
        â”œâ”€â”€ Invoices and payment status
        â””â”€â”€ Workbook versions
```

Public identifiers are opaque UUID-derived values. Customer, site, job, equipment, visit, estimate, invoice, evidence, and workbook histories are durable records rather than overwritten current-state blobs.

## Field evidence workflow

1. An employee creates or opens a job and field visit.
2. They upload 50 or more photographs in resumable batches or through a mobile-friendly interface.
3. SCS preserves originals, hashes content, records uploader/time/job provenance, and creates safe derivatives.
4. The technician enters requested scope, work performed, reported conditions, findings, readings, recommendations, and unresolved questions.
5. A vision-language service classifies evidence and proposes typed facts.
6. Each proposal stores the model/prompt version, source photo, source region, raw output, normalized candidate value, unit, and calibrated confidence.
7. SCS compares repeated tags and readings across photographs and flags conflicts.
8. The review interface highlights the exact image region beside the candidate, confidence, unit, source photograph, and conflict state.
9. The operator confirms, edits, rejects, or marks the value unresolved. Every action records the operator, timestamp, original model output, and resulting confirmed fact.
10. Serial/model numbers, readings, safety observations, quantities, and estimate-driving facts always require confirmation.

Low-confidence, conflicting, or `not visible` results never block the employee. SCS preserves the gap, offers manual entry or another-photo requests, and prevents only dependent automation from being silently completed. Missing values are never invented.

Original photos and derivatives have separate access controls. Customer-facing exports remove location metadata and internal-only provenance. Retention policies are configurable by evidence class; legal hold suspends deletion. Jobs and files never cross customer boundaries.

## Workbook and template system

The workbook master is a versioned, read-only template library. Runtime workflows cannot edit it. Master changes occur only through a separate administrator-controlled template editor with validation, review, publication, and rollback.

For a project workbook:

1. Rules propose relevant TAB/HVAC report sheets based on confirmed job facts and requested deliverable.
2. An employee confirms the sheets and report type.
3. The workbook service creates a new project workbook named from an approved naming pattern.
4. It copies approved sheets and required dependencies from a pinned master version.
5. It writes only to declared input cells/ranges through a template mapping schema.
6. It preserves formulas, styles, number formats, named ranges, validation, conditional formatting, charts, print areas, page breaks, hidden support sheets, and protected calculation cells.
7. It recalculates through an approved calculation engine and scans for formula/reference errors.
8. It visually renders every generated sheet for automated and human review.
9. The employee reviews facts, formulas, totals, narrative, photographs, unresolved items, and print output.
10. Only an approved immutable version can be exported or sent.

Each workbook records job/customer IDs, master and mapping versions, selected sheets, source evidence, AI-proposed versus operator-confirmed fields, formula checks, revisions, reviewer, and approval time. The master is never overwritten.

## Estimating and catalogs

Structured, effective-dated tables are authoritative for prices and calculations. They contain manufacturers, models/SKUs, specifications, catalog/rate-book versions, effective intervals, costs, labor rates, assemblies, source documents/URLs, verification state, and update history.

For every job, resolution uses the version effective on the job/estimate date. The selected version is immutable on an approved estimate. Expired, overlapping, missing, or unverified versions visibly block automatic approval. The language model can retrieve and explain sources but is never authoritative for numeric values.

Visible business assumptions drive formulas:

- labor categories and rates;
- material and equipment costs;
- markups and margins;
- travel/trip charges;
- disposal and rentals;
- subcontractors;
- contingencies and discounts;
- jurisdictional tax rules.

The AI may propose assemblies, quantities, descriptions, exclusions, and alternatives from confirmed evidence. Deterministic code calculates money and taxes. An employee confirms quantities, scope, current pricing, and tax treatment before approval.

## Stripe invoicing

SCS is the source of job, estimate, approval, and invoice-draft intent. Stripe handles Stripe customers, hosted invoices/payment pages, delivery, and payment events.

Use `Powering an integration you built`, not an autonomous-agent authorization. Begin in Stripe Sandbox. Use separate restricted test/live keys stored only in the encrypted Control Center secret store. Keys never enter browsers, prompts, logs, workbooks, repositories, or employee-visible settings.

Grant least-privilege access only to required customers, products/prices if used, invoice items, invoices, and payment-status reads. Refunds, payouts, bank details, disputes, and broad payment creation remain unavailable unless a later approved workflow requires them.

Workflow:

```text
Approved SCS estimate
â†’ employee reviews invoice draft
â†’ backend synchronizes Stripe customer
â†’ backend creates draft invoice and items
â†’ authorized employee approves finalization
â†’ Stripe sends hosted invoice/payment page
â†’ verified webhook updates SCS payment status
```

Every Stripe write uses an operation-specific idempotency key. Webhooks verify the signature against the raw body, enforce timestamp tolerance, deduplicate event/object IDs, subscribe only to required events, acknowledge quickly, and process asynchronously. Separate permissions govern draft preparation and approval/send. Finalize, send, void, credit, and refund actions require explicit authorized confirmation and durable audit events.

SCS stores Stripe object IDs, request IDs, synchronized status, and event history, never card data.

## Model roles

- `scs-language`: narrative, scope/report drafting, tool orchestration, explanations, and employee assistance;
- `scs-vision`: photo OCR, equipment/readings/conditions extraction, classification, and grounding;
- `scs-embedding`: retrieval vectors for SCS knowledge;
- deterministic services: workbooks, estimating, taxes, permissions, files, Stripe, and state transitions.

The initial SCS language path uses the professionally evaluated primary Qwen family through an SCS-specific prompt/tool registry. An SCS adapter is considered only after SCS evaluation and correction data show prompting/RAG limitations.

Evaluate Qwen3-VL-8B-Instruct as the cost baseline and Qwen3-VL-32B-Instruct as the quality candidate. Promote based on SCS-specific accuracy, abstention, grounding, latency, VRAM, and cost rather than model size.

Retain Qwen3-Embedding-0.6B initially at 1024 dimensions. SCS and DEFEND use distinct index generations, storage paths, credentials, and queries. Changing embedding model/dimension creates a new generation and requires re-indexing.

## SCS evaluations and drift

`SCS-Vision-Eval` contains representative, permission-cleared cases covering clean/damaged tags, glare, low light, oblique angles, blur, analog/digital readings, handwriting, multiple tags, common HVAC/TAB components, unknown/not-visible cases, conflicts, and exact region grounding.

Metrics include exact identifiers, normalized values/units, reading tolerances, abstention, calibration, source-region grounding, conflict detection, latency, VRAM, and cost.

`SCS-Report-Eval` covers correct template/sheet selection, fact-to-cell mapping, narrative support, unresolved-value behavior, formula integrity, print output, estimate accuracy, and unauthorized action prevention.

Every model, prompt, schema, mapping, catalog, or template change reruns the applicable evaluation. Scheduled drift checks rerun a stable reference set and compare operator correction rates. Release thresholds and rollback artifacts are versioned.

Track vision latency and cost per photo/job. Routing policy may use a lighter OCR path or 8B vision model for suitable evidence, escalating difficult/critical cases to 32B. Operators see which service produced each candidate.

## Knowledge and data isolation

SCS collections include manufacturer manuals/catalogs, approved industry references, company procedures, rate books/assemblies, template documentation, and eligible prior approved reports. Structured tables, not RAG, are authoritative for pricing and exact business rules.

All ingestion enforces provenance, version, license/permission, effective date, confidentiality, and retention metadata. Customer records are not turned into general training or shared RAG data without explicit policy and de-identification review.

DEFEND cannot retrieve SCS documents, catalogs, photos, prompts, tools, or application data. SCS cannot retrieve DEFEND membership, screening, research, memory, or coding-workspace data.

## Control Center and deployment

The Control Center exposes applications and services separately:

```text
Applications
- DEFEND
- SCS Operations

Model services
- Primary language
- Embedding
- Vision
- Owner-only coding
```

It can start DEFEND, SCS, or both. It calculates expected VRAM/disk/ports before a transition, reports active Vast billing, and never silently unloads a service or creates a billable instance.

The recommended initial Vast topology uses localhost-only services and distinct credentials/tunnels. Embeddings may remain resident. Vision and coding are on demand and unload after a configurable idle period. If the chosen GPU/profile cannot safely host requested services, the owner chooses a visible transition or separate instance. SCS photo jobs queue durably while vision starts; public DEFEND chat and SCS credentials remain isolated.

## Security, auditing, and reliability

- Encrypt traffic and sensitive data at rest.
- Keep uploads outside public web assets and use authorized download endpoints.
- Apply rate, size, count, type, decompression, and malware controls.
- Redact secrets and sensitive values from logs and model traces.
- Record sensitive reads, exports, approvals, financial actions, employee changes, template publications, and model/service transitions.
- Use append-only audit events wherever practical.
- Provide encrypted backups with tested restore procedures and application-specific retention.
- Require MFA before production financial or owner-administration access.
- Preserve explicit human approval for safety-, money-, and customer-facing outputs.

## Delivery phases

### Phase 0: Shared-platform boundaries

Define application context, configuration, secret namespaces, independent data roots, service profiles, domain routing, and cross-application isolation tests without changing existing DEFEND behavior.

Phase 0 implementation status (2026-08-13): the repository contains an
additive, pure validation layer for explicit `defend` and `scs` application
contexts, namespaced secret views, application-qualified service profiles,
route ownership, reserved ports/origins/cookies, and cross-wiring rejection.
The reservation performs no filesystem creation, process start, provider
mutation, domain activation, or billing action. SCS remains inactive until the
separately reviewed Phase 1 composition root and employee authentication exist.

### Phase 1: SCS foundation

Branded login; owner/employee identities; customers, sites, jobs, visits, assignments, notes, permissions, and audit; mobile-friendly job capture.

### Phase 2: Evidence and vision pilot

Resumable photo uploads, original/derivative storage, typed candidate/confirmation workflow, Qwen3-VL evaluation harness, per-job cost/latency, and non-blocking abstention.

### Phase 3: Template/workbook pilot

Import one read-only master version; map a small approved sheet set; generate new project workbooks; recalculate, inspect, render, review, approve, and export. No master editing through job workflows.

### Phase 4: Catalog and estimating

Effective-dated catalogs/rates/assemblies, formula-driven estimates, source/version traceability, approvals, and workbook integration.

### Phase 5: Stripe Sandbox

Restricted test key, draft invoice workflow, idempotent writes, verified/deduplicated webhooks, reconciliation, permissions, and audit. Live mode follows an explicit security and accounting readiness review.

### Phase 6: Production hardening

MFA, backups/restores, retention, monitoring, drift checks, capacity/cost controls, mobile usability, incident response, and live Stripe rollout.

### Later options

Customer portal, communications integrations, additional accounting exports, advanced scheduling/dispatch, and an SCS-specific adapter remain separate approved projects.

## Non-goals for the first implementation plan

- customer accounts or public SCS chat;
- automatic sending of reports/invoices;
- autonomous refunds or financial changes;
- direct model writes to workbooks;
- editing the master through a job workflow;
- automatic safety or compliance certification;
- training on customer records;
- guaranteeing all specialized models fit simultaneously;
- building every TAB/HVAC template or manufacturer catalog at once.

## Acceptance criteria

- SCS starts at `ai.sunshineclimatesolutions.com` with employee/owner login only.
- DEFEND and SCS ordinary identities, cookies, APIs, stores, tools, RAG, uploads, audits, and backups are provably isolated.
- The owner's mapped identity can administer both without sharing ordinary sessions.
- A job accepts large photo batches and preserves traceable originals.
- Vision proposals remain distinct from confirmed facts and expose grounding/confidence/conflicts.
- Missing/uncertain evidence remains unresolved rather than invented.
- A new project workbook is generated from a pinned read-only master without modifying it.
- Formula, formatting, validation, print, and visual checks pass before approval.
- Estimates resolve effective-dated data and calculations remain deterministic/auditable.
- Stripe Sandbox writes are restricted, approved, idempotent, verified, and reconciled.
- Model quality/cost and correction drift are measured and rollback is tested.
- Existing DEFEND behavior and verification suites remain green throughout phased delivery.

