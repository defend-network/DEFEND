"""Benchmark summary and JSON persistence (P10, P12).

The manifest records the model, agent identity, prompt version, and
task classes so future runs (live models, different prompts) produce
comparable numbers.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from defend_coder.agent import PROMPT_VERSION
from defend_coder.telemetry import aggregate_model_calls, wall_clock_accounting

from . import BENCH_VERSION
from .grader import TaskScore
from .runner import BenchRunResult


@dataclass
class BenchSummary:
    manifest: dict[str, Any]
    scores: list[TaskScore]
    metrics: dict[str, float | int]


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def summarize(
    results: list[BenchRunResult],
    scores: list[TaskScore],
    *,
    model: str = "scripted://local",
) -> BenchSummary:
    passed = [score for score in scores if score.passed]
    total_tool_calls = sum(score.total_tool_calls for score in scores)
    total_duplicates = sum(score.duplicate_calls for score in scores)
    total_no_progress = sum(score.no_progress_calls for score in scores)
    total_recovery = sum(score.recovery_calls for score in scores)
    total_useful = sum(score.useful_calls for score in scores)
    total_edits = sum(
        score.targeted_edits + score.full_rewrites for score in scores
    )
    total_targeted = sum(score.targeted_edits for score in scores)
    total_generation_tokens = sum(
        score.generation_tokens for score in scores
    )
    total_elapsed = sum(score.elapsed_seconds for score in scores)

    steps = [score.steps for score in scores]

    all_records = [
        record for result in results for record in result.telemetry
    ]
    telemetry = aggregate_model_calls(all_records) if all_records else None

    metrics: dict[str, float | int] = {
        "tasks_total": len(scores),
        "tasks_passed": len(passed),
        "pass_rate": _rate(len(passed), len(scores)),
        "mean_steps": (
            round(statistics.mean(steps), 2) if steps else 0
        ),
        "mean_elapsed_seconds": (
            round(total_elapsed / len(scores), 2) if scores else 0
        ),
        "total_tool_calls": total_tool_calls,
        "duplicate_call_rate": _rate(total_duplicates, total_tool_calls),
        "no_progress_call_rate": _rate(
            total_no_progress, total_tool_calls
        ),
        "recovery_call_rate": _rate(total_recovery, total_tool_calls),
        "useful_call_rate": _rate(total_useful, total_tool_calls),
        "targeted_edit_rate": _rate(total_targeted, total_edits),
        "generation_tokens": total_generation_tokens,
    }
    if telemetry is not None:
        metrics["model_calls"] = int(telemetry["call_count"])
        metrics["total_request_roundtrip_seconds"] = telemetry[
            "total_request_roundtrip_seconds"
        ]
        metrics["mean_request_roundtrip_seconds"] = telemetry[
            "mean_request_roundtrip_seconds"
        ]
        metrics["p95_request_roundtrip_seconds"] = telemetry[
            "p95_request_roundtrip_seconds"
        ]

    manifest: dict[str, Any] = {
        "bench_version": BENCH_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "agent": "defendcoder-agent",
        "prompt_version": PROMPT_VERSION,
        "task_classes": [
            score.task_id for score in scores if score.task_class
        ],
        "mode": "local-scripted" if model == "scripted://local" else "live",
    }

    return BenchSummary(manifest=manifest, scores=scores, metrics=metrics)


def persist_summary(
    summary: BenchSummary,
    *,
    results_dir: Path,
    slug: str | None = None,
    results: list[BenchRunResult] | None = None,
) -> Path:
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    slug = slug or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = results_dir / f"defendcoder_bench_{slug}.json"

    results_by_task = {result.task.id: result for result in results or []}
    payload: dict[str, Any] = {
        "manifest": summary.manifest,
        "metrics": summary.metrics,
        "tasks": [
            {
                "task_id": score.task_id,
                "task_class": score.task_class,
                "passed": score.passed,
                "failures": score.failures,
                "gates": score.gates,
                "outcome_state": score.outcome_state,
                "reason": score.reason,
                "steps": score.steps,
                "phases": score.phases,
                "total_tool_calls": score.total_tool_calls,
                "unique_tools": score.unique_tools,
                "duplicate_calls": score.duplicate_calls,
                "no_progress_calls": score.no_progress_calls,
                "recovery_calls": score.recovery_calls,
                "useful_calls": score.useful_calls,
                "error_calls": score.error_calls,
                "targeted_edits": score.targeted_edits,
                "full_rewrites": score.full_rewrites,
                "generation_tokens": score.generation_tokens,
                "elapsed_seconds": score.elapsed_seconds,
                "telemetry": _task_telemetry(
                    results_by_task.get(score.task_id)
                ),
                "wall_clock": _task_wall_clock(
                    results_by_task.get(score.task_id)
                ),
            }
            for score in summary.scores
        ],
    }
    path.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    return path


def _task_telemetry(result: BenchRunResult | None) -> dict[str, Any] | None:
    if not result or not result.telemetry:
        return None
    return aggregate_model_calls(list(result.telemetry))


def _task_wall_clock(result: BenchRunResult | None) -> dict[str, Any] | None:
    if not result or not result.telemetry:
        return None
    return wall_clock_accounting(
        list(result.telemetry),
        run_seconds=result.elapsed_seconds,
        queue_wait_seconds=None,
        tool_execution_seconds=None,
        finalization_seconds=None,
        persistence_seconds=None,
    )