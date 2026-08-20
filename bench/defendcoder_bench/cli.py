"""DEFENDcoder bench CLI.

Runs all tasks in local scripted mode (deterministic, no model, no
paid compute - P14) and writes a JSON report. Reserved for future
live-model runs with explicit owner approval:

    python -m bench.defendcoder_bench.cli --local
    python -m bench.defendcoder_bench.cli --live --base-url ... --model ...
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from .grader import score_task
from .report import persist_summary, summarize
from .runner import run_task
from .tasks import TASKS, cleanup_workspace


def run_local(results_dir: Path) -> int:
    workspace_root = Path(
        tempfile.mkdtemp(prefix="defendcoder_bench_")
    )
    results: list = []
    scores = []
    try:
        for task in TASKS:
            result = run_task(
                task,
                workspace_root=workspace_root,
            )
            results.append(result)
            score = score_task(
                result,
                original_hashes=result.original_hashes,
            )
            scores.append(score)
            status = "PASS" if score.passed else "FAIL"
            print(
                f"[{status}] {task.task_class} {task.id}: "
                f"state={score.outcome_state} reason={score.reason} "
                f"steps={score.steps} tool_calls={score.total_tool_calls}",
                file=sys.stderr,
            )
            if not score.passed:
                print(
                    f"        failed gates: {', '.join(score.failures)}",
                    file=sys.stderr,
                )
    finally:
        cleanup_workspace(workspace_root)

    summary = summarize(results, scores)
    path = persist_summary(
        summary, results_dir=results_dir, results=results
    )
    print(f"benchmark report written to {path}")
    print(f"pass rate: {summary.metrics['pass_rate']:.0%} "
          f"({summary.metrics['tasks_passed']}/"
          f"{summary.metrics['tasks_total']})")
    print(f"mean steps: {summary.metrics['mean_steps']}")
    print(f"targeted edit rate: {summary.metrics['targeted_edit_rate']:.0%}")
    print(f"duplicate call rate: "
          f"{summary.metrics['duplicate_call_rate']:.0%}")
    print(f"no-progress call rate: "
          f"{summary.metrics['no_progress_call_rate']:.0%}")
    print(f"recovery call rate: {summary.metrics['recovery_call_rate']:.0%}")
    print(f"useful call rate: {summary.metrics['useful_call_rate']:.0%}")

    return 0 if summary.metrics["pass_rate"] == 1.0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="defendcoder-bench",
        description=(
            "DEFENDcoder benchmark harness (local scripted mode only; "
            "live mode requires explicit owner approval)"
        ),
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path("bench") / "results",
        help="directory for JSON reports (default: bench/results)",
    )
    args = parser.parse_args(argv)

    return run_local(args.results_dir)


if __name__ == "__main__":
    raise SystemExit(main())