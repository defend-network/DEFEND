# AGENT EFFICIENCY + FINALIZATION HARDENING — STOP REPORT

Status: ALL P0–P10 items implemented (P9/P10 are proposals only). STOP BEFORE COMMIT — nothing has been committed. PAID_COMPUTE_USED: NO.

## P0 — DEFENDCODER_BENCH_V1 frozen

- Snapshot: `bench/defendcoder_bench/v1_manifest.json` — all 10 tasks (classes A–J) with fixture SHA-256s, scripts, expected/forbidden/inspect sets, max_steps, grader rules (gates, thresholds, metric definitions), and configuration.
- MANIFEST_SHA256: `312186636649c553b42af9c26d0290cdbf5ef753d98cc1d03db199a0d4083563` (canonical sort_keys+indent-2 JSON, excluding the self-referential field).
- Guard tests (`tests/test_defendcoder_bench.py`): `test_v1_manifest_frozen` and `test_v1_manifest_pins_current_sources` — any future edit to the 10 tasks/fixtures fails loudly.
- The 10 task definitions and `grader.py` scoring rules are byte-untouched this slice. Note: grader `_FINAL_STATES` still lists legacy `succeeded_with_warnings` as a superset — harmless (never produced now; `succeeded` still passes) and kept for V1 byte-freeze.

## P1/P1B — Completion-state model vs stop reason

Agent terminal outcomes (`defend_coder/agent.py`, `AgentOutcome`):

| State | Meaning | Reasons produced |
|---|---|---|
| `succeeded` | terminal response inside budget (natural or finalization turn) | `natural_completion`, `finalized` |
| `partial_success` | incomplete work stopped by action/wall-clock limit, including finalization failing to produce a terminal response | `action_limit`, `wall_clock_limit` |
| `failed` | model/tool/internal failure | `model_timeout`, `model_unavailable`, `model_error`, `tool_error`, `internal_error`, `invalid_prompt` |
| `cancelled` | user cancellation | `user_cancel` |

- Finalization stays OUTSIDE the action budget: exactly one synthesis-only model turn (no tools, no workspace mutation) after the step budget is exhausted.
- No `succeeded` + hard-error contradiction exists: model failures are `failed`; limit-stopped incomplete work is `partial_success`, never full success.
- Wall-clock stop changed `failed` → `partial_success` (work genuinely incomplete, nothing wrong).
- Finalization success `succeeded_with_warnings` → `succeeded` + `finalized`; finalization disabled/failed/timed out/returned tool calls → `partial_success` + `action_limit` (was `incomplete_step_limit` + `step_limit`).
- New honest terminal: unexpected toolkit exception during a tool call → `failed` + `tool_error` (previously crashed into `internal_error` at the runner).
- Legacy values remain readable and historical rows are NOT rewritten; migration `0005_completion_state_telemetry.sql` widens the status/reason CHECK constraints (no data migration).
- `cancelled` is now a persisted status (previously persisted as `failed` + `user_cancel`); phase mapping updated; API shape unchanged; UI updated (types, labels "Partial"/"Cancelled", banner shows reason for partial_success/cancelled/failed).

## P2/P2A — Per-call telemetry

- `AgentChatResponse` now preserves provider `usage` (`prompt_tokens`/`completion_tokens`/`total_tokens`) and `finish_reason` when the serving API returns them; `reasoning_content` is never captured, parsed, or persisted.
- New `defend_coder/telemetry.py`: `ModelCallRecord` + `build_call_record` + `aggregate_model_calls`. Per call: step, phase, started/finished, provider tokens (NULL when absent), finish_reason, max_tokens_requested, tool_calls_requested, assistant_visible_chars, assistant_visible_tokens (ESTIMATE, chars/4, only when output tokens reported), context_tokens (= provider prompt_tokens), remaining_action_budget, request_roundtrip_seconds (exact client wall-clock), generation_seconds (NULL — backend does not report), tokens_per_second (ESTIMATE), error_class.
- Estimates are stored in their own fields and labeled; provider token counts are never fabricated.
- New table `coder_model_calls` (migration 0005; indexes run_id+step, run_id, created_at; no sensitive payloads). `RunsRepository`: `record_model_call`, `model_calls_for_run`, `aggregate_model_calls` (totals + P50/P95/MAX round-trip and output tokens, finish_reason/error/phase histograms).
- `CodingAgent` emits telemetry through a `telemetry_sink` on every call INCLUDING failures (timeouts recorded with `error_class`); `RunRunner` persists to the DB.
- Bench harness collects telemetry (scripted client simulates usage/finish_reason) and the JSON report now includes per-task telemetry + wall-clock decomposition.

## P2B — Wall-clock accounting

- `RunsRepository.wall_clock_accounting(run_id)` derives from persisted timestamps: QUEUE_WAIT (created_at → first message), REQUEST_ROUNDTRIP (sum of client-measured model-call round-trips), TOOL_EXECUTION (assistant-with-tools → answering tool result deltas), FINALIZATION (round-trips with phase `finalizing`); PERSISTENCE is measured in the runner (timed append sink) and passed in; UNATTRIBUTED = remainder; ACCOUNTED_WALL_CLOCK_PERCENT reported. Persisted once at termination in `coder_runs.accounting` (JSONB).
- MODEL_GENERATION_SECONDS is NOT_AVAILABLE (backend exposes no per-request generation time); REQUEST_ROUNDTRIP_SECONDS is the exact figure. No double-counting.

## P4 — Phase token budgets

- Only phases the architecture can genuinely distinguish: TOOL_WORK (normal step), ERROR_RECOVERY (call immediately after an ok=False tool result), FINAL_SYNTHESIS (the finalization turn). No fabricated PLAN/TOOL_SELECTION phases.
- Budgets: `CODER_PHASE_TOOL_WORK_MAX_TOKENS` (default: client ceiling 4096 — behavior unchanged), `CODER_PHASE_ERROR_RECOVERY_MAX_TOKENS` (default 2048), `CODER_PHASE_FINAL_SYNTHESIS_MAX_TOKENS` (default 2048; floor 256 so a useful terminal report is always possible). Clamped to [256, model ceiling]; env overrides validated in `CoderSettings`; `max_tokens` override supported by the client; policy endpoint reports effective `max_tokens`.

## P3 — Root cause of long generations (evidence-classified)

Analyzed real run `f95795ae-b939-4602-8752-d9fedaca097d` (12 steps, 1530s) message-by-message:

- **PROVEN** — Tool-argument JSON emission is the dominant cost. 3 of 12 calls were `write_file` with 16,695 / 13,333 / 15,011-char argument payloads; those three calls consumed 416s / 544s / 399s = 1,359s ≈ 89% of wall time. The 544s gap ≈ 4,096 max_tokens ÷ ~7.5 tok/s ≈ 546s: the model generated to the max_tokens ceiling serializing file contents into tool arguments. All 9 remaining calls (args ≤ 582 chars) completed in ≤ 23s.
- **STRONGLY_SUPPORTED** — `max_tokens=4096` is the binding ceiling with no stop tokens; `write_file` payload cost scales linearly with file size. (The prompt already prefers `edit_file` for small changes — these targets were new files, so full writes were the correct behavior.)
- **HYPOTHESIS** — Qwen3 thinking mode burning hidden budget (Qwen3 templates enable thinking by default; we do not set `enable_thinking=false` and discard `reasoning_content`). Cannot be confirmed without live usage payloads.
- **NOT_AVAILABLE_WITHOUT_LIVE_RUN** — exact token split (reasoning vs output vs tool-args) and finish_reason values; P2 telemetry now captures these on the next live run.

Mitigation shipped this slice: P4 budgets cap the recovery/finalization long tail; the tool-work ceiling is untouched so normal (and write_file) behavior is unchanged — quality-preserving by construction.

## P5 — Trajectory analysis

- Bench V1 (10/10): mean steps 3.6; duplicate 4% (one repeated identical call), no-progress 0%, recovery 4%, useful 92%, targeted-edit 100%. Transcripts are coherent; no pathological loops.
- Real run f95795ae: `list_files×2` (different targets) → `run_command×2` (recon) → `write_file×3` (three distinct files, written once each — no edit-revert) → `run_command×5` (distinct verify/test-fix commands, all fast). No argument-identical duplicate calls, no no-progress sequences. A defensive reread that prevents a bad edit is NOT automatically redundant — none flagged.

## P6 — Context growth

- Stored message bytes ≈ 2.7 KB; the resend cost is dominated by the write_file tool-argument echo (~45 KB cumulative ≈ 11–15K input tokens per later request; full final context ≈ 15–20K tokens) — comfortably inside Qwen3 context, no evidence of overflow or degradation.
- Narrowest safe policy: keep full history, NO compaction. Provider token counts will be captured by P2 telemetry on live runs; revisit compaction only if `input_tokens` approaches the context limit.

## P7 — Prompt audit

- OWNER_PROMPT_LOADED: **true** (byte-identical 9,106-byte asset vs `C:\Users\thoma\Downloads\DEFEND32B\DEFEND_coder_prompt.txt`)
- OWNER_PROMPT_SHA256: `78ab8899ca968efe50bee4bc57e6ee2675849be84af3e07e99c8d22826832442`
- SYSTEM_MESSAGE_COUNT: **1** (single composed system message)
- SYSTEM_MESSAGE_ORDER: `[DEFEND OWNER DIRECTIVE]` → agent behavior → `[MODEL-SPECIFIC TECHNICAL INSTRUCTIONS]`
- QWEN_TECHNICAL_GUIDANCE_PRESENT: **true** (Qwen3CoderToolParser, OpenAI function-calling format, write_file/edit_file guidance)
- CONTRADICTORY_SYSTEM_INSTRUCTIONS: **none found**
- EFFECTIVE_POLICY_HASH: `3a970bc7f1726732ffd40b64e96159fbbba339b29beb79860efe16e220098474` (PROMPT_VERSION `2026-08-18.v1`, unchanged)
- EFFECTIVE_PRECEDENCE: owner directive > agent behavior > model technical > task content

## P8 / P8B — A/B on frozen V1

- BASELINE = all phases 4096 (pre-change behavior, run with `CODER_PHASE_*_MAX_TOKENS=4096`).
- CANDIDATE = shipped defaults (4096 / 2048 / 2048).
- Both: **10/10 PASS**; targeted 100%, duplicate 4%, no-progress 0%, recovery 4%, useful 92%, mean steps 3.6.
- DETERMINISTIC=YES → RUNS_REQUIRED=1. Scripted bench does NOT validate real-model speed; it validates quality-gate stability. CANDIDATE_PASS_RATE == BASELINE_PASS_RATE, no regression. Efficiency effect (halved ceiling on recovery/finalization turns) is only exercised when those turns occur — not on V1, which is exactly the gap P9 targets.

## P9 — Bench V2 proposal (proposal only, not built)

V1 scripts all complete in 3–5 steps without recovery/finalization — the new state model and phase budgets are never exercised. V2 should add tasks that force them:

1. **long-horizon completion** — 8–12 small edits in one task;
2. **step-budget exhaustion** — task requiring more than max_steps (verifies `partial_success` + `action_limit` honesty);
3. **final-summary correctness** — inspect tokens must appear only in the FINAL message (incl. finalized runs);
4. **multi-file implementation** — cross-referenced files;
5. **test-fix-retest recovery** — fail → fix → rerun until green (exercises the error_recovery budget);
6. **unfamiliar-repo navigation** — larger tree, no hints;
7. **unrelated-edit avoidance** — forbidden-gate on untouched files.

## P10 — Paid confirmation proposal (not launched)

- **OFFER**: NOT_AVAILABLE_FROM_RECORDS — the owner's GPU/Vast account details and rate are not on file; needed before any launch.
- **GPU**: 1× H100 80GB (fallback A100 80GB), vLLM serving Qwen3-Coder-Next with Qwen3CoderToolParser (mirrors the previously validated architecture).
- **HOURLY_RATE**: ~$1.50–2.50/h (H100 spot, 2026); confirm against the owner account.
- **EXPECTED_RUNTIME**: 1× V1 suite, worst case ~4–6 h (12 steps × ≤600s timeout + warmup).
- **MAX_SPEND**: **$15.00** hard cap.
- **HYPOTHESES_TO_TEST**:
  - H1: thinking-mode overhead — `completion_tokens` ≫ visible text; probe `enable_thinking=false` (P3 HYPOTHESIS);
  - H2: write_file max_tokens-cap stalls — `finish_reason == "length"` on write_file calls; test chunked-edit strategy vs raised cap;
  - H3: P4 budgets cut recovery/finalization latency without quality loss — live A/B on V1.
- **WHY_LOCAL_IS_INSUFFICIENT**: Qwen3-Coder-Next requires a GPU; the scripted bench cannot produce provider usage, finish_reason, or real generation time; H1–H3 are falsifiable only with live telemetry (P2 now records it).

## Regression summary

- Full suite (`pytest tests`): **1788 passed, 22 skipped, 0 failures in defend_coder / defend_data / bench lanes**.
- 15 pre-existing SCS-lane failures (`test_scs_reports*.py`) — shared `C:\SCS_DATA\masters` install interference; **24/24 pass in isolation**, same flake pattern documented in the previous slice; SCS/Markets untouched per directive.
- UI: `tsc --noEmit` clean; **37/37 vitest** green.
- Bench: 10/10 PASS with telemetry in report (baseline A/B run also 10/10).

## Commit boundary

- `git diff --check`: clean (no whitespace/conflict markers; CRLF warnings only).
- Secret scan of new files: clean (no keys, tokens, or password material).
- SCS/Markets/control lanes: not touched by this slice.
- Migrations: single new `0005_completion_state_telemetry.sql` (idempotent via IF NOT EXISTS/constraint drops; verified on fresh + previously-migrated test DBs).

**STOP — nothing committed. Commit-ready recommendation:** stage only this slice's files (defend_coder/agent.py, agent_client.py, config.py, db.py, runs.py, telemetry.py, migrations/0005, prompts.py, bench/defendcoder_bench/*, tests/test_defend_coder_*.py, tests/test_defendcoder_bench.py, tests/test_defend_coder_telemetry.py, defendcoder-ui/{components/WorkspaceShell.tsx, components/WorkspaceShell.test.tsx, app/workspace/load-workspace.ts}) with suggested message: `feat(coder): harden agent finalization, telemetry, and benchmark policy`.