# DEFENDcoder — Owner Workstation Product Checkpoint V1 (Design)

**Date:** 2026-08-23
**Base runtime checkpoint:** `8cb800a`
**Scope:** Owner-facing product experience on top of the converged runtime core.

## Goal

Turn DEFENDcoder from a strong backend into a product the owner can open, use,
inspect, and trust: log in, choose a real workspace, browse files, start a
coding task, watch the agent, inspect diffs/tests/logs, approve/deny
escalation, resume safely, and see truthful usage/runtime/cost — without ever
accidentally renting GPU or leaking secrets.

## Bounded continuity closure (P0)

The single runtime-core gap closed before the resume UX is real: a persisted
checkpoint revision could be NEW but contain OLD progress because compaction
persisted the pre-existing checkpoint before deriving the work it was about to
drop.

Fix (implemented):
- `RunContextCoordinator.note_tool_execution` accumulates server-observed
  structured facts (tool name + path/command, ok/error, test output).
- `fold_progress()` merges those facts into the checkpoint (completed work,
  relevant files, latest tests, current failure) BEFORE the next revision is
  persisted and old messages dropped.
- `checkpoint_context_message()` emits a bounded, clearly-marked
  `[SERVER DURABLE CHECKPOINT]` dynamic-context message that is prepended to
  subsequent (and resumed) model requests — never part of the stable authority,
  never masquerading as an owner instruction.

## Information architecture

Three primary areas, desktop-first, high information density:

- **LEFT:** Projects / workspace / files / run history.
- **CENTER:** agent conversation + run (task composer, structured timeline,
  run phase, attempts/checkpoints).
- **RIGHT/BOTTOM:** evidence — changes/diff, tests, command logs, usage.

## Backend owner read APIs

Focused, typed, no raw DB rows, no secrets:
- `GET /v1/workspaces/{ws}/runs/{run}/attempts|checkpoints|tool-executions|telemetry`
- `GET /v1/workspaces/{ws}/files/content?path=…` (bounded, binary-detecting)
- `GET /v1/workspaces/{ws}/git/status` (porcelain + bounded unified diff)
- `POST /v1/workspaces/{ws}/runs/{run}/resume` (blocked when an
  UNKNOWN_AFTER_INTERRUPTION mutation exists)

## Model routing / escalation UX

- Ladder preserved: AUTO → DeepSeek V4 Flash → (owner-approved) Qwen3-Coder-Next
  → GPT-5.6 Sol.
- Selector shows truthful configured/available state; viewing or selecting NEVER
  starts GPU.
- Escalation requires owner approval; escalation to Next is not implicit
  approval to rent/start compute.

## Crash / recovery UX

- A `RECOVERY REQUIRED` card surfaces UNKNOWN_AFTER_INTERRUPTION prominently
  (tool, safe argument summary, execution id short, reason) with the explicit
  statement that DEFENDcoder will not automatically repeat it.
- No blind retry button. Resume is blocked while an UNKNOWN mutation exists.

## Truthfulness rules

- Cost shown only when an authoritative pricing basis exists; otherwise
  `COST NOT AVAILABLE` (never `$0.00`).
- Test counts only when a real parser exists; otherwise `RAW TEST OUTPUT`.
- Changed-file lists come from server/git truth, never fabricated from
  assistant messages.
- No provider API key or secret-bearing environment value in browser JS.

## Ports (unchanged)

- Internal API: `8301`
- UI dev: `3301`
- Model-forward: `8403` (product model forward, NOT the Coder FastAPI app)

## Non-goals

No second frontend, no second auth system, no runtime-core rewrite, no
automatic GPU start, no live paid provider calls during acceptance.
