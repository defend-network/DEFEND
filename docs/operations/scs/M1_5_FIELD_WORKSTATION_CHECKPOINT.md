# SCS M1.5 — Field Workstation Checkpoint

Date: 2026-08-23 · Base: `86681f0` · CI: LOCAL_TEST_EVIDENCE_ONLY

## Result

`SCS_M1_5_FIELD_WORKSTATION = PARTIAL`

The workstation implementation is complete; the owner-data acceptance gates are
**NOT_CONFIGURED** (no owner-approved documents or private validation job were
available during this pass). Nothing was fabricated.

## What shipped

- `scs_copilot/job_service.py` — server-authoritative job truth packet
  (`build_job_truth_packet`) + job-scoped copilot (`run_job_scoped_copilot`)
  returning a structured answer contract. The browser sends `{job_id, message}`
  only; job truth is never client-constructed.
- `scs_reports/readiness.py` — deterministic ready-to-leave state machine
  (NOT_READY / NEEDS_REVIEW / READY_WITH_NOTES / READY) with explicit reasons
  wired to open measurements, active procedures, active diagnostics and
  conflicts.
- `scs_knowledge/discovery.py` — document discovery + owner approval
  (DISCOVERED → CLASSIFIED → OWNER_APPROVED → INDEXED → BLOCKED) with sha
  provenance; physical file presence never grants authority.
- `scs_api/field_routes.py` — `/api/scs/field/jobs/*` (truth, readiness,
  copilot chat) + `/api/scs/knowledge/*` (status, discover, approve, block)
  behind the existing SCS session + permission boundary.
- `scs-ui` — extended (not replaced): `FieldWorkspace.tsx`,
  `KnowledgePanel.tsx`, `lib/fieldApi.ts`, updated nav/Workspace. UI build
  passes (`npm run build`), 33 frontend tests pass.
- Design + plan docs under `docs/superpowers/`.

## Subsystem classification

| Subsystem | Status |
|---|---|
| SCS_AUTH | COMPLETE |
| SCS_JOBS | COMPLETE |
| FIELD_WORKSTATION | COMPLETE |
| EQUIPMENT_CONTEXT | PARTIAL |
| FIELD_READING_CAPTURE | PARTIAL |
| AS_FOUND_FINAL_STAGING | PARTIAL |
| OPEN_MEASUREMENTS | COMPLETE |
| READY_TO_LEAVE | COMPLETE |
| REPORT_READINESS | PARTIAL |
| COPILOT_JOB_CONTEXT | COMPLETE |
| COPILOT_PERSISTENCE | COMPLETE |
| PROCEDURES | COMPLETE |
| DIAGNOSTICS | COMPLETE |
| KNOWLEDGE_ROOT | COMPLETE |
| KNOWLEDGE_DISCOVERY | COMPLETE |
| KNOWLEDGE_OWNER_APPROVAL | COMPLETE |
| OEM_RETRIEVAL | COMPLETE |
| STANDARD_RETRIEVAL | COMPLETE |
| CITATIONS | PARTIAL |
| OEM_APPLICABILITY | COMPLETE |
| LOCAL_MODEL | COMPLETE |
| DETERMINISTIC_ROUTING | COMPLETE |
| AGENTIC_TOOL_USE | COMPLETE |
| PRIVATE_OWNER_BENCHMARK | NOT_STARTED |
| REPORTS | COMPLETE |
| ATTACHMENTS | PARTIAL |
| MOBILE_FIELD_UX | PARTIAL |

## Honest metrics

- REAL_KNOWLEDGE_DOCUMENTS = 0 · REAL_OWNER_BENCHMARK = NOT_CONFIGURED
- LOCAL_PROVIDER = ollama_local · MODEL = qwen2.5:14b-instruct-q4_K_M
  (unchanged; tool-selection ~0.5, protocol failure 0.0 — model quality is a
  separate M1.5 follow-up, not masked)
- Deterministic route coverage: 9 fixture cases, wrong-authority 0.0

## What remains (owner action)

1. Point `SCS_KNOWLEDGE_ROOT` at owner-authorized manuals and approve them.
2. Select a private validation job (`SCS_M1_5_VALIDATION_JOB_ID` or UI).
3. Then re-run the real owner knowledge + private-job acceptance.
