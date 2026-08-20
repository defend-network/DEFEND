"""Tests for the DEFENDcoder benchmark harness (P5-P10/P12).

These tests run the scripted client and the real CodingAgent without a
database: the BenchRepository satisfies the toolkit's workspace
ownership lookups.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from bench.defendcoder_bench import BENCH_VERSION
from bench.defendcoder_bench.grader import score_task
from bench.defendcoder_bench.v1_freeze import (
    MANIFEST_SHA256,
    verify_manifest,
)
from bench.defendcoder_bench.report import persist_summary, summarize
from bench.defendcoder_bench.runner import run_task
from bench.defendcoder_bench.tasks import (
    B_FIX_FAILING_TESTS,
    C_BUG_REPRO,
    D_TARGETED_EDIT,
    F_DOCS,
    TASKS,
    Task,
    materialize_workspace,
    workspace_hashes,
)


@pytest.fixture
def bench_root(tmp_path: Path) -> Path:
    return tmp_path


def _run(task: Task, bench_root: Path):
    return run_task(task, workspace_root=bench_root)


def test_materialize_writes_files_and_hashes(bench_root: Path) -> None:
    hashes = materialize_workspace(
        bench_root / "ws", {"a.txt": "hello\n", "nested/b.txt": "x\n"}
    )
    assert (bench_root / "ws" / "a.txt").read_text(
        encoding="utf-8"
    ) == "hello\n"
    assert (bench_root / "ws" / "nested" / "b.txt").is_file()
    assert "a.txt" in hashes
    assert "nested/b.txt" in hashes
    assert workspace_hashes(
        bench_root / "ws", ["a.txt"]
    ) == {"a.txt": hashes["a.txt"]}


def test_materialize_preserves_unix_newlines(bench_root: Path) -> None:
    content = "line one\nline two\n"
    materialize_workspace(bench_root / "ws", {"f.txt": content})
    raw = (bench_root / "ws" / "f.txt").read_bytes()
    assert b"\r\n" not in raw


def test_scripted_task_passes(bench_root: Path) -> None:
    result = _run(TASKS[0], bench_root)
    assert result.error is None
    assert result.outcome is not None
    assert result.outcome.state == "succeeded"
    assert result.outcome.reason == "natural_completion"
    score = score_task(
        result, original_hashes=result.original_hashes
    )
    assert score.passed
    assert score.total_tool_calls == 2
    assert score.unique_tools == 2


def test_scripted_bug_fix_allows_expected_error(bench_root: Path) -> None:
    result = _run(B_FIX_FAILING_TESTS, bench_root)
    score = score_task(
        result, original_hashes=result.original_hashes
    )
    if score.error_calls != 1:
        for event in result.events:
            if event.get("role") == "tool":
                print(
                    "DBG",
                    event.get("tool_name"),
                    "ok=",
                    event.get("ok"),
                    repr(str(event.get("tool_result") or "")),
                )
    assert result.expected_error_calls == 1
    assert score.error_calls == 1
    assert score.passed


def test_forbidden_gate_detects_modified_file(bench_root: Path) -> None:
    result = _run(C_BUG_REPRO, bench_root)
    score = score_task(
        result, original_hashes=result.original_hashes
    )
    assert score.gates["gate_forbidden"]
    assert (result.workspace / "notes.txt").is_file()


def test_missing_expected_content_fails_files_gate(
    bench_root: Path,
) -> None:
    broken = Task(
        id="z_broken",
        task_class="Z",
        title="broken",
        prompt="produce fib.py",
        expected={"fib.py": ["def nth_fib"]},
        script=[
            {
                "tool": "write_file",
                "arguments": {"path": "fib.py", "content": "x = 1\n"},
            },
            {"text": "done"},
        ],
    )
    result = _run(broken, bench_root)
    score = score_task(
        result, original_hashes=result.original_hashes
    )
    assert not score.passed
    assert "files" in score.failures


def test_duplicate_calls_counted(bench_root: Path) -> None:
    task = Task(
        id="z_dupes",
        task_class="Z",
        title="dupes",
        prompt="make dupes",
        expected={"dup.py": ["x"]},
        script=[
            {
                "tool": "write_file",
                "arguments": {"path": "dup.py", "content": "x = 1\n"},
            },
            {
                "tool": "write_file",
                "arguments": {"path": "dup.py", "content": "x = 1\n"},
            },
            {
                "tool": "write_file",
                "arguments": {"path": "dup.py", "content": "x = 1\n"},
            },
            {"text": "done"},
        ],
    )
    result = _run(task, bench_root)
    score = score_task(
        result, original_hashes=result.original_hashes
    )
    assert score.total_tool_calls == 3
    assert score.duplicate_calls == 2
    assert score.useful_calls == 1


def test_summary_and_persist(bench_root: Path) -> None:
    results = [_run(task, bench_root) for task in TASKS]
    scores = [
        score_task(result, original_hashes=result.original_hashes)
        for result in results
    ]
    summary = summarize(results, scores)
    assert summary.metrics["tasks_total"] == len(TASKS)
    assert summary.metrics["tasks_passed"] == len(TASKS)
    assert summary.metrics["pass_rate"] == 1.0
    assert summary.manifest["bench_version"] == BENCH_VERSION
    assert summary.manifest["model"] == "scripted://local"

    path = persist_summary(
        summary, results_dir=bench_root / "results", results=results
    )
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["manifest"]["prompt_version"]
    assert payload["metrics"]["pass_rate"] == 1.0
    assert len(payload["tasks"]) == len(TASKS)
    task_ids = [entry["task_id"] for entry in payload["tasks"]]
    assert task_ids == [task.id for task in TASKS]


def test_fixture_edit_tasks_are_targeted(bench_root: Path) -> None:
    for task in (D_TARGETED_EDIT, F_DOCS):
        result = _run(task, bench_root)
        score = score_task(
            result, original_hashes=result.original_hashes
        )
        assert score.targeted_edits >= 1
        assert score.full_rewrites == 0


def test_cli_exit_zero(tmp_path: Path) -> None:
    from bench.defendcoder_bench.cli import run_local

    assert run_local(tmp_path / "results") == 0


def test_v1_manifest_frozen() -> None:
    checks = verify_manifest()
    assert all(checks.values()), checks


def test_v1_manifest_pins_current_sources() -> None:
    import hashlib

    from bench.defendcoder_bench.v1_freeze import manifest_payload

    payload = manifest_payload()
    live = {task.id: task for task in TASKS}
    assert set(live) == {entry["id"] for entry in payload["tasks"]}
    for entry in payload["tasks"]:
        task = live[entry["id"]]
        for rel, content in task.files.items():
            assert (
                hashlib.sha256(content.encode("utf-8")).hexdigest()
                == entry["files"][rel]
            ), f"{entry['id']} fixture {rel} drifted from V1"
        assert task.max_steps == entry["max_steps"]
        assert task.task_class == entry["task_class"]
    assert payload["manifest_sha256"] == MANIFEST_SHA256