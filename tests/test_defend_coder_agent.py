from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from defend_coder.agent import CodingAgent
from defend_coder.agent_client import (
    AgentChatClient,
    AgentChatResponse,
    ModelError,
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


def _agent(tmp_path, script, max_steps=12):
    configured = tmp_path / "configured"
    configured.mkdir(exist_ok=True)
    ws = _workspace(configured / "ws")
    repo = FakeRepo([ws])
    toolkit = CoderToolkit(
        repository=repo,
        configured_root=configured,
    )
    client = FakeClient(script)
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

    assert outcome.state == "model_unavailable"
    assert "unreachable" in (outcome.error or "")
    log_events = [event for event in events if event["role"] == "log"]
    assert any(
        "model_unavailable" in (event.get("content") or "")
        for event in log_events
    )


def test_step_limit_is_handled_without_looping_forever(tmp_path):
    script = [
        AgentChatResponse(
            content=None,
            tool_calls=(ToolCall(id=f"call_{i}", name="read_logs", arguments={}),),
        )
        for i in range(10)
    ]
    agent, ws, events, logs = _agent(tmp_path, script, max_steps=3)

    outcome = agent.run(
        prompt="Loop forever.",
        account_id=ws.owner_account_id,
        workspace_id=ws.workspace_id,
        sink=lambda **kw: events.append(kw),
    )

    assert outcome.state == "succeeded"
    assert outcome.steps == 3
    assert "step limit" in (outcome.error or "")
    log_events = [event for event in events if event["role"] == "log"]
    assert any("maximum of 3" in (event.get("content") or "") for event in log_events)


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
