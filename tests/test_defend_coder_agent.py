from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from defend_coder.agent import CodingAgent
from defend_coder.agent_client import (
    AgentChatClient,
    AgentChatResponse,
    ModelError,
    ModelTimeoutError,
    ModelUnavailableError,
    ToolCall,
)
from defend_coder.model_config import CoderModelConfig
from defend_coder.repositories import WorkspaceRecord
from defend_coder.tools import CoderToolkit


class FakeClient(AgentChatClient):
    def __init__(self, script):
        super().__init__(
            CoderModelConfig(
                alias="defendcoder-heavy",
                model_name="Qwen/Qwen3-Coder-Next",
                base_url="http://127.0.0.1:8001/v1",
            )
        )
        self.script = list(script)
        self.requests: list[dict] = []

    def chat(self, messages, tools=None, **kwargs):
        self.requests.append({"messages": messages, "tools": tools})
        on_request_started = kwargs.get("on_request_started")
        if on_request_started is not None:
            on_request_started()
        if not self.script:
            raise ModelError("script exhausted")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeRepo:
    def __init__(self, workspaces):
        self._workspaces = workspaces

    def list_workspaces_for_owner(self, account_id):
        return tuple(
            workspace
            for workspace in self._workspaces
            if workspace.owner_account_id == account_id
        )


def _workspace(root):
    now = datetime.now(timezone.utc)
    return WorkspaceRecord(
        workspace_id=uuid4(),
        owner_account_id=uuid4(),
        name="ws",
        workspace_root=str(root),
        repository_url=None,
        default_branch=None,
        created_at=now,
        updated_at=now,
    )


def _agent(tmp_path, script, max_steps=12, client=None):
    configured = tmp_path / "configured"
    configured.mkdir(exist_ok=True)
    ws = _workspace(configured / "ws")
    repo = FakeRepo([ws])
    toolkit = CoderToolkit(
        repository=repo,
        configured_root=configured,
    )
    client = client or FakeClient(script)
    events: list[dict] = []

    def sink(**fields):
        events.append(fields)

    logs: list[str] = []
    agent = CodingAgent(
        client=client,
        toolkit=toolkit,
        log=logs.append,
        max_steps=max_steps,
    )
    return agent, ws, events, logs


def test_agent_creates_file_runs_tests_and_finishes(tmp_path):
    script = [
        AgentChatResponse(
            content=None,
            tool_calls=(
                ToolCall(
                    id="call_1",
                    name="write_file",
                    arguments={
                        "path": "index.html",
                        "content": "<h1>Dashboard</h1>",
                    },
                ),
            ),
        ),
        AgentChatResponse(
            content=None,
            tool_calls=(ToolCall(id="call_2", name="run_tests", arguments={}),),
        ),
        AgentChatResponse(content="Built the dashboard. Tests passed.", tool_calls=()),
    ]
    agent, ws, events, logs = _agent(tmp_path, script)

    outcome = agent.run(
        prompt="Build an ops dashboard.",
        account_id=ws.owner_account_id,
        workspace_id=ws.workspace_id,
        sink=lambda **kw: events.append(kw),
    )

    assert outcome.state == "succeeded"
    assert outcome.error is None
    assert outcome.steps == 3

    written = tmp_path / "configured" / "ws" / "index.html"
    assert written.read_text(encoding="utf-8") == "<h1>Dashboard</h1>"

    roles = [event["role"] for event in events]
    assert roles == ["assistant", "tool", "assistant", "tool", "assistant"]

    tool_events = [event for event in events if event["role"] == "tool"]
    assert tool_events[0]["tool_name"] == "write_file"
    assert tool_events[0]["kind"] == "file"
    assert tool_events[1]["tool_name"] == "run_tests"
    assert tool_events[1]["kind"] == "tests"


def test_agent_edit_followed_by_git_diff(tmp_path):
    target = tmp_path / "configured" / "ws" / "app.js"
    target.parent.mkdir(parents=True)
    target.write_text("value = 1;", encoding="utf-8")
    script = [
        AgentChatResponse(
            content="Editing the constant.",
            tool_calls=(
                ToolCall(
                    id="call_1",
                    name="edit_file",
                    arguments={
                        "path": "app.js",
                        "old_text": "value = 1",
                        "new_text": "value = 2",
                    },
                ),
            ),
        ),
        AgentChatResponse(
            content=None,
            tool_calls=(ToolCall(id="call_2", name="git_diff", arguments={}),),
        ),
        AgentChatResponse(content="Done.", tool_calls=()),
    ]
    agent, ws, events, logs = _agent(tmp_path, script)

    outcome = agent.run(
        prompt="Change the value.",
        account_id=ws.owner_account_id,
        workspace_id=ws.workspace_id,
        sink=lambda **kw: events.append(kw),
    )

    assert outcome.state == "succeeded"
    assert target.read_text(encoding="utf-8") == "value = 2;"
    kinds = [event.get("kind") for event in events if event.get("kind")]
    assert "file" in kinds
    assert "diff" in kinds


def test_tool_error_is_fed_back_to_model(tmp_path):
    script = [
        AgentChatResponse(
            content=None,
            tool_calls=(
                ToolCall(
                    id="call_1",
                    name="read_file",
                    arguments={"path": "missing.txt"},
                ),
            ),
        ),
        AgentChatResponse(content="The file is missing.", tool_calls=()),
    ]
    agent, ws, events, logs = _agent(tmp_path, script)

    outcome = agent.run(
        prompt="Read the file.",
        account_id=ws.owner_account_id,
        workspace_id=ws.workspace_id,
        sink=lambda **kw: events.append(kw),
    )

    assert outcome.state == "succeeded"
    tool_events = [event for event in events if event["role"] == "tool"]
    assert not tool_events[0]["ok"]
    assert "not a file" in tool_events[0]["tool_result"]


def test_model_unavailable_is_reported_honestly(tmp_path):
    script = [ModelUnavailableError("endpoint unreachable")]
    agent, ws, events, logs = _agent(tmp_path, script)

    outcome = agent.run(
        prompt="Do something.",
        account_id=ws.owner_account_id,
        workspace_id=ws.workspace_id,
        sink=lambda **kw: events.append(kw),
    )

    assert outcome.state == "failed"
    assert outcome.reason == "model_unavailable"
    assert "unreachable" in (outcome.error or "")
    log_events = [event for event in events if event["role"] == "log"]
    assert any(
        "model_unavailable" in (event.get("content") or "")
        for event in log_events
    )


def test_step_limit_triggers_reserved_finalization_turn(tmp_path):
    script = [
        AgentChatResponse(
            content=None,
            tool_calls=(ToolCall(id=f"call_{i}", name="read_logs", arguments={}),),
        )
        for i in range(3)
    ] + [AgentChatResponse(content="Work is done.", tool_calls=())]
    agent, ws, events, logs = _agent(tmp_path, script, max_steps=3)

    outcome = agent.run(
        prompt="Loop forever.",
        account_id=ws.owner_account_id,
        workspace_id=ws.workspace_id,
        sink=lambda **kw: events.append(kw),
    )

    assert outcome.state == "succeeded"
    assert outcome.reason == "finalized"
    assert outcome.steps == 3
    assert outcome.error is None
    log_events = [event for event in events if event["role"] == "log"]
    assert any("maximum of 3" in (event.get("content") or "") for event in log_events)
    assert any(
        "finalization" in (event.get("content") or "").lower()
        for event in log_events
    )
    finalization_request = agent._client.requests[-1]
    assert finalization_request["tools"] is None
    assert finalization_request["messages"][-1]["role"] == "user"
    assert "finalization" in finalization_request["messages"][-1]["content"].lower()


def test_step_limit_with_finalization_disabled_marks_partial(tmp_path):
    script = [
        AgentChatResponse(
            content=None,
            tool_calls=(ToolCall(id=f"call_{i}", name="read_logs", arguments={}),),
        )
        for i in range(4)
    ]
    agent, ws, events, logs = _agent(tmp_path, script, max_steps=2)
    agent._finalization_enabled = False

    outcome = agent.run(
        prompt="Loop forever.",
        account_id=ws.owner_account_id,
        workspace_id=ws.workspace_id,
        sink=lambda **kw: events.append(kw),
    )

    assert outcome.state == "partial_success"
    assert outcome.reason == "action_limit"
    assert outcome.steps == 2
    assert "maximum of 2" in (outcome.error or "")
    assert agent._client.requests[-1]["tools"] is not None


def test_step_limit_finalization_failure_marks_partial(tmp_path):
    script = [
        AgentChatResponse(
            content=None,
            tool_calls=(ToolCall(id="call_1", name="read_logs", arguments={}),),
        ),
        AgentChatResponse(
            content=None,
            tool_calls=(ToolCall(id="call_2", name="read_logs", arguments={}),),
        ),
        ModelError("finalization blew up"),
    ]
    agent, ws, events, logs = _agent(tmp_path, script, max_steps=2)

    outcome = agent.run(
        prompt="Loop forever.",
        account_id=ws.owner_account_id,
        workspace_id=ws.workspace_id,
        sink=lambda **kw: events.append(kw),
    )

    assert outcome.state == "partial_success"
    assert outcome.reason == "action_limit"
    assert outcome.steps == 2
    assert "finalization" in (outcome.error or "")


def test_step_limit_finalization_timeout_marks_partial(tmp_path):
    script = [
        AgentChatResponse(
            content=None,
            tool_calls=(ToolCall(id="call_1", name="read_logs", arguments={}),),
        ),
        ModelTimeoutError("finalization timed out"),
    ]
    agent, ws, events, logs = _agent(tmp_path, script, max_steps=1)

    outcome = agent.run(
        prompt="Loop forever.",
        account_id=ws.owner_account_id,
        workspace_id=ws.workspace_id,
        sink=lambda **kw: events.append(kw),
    )

    assert outcome.state == "partial_success"
    assert outcome.reason == "action_limit"
    assert outcome.steps == 1


def test_empty_prompt_is_rejected_before_any_model_call(tmp_path):
    agent, ws, events, logs = _agent(tmp_path, [])
    calls_before = len(agent._client.requests)

    outcome = agent.run(
        prompt="   ",
        account_id=ws.owner_account_id,
        workspace_id=ws.workspace_id,
        sink=lambda **kw: events.append(kw),
    )

    assert outcome.state == "failed"
    assert "prompt" in (outcome.error or "")
    assert outcome.reason == "invalid_prompt"
    assert len(agent._client.requests) == calls_before


def test_system_prompt_precedes_user_prompt(tmp_path):
    script = [AgentChatResponse(content="ok", tool_calls=())]
    agent, ws, events, logs = _agent(tmp_path, script)

    agent.run(
        prompt="First task.",
        account_id=ws.owner_account_id,
        workspace_id=ws.workspace_id,
        sink=lambda **kw: events.append(kw),
    )

    first_request = agent._client.requests[0]["messages"]
    assert first_request[0]["role"] == "system"
    assert "DEFENDcoder" in first_request[0]["content"]
    assert first_request[1] == {"role": "user", "content": "First task."}
    assert agent._client.requests[0]["tools"]


def test_tool_history_is_visible_to_subsequent_requests(tmp_path):
    script = [
        AgentChatResponse(
            content=None,
            tool_calls=(ToolCall(id="c1", name="write_file", arguments={
                "path": "x.txt", "content": "hi",
            }),),
        ),
        AgentChatResponse(content="done", tool_calls=()),
    ]
    agent, ws, events, logs = _agent(tmp_path, script)

    agent.run(
        prompt="Write x.txt.",
        account_id=ws.owner_account_id,
        workspace_id=ws.workspace_id,
        sink=lambda **kw: events.append(kw),
    )

    second = agent._client.requests[1]["messages"]
    assert second[2]["role"] == "assistant"
    assert second[2]["tool_calls"][0]["id"] == "c1"
    assert second[3]["role"] == "tool"
    assert second[3]["tool_call_id"] == "c1"
    assert "wrote" in second[3]["content"]


def test_long_generation_phase_visibility_and_tool_continuation(tmp_path):
    """G: a long healthy generation surfaces MODEL_GENERATING and the
    agent loop continues into tool execution."""
    phases: list[str] = []
    agent, ws, events, logs = _agent(
        tmp_path,
        [
            AgentChatResponse(
                content=None,
                tool_calls=(
                    ToolCall(
                        id="call_1",
                        name="write_file",
                        arguments={
                            "path": "index.html",
                            "content": "<h1>Dashboard</h1>",
                        },
                    ),
                ),
            ),
            AgentChatResponse(
                content="Built the dashboard.", tool_calls=()
            ),
        ],
    )
    agent._phase_sink = phases.append

    outcome = agent.run(
        prompt="Build an ops dashboard.",
        account_id=ws.owner_account_id,
        workspace_id=ws.workspace_id,
        sink=lambda **kw: events.append(kw),
    )

    assert outcome.state == "succeeded"
    assert outcome.steps == 2
    assert phases == [
        "waiting_for_model",
        "model_generating",
        "executing_tool",
        "waiting_for_model_after_tool",
        "waiting_for_model_after_tool",
        "model_generating",
    ]
    written = tmp_path / "configured" / "ws" / "index.html"
    assert written.read_text(encoding="utf-8") == "<h1>Dashboard</h1>"


def test_cancel_between_steps_aborts_cleanly(tmp_path):
    """H: cancellation is honored at step boundaries without corrupting
    the completed work."""
    checks = {"calls": 0}
    agent, ws, events, logs = _agent(
        tmp_path,
        [
            AgentChatResponse(
                content=None,
                tool_calls=(
                    ToolCall(
                        id="call_1",
                        name="write_file",
                        arguments={
                            "path": "index.html",
                            "content": "<h1>Dashboard</h1>",
                        },
                    ),
                ),
            ),
            AgentChatResponse(content="Done.", tool_calls=()),
        ],
    )

    def cancelled():
        checks["calls"] += 1
        return checks["calls"] > 1

    agent._is_cancelled = cancelled

    outcome = agent.run(
        prompt="Build an ops dashboard.",
        account_id=ws.owner_account_id,
        workspace_id=ws.workspace_id,
        sink=lambda **kw: events.append(kw),
    )

    assert outcome.state == "cancelled"
    assert outcome.error == "cancelled by user"
    assert outcome.steps == 1
    written = tmp_path / "configured" / "ws" / "index.html"
    assert written.read_text(encoding="utf-8") == "<h1>Dashboard</h1>"
    log_events = [event for event in events if event["role"] == "log"]
    assert any(
        "cancelled by user" in (event.get("content") or "")
        for event in log_events
    )


class FakeMonotonic:
    def __init__(self, start: float = 0.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class AdvancingClient(FakeClient):
    def __init__(self, script, clock: FakeMonotonic):
        super().__init__(script)
        self.clock = clock

    def chat(self, messages, tools=None, **kwargs):
        result = super().chat(messages, tools=tools, **kwargs)
        self.clock.advance(31.0)
        return result


def test_wall_clock_limit_stops_a_too_long_run(monkeypatch, tmp_path):
    """The run wall-clock guard stops a run whose total execution exceeds
    max_loop_seconds even when individual calls stay under budget."""
    clock = FakeMonotonic()
    monkeypatch.setattr("defend_coder.agent.time.monotonic", clock)
    client = AdvancingClient(
        [
            AgentChatResponse(
                content=None,
                tool_calls=(
                    ToolCall(
                        id="call_1",
                        name="write_file",
                        arguments={
                            "path": "x.txt",
                            "content": "hi",
                        },
                    ),
                ),
            ),
            AgentChatResponse(content="Done.", tool_calls=()),
        ],
        clock,
    )
    agent, ws, events, logs = _agent(tmp_path, [], client=client)
    agent._max_loop_seconds = 30.0

    outcome = agent.run(
        prompt="Do a thing.",
        account_id=ws.owner_account_id,
        workspace_id=ws.workspace_id,
        sink=lambda **kw: events.append(kw),
    )

    assert outcome.state == "partial_success"
    assert "wall-clock limit" in (outcome.error or "")
    assert outcome.reason == "wall_clock_limit"
    assert outcome.steps == 1
    written = tmp_path / "configured" / "ws" / "x.txt"
    assert written.read_text(encoding="utf-8") == "hi"
