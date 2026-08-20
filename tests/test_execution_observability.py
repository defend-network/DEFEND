"""Execution trace observability: redacted step summaries expose tool usage."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from execution_protocol import PlanStatus, StepExecution, StepStatus


def _fake_execution(steps, status="succeeded", tool_calls=1, cost=0.0):
    from types import SimpleNamespace

    return SimpleNamespace(
        status=PlanStatus(status),
        tool_calls=tool_calls,
        cost_usd=cost,
        steps={s.step_id: s for s in steps},
    )


def _step(
    step_id,
    tool_name,
    status="succeeded",
    ok=True,
    error_code=None,
    attempts=1,
    latency_seconds=1.25,
):
    err = None
    if error_code:
        from types import SimpleNamespace

        err = SimpleNamespace(code=SimpleNamespace(value=error_code))
    result = None
    if ok is not None:
        from types import SimpleNamespace

        result = SimpleNamespace(ok=ok, error=err)
    start = datetime.now(timezone.utc)
    finish = start + timedelta(seconds=latency_seconds)
    return StepExecution(
        step_id=step_id,
        call_id=f"call_{step_id}",
        tool_name=tool_name,
        status=StepStatus(status),
        started_at=start,
        finished_at=finish,
        attempts=attempts,
        tool_result=result,
    )


def test_execution_summary_redacts_arguments_and_results():
    from api_server import _execution_summary

    ex = _fake_execution(
        [
            _step("s1", "calculator.evaluate", ok=True, attempts=1),
            _step("s2", "time.now", status="failed", ok=False, error_code="invalid_input"),
        ],
        status="partial",
        tool_calls=2,
        cost=0.000042,
    )
    summary = _execution_summary(ex)
    assert summary["plan_status"] == "partial"
    assert summary["tool_calls"] == 2
    assert [s["tool_name"] for s in summary["steps"]] == [
        "calculator.evaluate",
        "time.now",
    ]
    assert summary["steps"][0]["ok"] is True
    assert summary["steps"][1]["error_code"] == "invalid_input"
    assert summary["steps"][0]["latency_ms"] == 1250.0
    assert all("arguments" not in s for s in summary["steps"])
    assert all("tool_result" not in s for s in summary["steps"])


def test_execution_summary_none_handling():
    from api_server import _execution_summary

    assert _execution_summary(None) is None


def test_step_execution_carries_tool_name():
    step = _step("s1", "calculator.evaluate", ok=True)
    assert step.tool_name == "calculator.evaluate"