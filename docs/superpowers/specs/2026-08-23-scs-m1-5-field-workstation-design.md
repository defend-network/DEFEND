# SCS M1.5 — Field Workstation Design

Date: 2026-08-23 · Status: accepted design · Base: `86681f0`

## Goal

Turn SCS AI into an owner-usable field workstation. The trust architecture
(M1.4.x) is locked; M1.5 makes it useful in the field and closes the
architecture split between the generic AI assistant and the field copilot.

## Current reality (inventory)

- `scs-ui` (Next.js 16, `:3100`) — login/session, dispatch jobs, reports,
  calculators, customers, employees, a **generic** AI assistant.
- `scs_api` (FastAPI, `:8100`) — auth/employee/customer/membership/job/report
  REST. Jobs use `scs_data.jobs.ScsJobStore` (dispatch model: customer/site/
  type/visits/notes) — **no** equipment/readings.
- `scs_ai` (`:8300`) — generic chat + calculations gateway. The assistant sends
  a **browser-generated `jobContext` string** to `/v1/chat`; the browser is
  currently the authority for job truth.
- `tools/job_copilot.py` (`:3220`) — the trust-hardened field copilot with its
  own workspace, `scs_reports.schema.JobRecord` (equipment/air-devices/
  findings/photos), plan graph, knowledge, procedures, diagnostics, memory.
- `scs_copilot` / `scs_knowledge` / `scs_reports` / `scs_engineering` /
  `scs_procedures` / `scs_diagnostics` / `scs_equipment` — the locked trust
  libraries.
- `scs_reports.completeness` already has a BLOCKING/IMPORTANT/OPTIONAL
  readiness evaluator (READY / MISSING BEFORE LEAVING).

## Key architectural decision

One server-authoritative job truth packet. The browser sends `{job_id,
message}` only; the server loads job identity, evidence, equipment, memory,
design state, measurements, knowledge authority, procedures, diagnostics and
open requirements. The browser can never override real job truth.

The field copilot's `JobRecord` model is the field-workstation source of truth
(equipment, design, readings, procedures, diagnostics, readiness). It is
served through the SCS API surface, not through a second frontend.

## Modules to build

1. `scs_copilot/job_service.py` — pure functions:
   - `build_job_truth_packet(record, graph, memory, knowledge)` (P9).
   - `run_job_scoped_copilot(workspace, job_id, question, ...)` — refactor of
     `tools/job_copilot._run_copilot`, returning the structured answer
     contract (P10-P12).
2. `scs_reports/readiness.py` — deterministic ready-to-leave state machine
   (NOT_READY / NEEDS_REVIEW / READY_WITH_NOTES / READY) with reasons, wired to
   open measurements + active procedure/diagnostic + conflicts (P20-P23).
3. `scs_knowledge/discovery.py` — document discovery + owner-approval states
   DISCOVERED/CLASSIFIED/OWNER_APPROVED/INDEXED/BLOCKED (P2-P6).
4. `scs_api/field_routes.py` — FastAPI router exposing job truth, job-scoped
   copilot chat, readiness and knowledge status/approval behind the existing
   auth principal (P10, P14, P35).

## Frontend

Extend `scs-ui` (do not replace): a job-first Field workspace (equipment,
field readings with AS_FOUND/INTERMEDIATE/FINAL, open measurements,
ready-to-leave, procedures/diagnostics) and a Knowledge area (discovered /
approved / indexed / blocked). The AI assistant becomes job-scoped and sends
`{job_id, message}`, not a `jobContext` string.

## Explicit non-goals

No second frontend. No cloud model. No auto-downloaded model. No committed
owner documents/job data. No LLM-authoritative readiness. No fake metrics.
