# DEFENDcoder Hardening Slice — Delivery Report

Slice: terminal semantics (P1–P4), benchmark harness (P5–P10/P12), evidence analysis (P11), UI (P13), regression (P15).
Owner directive: hash-pinned system prompt (OWNER_DIRECTIVE_SHA256=`78ab8899ca968efe50bee4bc57e6ee2675849be84af3e07e99c8d22826832442`, FINAL_SYSTEM_PROMPT_SHA256=`3a970bc7f1726732ffd40b64e96159fbbba339b29beb79860efe16e220098474`, PROMPT_VERSION=`2026-08-18.v1`, SYSTEM_MESSAGE_COUNT=1). Source preserved unchanged.

## BENCH_TASKS / CLASSES / LOCAL_RUNS
10 tasks, 10 classes (A–J), all run locally (scripted client, deterministic, no model compute):

| Class | Task | Result |
|---|---|---|
| A | Scratch implementation from spec | PASS |
| B | Fix failing tests (TDD loop) | PASS |
| C | Bug fix from repro steps | PASS |
| D | Targeted edit of existing code | PASS |
| E | Refactor without behavior change | PASS |
| F | Documentation update | PASS |
| G | Small utility script | PASS |
| H | Configuration file change | PASS |
| I | Inspection and report only | PASS |
| J | Multi-file feature assembly | PASS |

Local runs: 10/10 PASS (exit 0). Report: `bench/results/defendcoder_bench_20260818T215537Z.json`.

## RATES (local, aggregate)
- pass_rate: 1.00 (10/10) — mean steps 3.6
- targeted_edit_rate: 1.00 (all 6 edits to pre-existing files preserved >=50% of original lines)
- duplicate_call_rate: 0.04 (1 duplicate of 24 tool calls)
- no_progress_call_rate: 0.00
- recovery_call_rate: 0.04 (1 recovery after an expected-error test run)
- useful_call_rate: 0.92

## Quality gates (per task)
gate_completed, gate_reason (natural_completion/finalized), gate_files, gate_forbidden (protected files byte-identical), gate_inspect, gate_no_errors (expect_error escapes allowed for intentionally-failing pre-fix test runs).

## Product changes delivered
- P1: terminal `reason` for every run (natural_completion, finalized, step_limit, wall_clock_limit, model_timeout, model_unavailable, model_error, user_cancel, internal_error, invalid_prompt) — DB migration 0004 (`reason` column, `finalizing` phase), agent/runner/API/UI wiring.
- P2: reserved finalization turn (single bounded non-tool turn after budget exhaustion; FINALIZATION_MESSAGE; tool_calls in it → incomplete_step_limit).
- P3: policy knobs CODER_MAX_STEPS (12, 1–100), CODER_FINALIZATION_ENABLED, CODER_FINALIZATION_TIMEOUT_SECONDS (600, 30–3600), CODER_MAX_RUN_SECONDS (2400, 60–14400); `GET /v1/agent/policy`.
- P7: targeted-edit vs full-rewrite classification (fraction of original lines preserved >= 0.5).
- P13: UI shows `finalizing` phase and terminal reason on failed runs.
- P15: full regression — **1723 passed, 22 skipped, 0 failed** (120 files, thread-exception warnings escalated to errors). Includes 202 tests in the coder slice.
- Real bug fixed (found by bench): `write_file`/`edit_file` now drop stale `__pycache__/*.pyc` — Python's pyc freshness check compares source mtimes in whole seconds, so an edit landing in the same second as an earlier compile left stale bytecode that pytest imported (deterministic-adjacent flake, 1-in-5 rate under load; root-caused via in-process repro).
- Bench harness: `bench/defendcoder_bench/` (tasks, scripted client, runner, grader, report, cli) + `tests/test_defendcoder_bench.py` (10 tests) + `tests/test_defend_coder_settings.py` (6 tests) + 2 pyc-invalidation tests.

## P11 EVIDENCE (run f95795ae, pre-migration dev DB)
- 12 steps, status succeeded, 1530s wall (~25.5 min) for a multi-file dashboard build.
- assistant text avg 72.6 chars (total ~726 chars ≈ 180 tokens) — the model spends its budget on work, not narration.
- tool_arguments avg 3,988 chars, max 16,836 — ~47.9 KB (~12K tokens) of tool payload per run; context grows ~4 KB/step.
- mean inter-message gap 63.3s, max 543.9s ≈ one near-full 4096-token generation at ~7.5 tok/s — per-step generation is the bottleneck; the 4096 max_tokens cap is binding only on rare steps.

## PAID_COMPUTE_USED
NO (P14 honored: local scripted bench only, no live-model runs).

## STOP BEFORE COMMIT
Changes are staged in the worktree only. Nothing committed. Awaiting owner review before commit.