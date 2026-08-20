"""Tests for per-model-call telemetry and wall-clock accounting (P2/P2A/P2B)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from defend_coder.agent import (
    AgentChatResponse,
    CodingAgent,
)
from defend_coder.agent_client import ToolCall
from defend_coder.telemetry import (
    ModelCallRecord,
    aggregate_model_calls,
    build_call_record,
    wall_clock_accounting,
)
from defend_coder.tools import CoderToolkit


def _record(**overrides) -> ModelCallRecord:
    now = datetime.now(timezone.utc)
    base: dict = {
        "step": 1,
        "phase": "tool_work",
        "started_at": now,
        "finished_at": now,
        "request_roundtrip_seconds": 10.0,
        "input_tokens": 100,
        "output_tokens": 50,
        "total_tokens": 150,
        "finish_reason": "stop",
        "max_tokens_requested": 4096,
        "tool_calls_requested": 1,
        "assistant_visible_chars": 200,
        "assistant_visible_tokens": 50,
        "context_tokens": 100,
        "remaining_action_budget": 5,
    }
    base.update(overrides)
    return ModelCallRecord(**base)


def test_build_call_record_maps_provider_usage() -> None:
    record = build_call_record(
        step=2,
        phase="tool_work",
        roundtrip_seconds=8.0,
        max_tokens_requested=4096,
        tool_calls_requested=1,
        remaining_action_budget=3,
        content="short answer",
        usage={"prompt_tokens": 42, "completion_tokens": 17, "total_tokens": 59},
        finish_reason="stop",
    )
    assert record.input_tokens == 42
    assert record.output_tokens == 17
    assert record.total_tokens == 59
    assert record.context_tokens == 42
    assert record.assistant_visible_chars == 12
    assert record.tokens_per_second == pytest.approx(17 / 8.0, rel=0.01)
    assert record.error_class is None


def test_build_call_record_never_fabricates_tokens() -> None:
    record = build_call_record(
        step=1,
        phase="tool_work",
        roundtrip_seconds=5.0,
        max_tokens_requested=4096,
        tool_calls_requested=0,
        remaining_action_budget=4,
        content="hi",
        usage=None,
        finish_reason=None,
    )
    assert record.input_tokens is None
    assert record.output_tokens is None
    assert record.total_tokens is None
    assert record.context_tokens is None
    assert record.tokens_per_second is None
    assert record.assistant_visible_tokens is None


def test_build_call_record_marks_errors() -> None:
    record = build_call_record(
        step=1,
        phase="tool_work",
        roundtrip_seconds=90.0,
        max_tokens_requested=4096,
        tool_calls_requested=0,
        remaining_action_budget=4,
        error_class="ModelTimeoutError",
    )
    assert record.error_class == "ModelTimeoutError"
    assert record.tokens_per_second is None


def test_aggregate_totals_and_percentiles() -> None:
    records = [
        _record(step=1, request_roundtrip_seconds=1.0, output_tokens=10),
        _record(step=2, request_roundtrip_seconds=2.0, output_tokens=20),
        _record(step=3, request_roundtrip_seconds=3.0, output_tokens=30),
        _record(step=4, request_roundtrip_seconds=4.0, output_tokens=40),
    ]
    agg = aggregate_model_calls(records)
    assert agg["call_count"] == 4
    assert agg["total_request_roundtrip_seconds"] == 10.0
    assert agg["total_output_tokens"] == 100
    assert agg["max_request_roundtrip_seconds"] == 4.0
    assert agg["mean_output_tokens"] == 25.0
    assert agg["max_output_tokens"] == 40
    assert agg["finish_reasons"] == {"stop": 4}
    assert agg["error_classes"] == {"ok": 4}
    assert agg["generation_seconds_available"] is False


def test_aggregate_empty_is_not_available() -> None:
    agg = aggregate_model_calls([])
    assert agg["call_count"] == 0
    assert agg["total_output_tokens"] is None
    assert agg["mean_request_roundtrip_seconds"] is None


def test_wall_clock_accounting_does_not_double_count() -> None:
    records = [_record(request_roundtrip_seconds=10.0)]
    accounting = wall_clock_accounting(
        records,
        run_seconds=30.0,
        queue_wait_seconds=1.0,
        tool_execution_seconds=5.0,
        finalization_seconds=None,
        persistence_seconds=2.0,
    )
    assert accounting["total_wall_seconds"] == 30.0
    assert accounting["request_roundtrip_seconds"] == 10.0
    assert accounting["tool_execution_seconds"] == 5.0
    assert accounting["persistence_seconds"] == 2.0
    assert accounting["queue_wait_seconds"] == 1.0
    accounted = 1.0 + 10.0 + 5.0 + 2.0
    assert accounting["unattributed_seconds"] == 30.0 - accounted
    assert accounting["accounted_wall_clock_percent"] == round(
        accounted / 30.0 * 100, 1
    )
    assert accounting["model_generation_seconds"] is None
    assert accounting["model_generation_seconds_available"] is False


def test_wall_clock_accounting_finalization_bucket() -> None:
    records = [
        _record(step=1, phase="tool_work", request_roundtrip_seconds=3.0),
        _record(step=2, phase="finalizing", request_roundtrip_seconds=7.0),
    ]
    accounting = wall_clock_accounting(
        records,
        run_seconds=10.0,
        queue_wait_seconds=0.0,
        tool_execution_seconds=0.0,
        finalization_seconds=None,
        persistence_seconds=0.0,
    )
    assert accounting["finalization_seconds"] == 7.0
    assert accounting["request_roundtrip_seconds"] == 10.0


def _agent_with_spy(
    script, tmp_path, max_steps=3
) -> tuple[CodingAgent, list, list]:
    from bench.defendcoder_bench.client import ScriptedBenchClient
    from bench.defendcoder_bench.runner import BenchRepository
    from uuid import uuid4
    from pathlib import Path

    workspace_root = Path(tmp_path)
    workspace = workspace_root / "ws"
    workspace.mkdir(exist_ok=True)
    from defend_coder.repositories import WorkspaceRecord

    record = WorkspaceRecord(
        workspace_id=uuid4(),
        owner_account_id=uuid4(),
        name="ws",
        workspace_root=str(workspace.resolve()),
        repository_url=None,
        default_branch=None,
        created_at=None,
        updated_at=None,
    )
    toolkit = CoderToolkit(
        repository=BenchRepository(record),
        configured_root=workspace_root.resolve(),
    )
    client = ScriptedBenchClient(script)
    events: list = []
    telemetry: list = []
    agent = CodingAgent(
        client=client,
        toolkit=toolkit,
        log=lambda _line: None,
        max_steps=max_steps,
        phase_sink=lambda _phase: None,
        telemetry_sink=telemetry.append,
    )
    return agent, record, events, telemetry


def test_agent_emits_telemetry_per_call(tmp_path) -> None:
    script = [
        {
            "tool": "write_file",
            "arguments": {"path": "a.txt", "content": "x\n"},
            "usage": {"input": 120, "output": 30},
        },
        {"text": "done.", "usage": {"input": 130, "output": 12}},
    ]
    agent, record, events, telemetry = _agent_with_spy(script, tmp_path)
    outcome = agent.run(
        prompt="Write a file.",
        account_id=record.owner_account_id,
        workspace_id=record.workspace_id,
        sink=lambda **kw: events.append(kw),
    )
    assert outcome.state == "succeeded"
    assert len(telemetry) == 2
    first, second = telemetry
    assert first.phase == "tool_work"
    assert first.step == 1
    assert first.output_tokens == 30
    assert first.input_tokens == 120
    assert second.phase == "tool_work"
    assert second.step == 2
    assert second.tool_calls_requested == 0
    assert second.remaining_action_budget == 1


def test_agent_phase_budgets_default_and_override() -> None:
    from bench.defendcoder_bench.client import ScriptedBenchClient
    from defend_coder.agent_client import AgentChatClient
    from defend_coder.model_config import CoderModelConfig

    client = AgentChatClient(
        CoderModelConfig(
            alias="x",
            model_name="x",
            base_url="http://127.0.0.1:1/v1",
        )
    )
    from unittest.mock import MagicMock

    toolkit = MagicMock(spec=CoderToolkit)
    agent = CodingAgent(
        client=client,
        toolkit=toolkit,
        max_steps=12,
    )
    assert agent._max_tokens_for("tool_work") == 4096
    assert agent._max_tokens_for("error_recovery") == 2048
    assert agent._max_tokens_for("finalizing") == 2048

    agent = CodingAgent(
        client=client,
        toolkit=toolkit,
        max_steps=12,
        phase_max_tokens={
            "tool_work": 512,
            "error_recovery": 1000,
            "final_synthesis": 100,
        },
    )
    assert agent._max_tokens_for("tool_work") == 512
    assert agent._max_tokens_for("error_recovery") == 1000
    assert agent._max_tokens_for("finalizing") == 256  # raised to minimum


def test_agent_error_recovery_phase_budget_applied(tmp_path) -> None:
    script = [
        {
            "tool": "run_command",
            "arguments": {
                "command": "python -c 'raise SystemExit(1)'",
            },
        },
        {"text": "fixed."},
    ]
    agent, record, events, telemetry = _agent_with_spy(
        script, tmp_path, max_steps=3
    )
    agent._phase_max_tokens["error_recovery"] = 999
    outcome = agent.run(
        prompt="Reproduce the failure.",
        account_id=record.owner_account_id,
        workspace_id=record.workspace_id,
        sink=lambda **kw: events.append(kw),
    )
    assert len(telemetry) == 2
    # second call follows an error and must use the error_recovery phase
    assert telemetry[1].phase == "error_recovery"
    assert telemetry[1].max_tokens_requested == 999