# SCS M1.5 — Field Workstation Plan

Task-oriented plan with RED/GREEN cycles. Base `86681f0`.

## 1. Job truth packet + job-scoped copilot (P9-P12)

- RED: `build_job_truth_packet` returns UNKNOWN for absent fields; browser
  context cannot override; structured answer contract has `visible_answer`,
  `verified_claims`, `blocked_claims`, `copilot_mode`, `session_durable`.
- IMPLEMENT: `scs_copilot/job_service.py`.
- GREEN: unit tests + a job-scoped chat smoke via the refactored service.

## 2. Ready-to-leave engine (P20-P23)

- RED: NOT_READY/NEEDS_REVIEW/READY_WITH_NOTES/READY states with reasons;
  open measurements block; unresolved diagnostic blocks; design-unknown is
  distinguished from N/A.
- IMPLEMENT: `scs_reports/readiness.py`.
- GREEN: unit tests with synthetic JobRecord + memory states.

## 3. Knowledge discovery + owner approval (P2-P6)

- RED: physical file presence does not grant authority; states
  DISCOVERED→CLASSIFIED→OWNER_APPROVED→INDEXED→BLOCKED; sha provenance.
- IMPLEMENT: `scs_knowledge/discovery.py` (+ registry approval fields).
- GREEN: unit tests over a synthetic temp knowledge root.

## 4. SCS API surface (P10, P14, P35)

- IMPLEMENT: `scs_api/field_routes.py` (job truth, copilot chat, readiness,
  knowledge status/approve) behind existing auth principal.
- GREEN: route tests (principal required; generic 500; no path traversal).

## 5. scs-ui extension (P13-P19, P23, P32-P34)

- IMPLEMENT: `FieldWorkspace.tsx`, `KnowledgePanel.tsx`, job-scoped
  `AiAssistant`, updated `Workspace`/nav; `lib/fieldApi.ts`.
- GREEN: component tests + `npm run build`.

## 6. Acceptance + certification (P26-P31, P36-P39)

- Deterministic-route coverage measurement; honest local model benchmark;
  local HTTP restart smoke; no customer/private data committed.

## 7. Checkpoint doc (P19)

- `docs/operations/scs/M1_5_FIELD_WORKSTATION_CHECKPOINT.md`.

Commit at each green checkpoint. Targeted staging only.
