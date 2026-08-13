# SCS Phase 1 Foundation Design

## Purpose

Build the first usable employee-only Sunshine Climate Solutions application on
top of the Phase 0 isolation contract. Phase 1 establishes SCS identity,
authorization, employee administration, customers, contacts, sites, basic
equipment, memberships, jobs, visits, assignments, notes, audit history, and a
mobile-friendly operational workspace.

Phase 1 does not give customers accounts, run photo analysis, calculate
estimates, generate workbooks, synchronize Stripe, or activate public access
before authentication and health gates pass.

## Application and deployment boundary

SCS uses its reserved Phase 0 context:

- application ID `scs`;
- data root `C:\SCS_DATA`;
- environment and encrypted-secret namespace `SCS_*`;
- session cookie `scs_employee_session`;
- API port 8100 and web port 3100;
- public origin `https://ai.sunshineclimatesolutions.com`.

The SCS API, frontend, database, sessions, uploads, audit records, backups,
tools, prompts, and indexes remain separate from DEFEND. Shared code accepts an
explicit application context and cannot open a DEFEND application store while
executing an SCS request. The SCS origin remains inactive until login, health,
backup, rollback, and isolation acceptance tests pass.

## Identity and invitations

The SCS owner is bootstrapped once from encrypted Control Center credentials.
There is exactly one active owner account in Phase 1. Owner bootstrap is
idempotent, never prints credentials, and refuses to replace an existing owner.

There is no public registration. The owner and active operations administrators
may invite employees. Only the owner may grant or remove `operations_admin`,
change owner-controlled permissions, disable an operations administrator, or
perform other owner-only account transitions.

Invitations are delivered through separate SCS Gmail credentials. Delivery
failures preserve a safe retryable invitation record and provide an authorized
owner/operations-admin manual-copy fallback. Raw invitation tokens appear only
at creation or authorized regeneration, are stored only as hashes, use fragment
transport for activation, expire, and are invalid after acceptance/revocation.

SCS sessions are stored as hashes, use Secure/HttpOnly/SameSite cookies, expire,
support revocation, and cannot authenticate to DEFEND. Login, logout, activation,
failed authentication, session revocation, and account state changes are audited
without raw credentials or tokens.

## Authorization model

Authorization has three independent dimensions:

1. Security roles grant application permissions.
2. Job functions and qualifications describe workforce capability.
3. Assignments determine ordinary record visibility.

Security roles are:

- `owner`;
- `operations_admin`;
- `billing`;
- `estimator`;
- `reviewer`;
- `read_only`.

An employee may hold multiple roles. Permissions are evaluated at API and
service boundaries; hiding a frontend control is never sufficient. The owner
receives every SCS permission. Operations administrators manage ordinary
employees and operational configuration but cannot perform owner-only role,
secret, or platform actions.

Initial job functions are:

- apprentice;
- service technician;
- maintenance technician;
- installation technician;
- sales technician;
- salesperson;
- TAB technician;
- TAB supervisor;
- service manager;
- installation manager.

Technician level is a separate internal qualification with values Apprentice,
Technician I, Technician II, and Technician III. Only the owner, operations
administrators, service managers, and installation managers may view or change
technician level. Other employees and all customer-facing exports omit it.
Function and qualification assignments are effective-dated and append history
rather than overwriting prior records.

Employees normally access only jobs to which they are assigned. Explicit
scheduling, operations-wide, estimating, billing, reviewing, or management
permissions expand visibility only as required. Customer, financial, export,
employee-management, and audit permissions remain separately enforceable.

## Customer, contact, and site records

Customer profiles are internal employee records. A customer has an opaque public
identifier, lifecycle state, display/legal names, customer type, communication
preferences, internal notes, and immutable
created/updated provenance.

A customer may have multiple contacts and multiple sites. Contacts have explicit
purposes and preferences rather than one overloaded primary-contact field. Sites
contain service addresses, access instructions, timezone, and separate billing
relationship metadata. Billing and service addresses may differ. Record history
is durable and archive-based; ordinary workflows do not hard-delete customers
with operational history.

The profile presents HVAC service, installation, maintenance, sales, and TAB
history in one customer timeline while retaining job discipline and type.

## Customer summary metrics

The customer summary contract includes:

- lifetime invoiced;
- lifetime paid;
- outstanding balance;
- average whole/fractional days from job completion to payment;
- last completed service date;
- total jobs;
- active membership status and plan;
- active site count;
- equipment count.

Phase 1 calculates only metrics supported by authoritative Phase 1 records.
Financial and payment-latency fields return a typed `not_available` state until
invoice/payment event stores exist. They never display zero as a substitute for
missing integration and are never estimated by a language model.

## Equipment foundation

Phase 1 supports basic equipment linked to one customer and site, with equipment
type, manufacturer, model, serial number, install/manufacture dates when known,
status, location, and notes. Sensitive or estimate-driving values retain source
and confirmation metadata. Equipment history is preserved.

The schema reserves stable relationships for later photographs, readings,
vision proposals, catalog matches, warranties, maintenance tasks, estimates,
reports, and workbook fields. Phase 1 does not implement those workflows.

## Membership plans and enrollments

Membership is structured data, not a free-form customer tag. Plans are
configurable and effective-dated. Phase 1 seeds one inactive-or-active configurable
plan named `Maintenance Member`; authorized staff may update future versions
without rewriting historical enrollments.

Enrollment records contain customer, plan version, status, start/end dates,
covered sites or equipment when specified, renewal metadata, notes, and actor
provenance. Status is one of active, paused, expired, or cancelled. Changes append
history and are audited.

## Jobs, visits, assignments, and notes

A job belongs to exactly one customer and one site. Initial job types are:

- HVAC service;
- preventive maintenance;
- installation/replacement;
- warranty/callback;
- sales/estimate;
- TAB testing;
- TAB reporting;
- commissioning support;
- internal/non-billable.

Jobs have durable status history, requested scope, priority, discipline,
scheduling fields, internal notes, and
unresolved items. A job may have multiple visits and multiple assignments.
Assignments record the employee, assignment role, effective interval, assigning
actor, and status. Visits preserve work performed, findings, recommendations,
an optional technician-entered readings summary, arrival/completion timestamps,
and author.

Notes have an explicit visibility class: operational, management-only,
billing-only, or future-customer-safe. Service methods enforce visibility before
returning note content.

## Controlled classifications

Job classifications are controlled codes, not arbitrary security decisions.
Initial codes include:

- `new-customer`;
- `potential-member`;
- `system-age-0-3`;
- `system-age-4-7`;
- `system-age-8-plus`;
- discipline and job-type codes corresponding to the approved job types.

`potential-member` is invalid for TAB-only jobs. Exactly zero or one system-age
bucket may be active. An age bucket derives from a confirmed manufacture or
installation date relative to the job date; if the source date is absent or
uncertain, no age bucket is inferred. Authorized employees confirm proposed
classifications, and every change records source, actor, and time.

## CSV import preview

Phase 1 provides manual customer entry and a bounded CSV preview workflow. The
preview accepts UTF-8 CSV only, enforces row/column/file limits, and performs no
database writes. An authorized employee maps source columns to customer,
contact, and site fields, then receives proposed creates, possible matches,
conflicts, rejected rows, and normalized values.

Matching is advisory and never silently merges customers. Preview artifacts
exclude credentials and expire. Committing imports is a later separately tested
operation after the schema and real source exports are reviewed.

## Extension contracts

Phase 1 defines identifiers and typed service boundaries for later:

- evidence/photo batches and vision candidates;
- estimates, lines, catalogs, prices, and tax decisions;
- reports, templates, workbook generations, reviews, and exports;
- invoices, Stripe customers/invoices, payments, and webhook events;
- SCS language, vision, and embedding tool registries.

These contracts may be interfaces, foreign-key-ready identifiers, and explicit
`not_available` states. Phase 1 must not create nonfunctional buttons, empty
tables for speculative fields with no defined owner, or routes that imply a
later workflow is operational.

## API and frontend composition

SCS has a separate FastAPI composition root and separate frontend application.
The API starts only with an explicit SCS application context and opens only SCS
stores. It exposes fixed SCS authentication and operational routes with
permission dependencies applied at routers and services.

The frontend opens directly to a branded Sunshine Climate Solutions login page.
After login, navigation and dashboards reflect granted permissions. The first
workspace is mobile-friendly and supports customer/site lookup, assigned-job
lists, job/visit detail, notes, classifications, and manager-authorized employee
administration. Customer logins and anonymous chat do not exist.

Errors use safe stable messages and correlation IDs. Validation errors identify
fields without exposing database statements, filesystem paths, secrets, tokens,
or records the caller cannot access.

## Audit and retention

Append-oriented SCS audit events record:

- successful and failed login events;
- invitation creation, delivery, retry, revocation, and acceptance;
- session revocation;
- employee role, function, qualification, status, and assignment changes;
- sensitive customer/equipment reads and exports;
- customer, contact, site, equipment, membership, job, visit, note, status, and
  classification mutations;
- denied actions and administrative configuration changes.

Audit views are permissioned and bounded. They omit passwords, hashes, raw
tokens, cookies, secret values, SMTP content, and unnecessary note/customer
content. Login history exposes safe metadata such as time, result, and bounded
network/device classification rather than reusable credentials.

Phase 1 includes a separate SCS backup manifest and restore verification path.
SCS and DEFEND backups cannot target the same directory or be restored into the
other application's data root.

## Delivery slices

1. SCS composition root, stores, schema migration mechanism, health, and backup
   boundary.
2. Owner bootstrap, employee identity, invitations, sessions, roles,
   permissions, functions, technician levels, and audit.
3. Customers, contacts, sites, basic equipment, service APIs, and authorization.
4. Membership plans, seeded Maintenance Member version, enrollments, and history.
5. Jobs, visits, assignments, notes, statuses, classifications, and visibility.
6. Customer summary contract and authoritative/not-available metric states.
7. Bounded CSV import preview with no commit operation.
8. Branded login and mobile-friendly employee workspace.
9. Cross-application isolation, authorization, migration, backup, frontend, and
   complete DEFEND regression verification.

Each slice uses test-first development and an independently reviewable commit.

## Non-goals

- customer accounts or customer portal;
- public registration or anonymous SCS chat;
- photo upload/vision processing;
- production estimates, catalogs, taxes, reports, or workbooks;
- Stripe synchronization, invoices, or payment calculations;
- customer communications or automatic sending;
- activation of the public SCS hostname before readiness approval;
- reuse of DEFEND databases, cookies, ordinary accounts, sessions, tools, or
  indexes;
- autonomous safety, financial, membership, or classification decisions.

## Acceptance criteria

- SCS starts only with an explicit validated SCS context and opens only its data
  root.
- The branded SCS site presents login before any operational content.
- Owner bootstrap and invitation-only employee activation work without storing
  raw credentials or tokens.
- Multiple security roles and job functions are supported independently.
- Technician level is visible/changeable only to the approved management group.
- Employees cannot access unassigned jobs without an explicit broader
  permission.
- Customers support multiple contacts/sites and separate billing/service data.
- Basic equipment and configurable Maintenance Member enrollments have durable
  history.
- All approved job types, visits, assignments, note visibility classes, and
  controlled classifications are enforced.
- TAB-only jobs reject `potential-member`; uncertain equipment age creates no
  age tag.
- Financial summary fields are explicitly unavailable until authoritative event
  stores exist.
- CSV processing is preview-only and cannot mutate operational records.
- Sensitive reads and changes generate bounded secret-safe audit events.
- SCS and DEFEND identities, cookies, ports, origins, roots, stores, audits,
  backups, routes, and sessions remain demonstrably isolated.
- Existing DEFEND backend tests, frontend tests, and production build remain
  green.
