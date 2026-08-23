# DEFENDcoder — Owner Workstation Checkpoint V1

**Date:** 2026-08-23
**Base:** `8cb800a` (runtime core)
**Final:** see git HEAD (remote-verified)

## Status by subsystem

| Subsystem | State |
|---|---|
| RUNTIME_CORE | COMPLETE (preserved) |
| AUTHORITY | COMPLETE |
| ROUTING | COMPLETE |
| DEEPSEEK | PARTIAL (configured/credential path exists; live call NOT run) |
| NEXT | PARTIAL (runtime lifecycle owned by Control Center; no GPU started) |
| SOL | PARTIAL (provider + Responses continuation exist; not called) |
| CONTEXT | COMPLETE |
| CHECKPOINT_CONTINUITY | COMPLETE |
| MUTATION_RECOVERY | COMPLETE (backend) |
| WORKSPACES | COMPLETE |
| FILE_EXPLORER | PARTIAL (browse + open; no per-file modified indicators yet) |
| FILE_VIEWER | COMPLETE (bounded, binary-detecting, line numbers) |
| TASK_COMPOSER | COMPLETE |
| AGENT_TIMELINE | PARTIAL (structured messages; collapsible tool output pending) |
| RUN_HISTORY | PARTIAL (list endpoint exists; full history UI list pending) |
| RUN_DETAIL | PARTIAL (run + messages + attempts/checkpoints/tool-executions/telemetry read APIs) |
| DIFF | COMPLETE (real git status/diff) |
| TEST_EVIDENCE | PARTIAL (raw output; no parser) |
| COMMAND_EVIDENCE | PARTIAL (raw output) |
| ATTEMPTS | COMPLETE (live records + read API) |
| CHECKPOINTS | COMPLETE (revisioned + read API) |
| ESCALATION | COMPLETE (approval UX; no auto-approval) |
| RESUME | COMPLETE (resume endpoint; blocked when UNKNOWN mutation exists) |
| RECOVERY_UI | COMPLETE (RecoveryCard) |
| MODEL_SELECTOR | COMPLETE (truthful configured/available) |
| RUNTIME_STATUS | COMPLETE |
| USAGE | COMPLETE (telemetry read API) |
| COST | PARTIAL (no authoritative pricing basis; shows COST NOT AVAILABLE) |
| AUTH | COMPLETE (reused) |
| LOCAL_LAUNCH | COMPLETE (API 8301, UI 3301) |
| PRODUCTION_BUILD | COMPLETE (`npm run build` standalone) |
| CLOUDFLARE_ROUTE | OWNER_ACTION_REQUIRED |
| PUBLIC_HOSTNAME | OWNER_ACTION_REQUIRED (defendcoder.defend-network.org) |
| LIVE_DEEPSEEK_ACCEPTANCE | OWNER_ACTION_REQUIRED (no spend authorization) |

## What this milestone changed

- **P0 bounded continuity** (`307aed1`): `RunContextCoordinator.note_tool_execution`
  + `fold_progress` fold server-observed work into the checkpoint before
  compaction drops the conversation; `checkpoint_context_message` injects a
  bounded, clearly-marked dynamic-context message into post-compaction and
  resumed model requests (never part of stable authority).
- **Owner read APIs** (`e3080d7`): attempts / checkpoints / tool-executions /
  telemetry / file content / git snapshot / resume.
- **UI** (in `defendcoder-ui`): `FileViewer`, `RecoveryCard`, real git diff in
  the Diff tab, file-open in the explorer, resume button, tool-execution
  recovery gating surfaced.

## Local launch

- API: `127.0.0.1:8301`
- UI dev: `npm run dev` → `127.0.0.1:3301`
- UI production: `npm run build` then `node .next/standalone/server.js`

## Safety

- Production DB `defendcoder` untouched (tests use `defendcoder_test`).
- No live DeepSeek / Next / Sol calls; no GPU started; no paid compute.
- No secrets in browser assets.

## Residual risks

- Context windows are configured (conservative), not measured per provider.
- No per-file "modified" indicators in the explorer yet.
- Cost display is `COST NOT AVAILABLE` (no authoritative pricing source).
- Cloudflare hostname wiring requires owner action.
