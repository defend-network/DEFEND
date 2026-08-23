# DEFENDcoder — Owner Workstation Product Checkpoint V1 (Plan)

**Date:** 2026-08-23
**Base:** `8cb800a` → continuation commits

## Order of work

1. **P0 bounded continuity** (done — `307aed1`): checkpoint captures dropped
   work + reaches post-compaction and resumed model calls.
2. **Owner read APIs** (done — `e3080d7`): attempts / checkpoints /
   tool-executions / telemetry / file content / git snapshot / resume.
3. **UI extensions** in `defendcoder-ui` (extend, not rebuild): file viewer,
   run history + detail, recovery card, resume, attempt/checkpoint view,
   real git diff, usage/cost.
4. **Docs**: this plan + spec + checkpoint document.
5. **Local acceptance**: `npm ci` / `npm test` / `npm run build`; Python
   regression; real-Postgres integration.

## Backend (already converged — preserved)

Durable authority, server-authoritative pins, RunPreparationService, envelope,
route history, checkpoints, attempts, tool ledger, ContextBudgetManager,
RunContextCoordinator, mutation crash safety.

## Frontend extension points

- `app/workspace/load-workspace.ts` — add typed helpers for the new read
  endpoints + resume.
- `components/*.tsx` — add `FileViewer`, `RunHistory`, `RecoveryCard`, and
  extend `WorkspaceShell` (split responsibilities where it grows).
- `app/globals.css` — extend the existing dark engineering theme.

## Verification

- `tests/test_owner_workstation_runtime_integrity.py` — real `defendcoder_test`
  PostgreSQL, no persistence mocks, fake providers.
- Full coder regression.
- `npm ci && npm test && npm run build` in `defendcoder-ui`.

## Safety invariants

No GPU on page view / selector / status view. No blind mutation replay. No
secret material in browser assets. Production DB `defendcoder` untouched by
tests.
