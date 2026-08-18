from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Callable
from uuid import UUID

from .agent_client import (
    AgentChatClient,
    ModelError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from .tools import CoderToolkit

SYSTEM_PROMPT = (
    "You are DEFENDcoder, an autonomous coding agent inside the "
    "DEFEND platform. You work inside one workspace directory.\n\n"
    "Rules:\n"
    "- Always inspect the workspace first (list_files, read_file) before "
    "writing or editing anything.\n"
    "- Prefer targeted edit_file over rewriting whole files when "
    "modifying existing code; only write_file when creating a new file "
    "or replacing one entirely.\n"
    "- Never invent files, functions, or test results. Verify with "
    "read_file / run_tests and report honestly.\n"
    "- After implementing or fixing something, run the tests and report "
    "the outcome.\n"
    "- Show what changed: run git_diff and summarize it, or say the "
    "workspace is not under version control.\n"
    "- Keep every path inside the workspace root. Never touch anything "
    "outside it.\n"
    "- When a tool reports an error, read the error, diagnose the cause, "
    "fix it, and retry rather than giving up.\n"
    "- Do not fabricate a successful test run. Report the real exit "
    "codes and output.\n"
    "- If the workspace is empty, say so and propose the file structure "
    "you will create.\n\n"
    "When done, give a short final summary: what you built or changed "
    "(file paths), how you verified it (commands and results), and "
    "anything the user should know."
)


@dataclass(frozen=True)
class AgentOutcome:
    state: str
    error: str | None
    steps: int


class CodingAgent:
    """Step-by-step tool-calling agent loop.

    Runs synchronously inside a caller-owned worker thread. Every step is
    reported through the sink so the run can be persisted and streamed to
    the UI. Failures are honest: model problems surface as
    model_unavailable, never as a fake success.
    """

    def __init__(
        self,
        *,
        client: AgentChatClient,
        toolkit: CoderToolkit,
        log: Callable[[str], None] | None = None,
        max_steps: int = 12,
        max_loop_seconds: float = 900.0,
    ) -> None:
        if not isinstance(client, AgentChatClient):
            raise TypeError("client must be an AgentChatClient")
        if not isinstance(toolkit, CoderToolkit):
            raise TypeError("toolkit must be a CoderToolkit")
        self._client = client
        self._toolkit = toolkit
        self._log = log or (lambda _line: None)
        self._max_steps = max(1, int(max_steps))
        self._max_loop_seconds = max(30.0, float(max_loop_seconds))

    def run(
        self,
        *,
        prompt: str,
        account_id: UUID,
        workspace_id: UUID,
        sink: Callable[..., None],
    ) -> AgentOutcome:
        if not isinstance(prompt, str) or not prompt.strip():
            sink(
                role="log",
                content="error: a prompt is required to start a run",
                kind="log",
            )
            return AgentOutcome(
                state="failed",
                error="a prompt is required",
                steps=0,
            )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        tool_schemas = self._toolkit.schema()
        steps = 0

        self._log(f"agent: run started (max {self._max_steps} steps)")
        try:
            while steps < self._max_steps:
                steps += 1
                response = self._client.chat(
                    messages,
                    tools=tool_schemas,
                )
                self._log(
                    f"agent: step {steps} "
                    f"(tool_calls={len(response.tool_calls)})"
                )

                if not response.tool_calls:
                    final = response.content or "Done."
                    sink(
                        role="assistant",
                        content=final,
                    )
                    self._log("agent: final answer produced")
                    return AgentOutcome(
                        state="succeeded",
                        error=None,
                        steps=steps,
                    )

                assistant_message: dict[str, Any] = {
                    "role": "assistant",
                    "content": response.content or "",
                }
                if response.tool_calls:
                    assistant_message["tool_calls"] = [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": _dump_arguments(call.arguments),
                            },
                        }
                        for call in response.tool_calls
                    ]
                messages.append(assistant_message)

                sink(
                    role="assistant",
                    content=response.content,
                    tool_calls=[
                        {
                            "id": call.id,
                            "name": call.name,
                            "arguments": call.arguments,
                        }
                        for call in response.tool_calls
                    ],
                )

                for call in response.tool_calls:
                    self._log(
                        f"agent: executing tool {call.name} "
                        f"(step {steps})"
                    )
                    result = self._toolkit.execute(
                        call.name,
                        call.arguments,
                        account_id=account_id,
                        workspace_id=workspace_id,
                    )
                    self._log(
                        f"agent: tool {call.name} -> "
                        f"{'ok' if result.ok else 'error'}"
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": result.content,
                        }
                    )
                    sink(
                        role="tool",
                        tool_call_id=call.id,
                        tool_name=call.name,
                        tool_arguments=call.arguments,
                        tool_result=result.content,
                        kind=result.kind,
                        ok=result.ok,
                    )

            sink(
                role="log",
                content=(
                    f"reached the maximum of {self._max_steps} agent steps; "
                    "the task may be incomplete."
                ),
                kind="log",
            )
            self._log("agent: step limit reached")
            return AgentOutcome(
                state="succeeded",
                error="step limit reached",
                steps=steps,
            )
        except ModelTimeoutError as error:
            return self._fail(
                sink,
                "model_timeout",
                f"model request timed out: {error}",
                steps,
            )
        except ModelUnavailableError as error:
            return self._fail(
                sink,
                "model_unavailable",
                f"model endpoint is unreachable: {error}",
                steps,
            )
        except ModelError as error:
            return self._fail(
                sink,
                "model_error",
                f"model returned an unusable response: {error}",
                steps,
            )

    def _fail(
        self,
        sink: Callable[..., None],
        state: str,
        detail: str,
        steps: int,
    ) -> AgentOutcome:
        self._log(f"agent: {state} after {steps} steps: {detail}")
        sink(
            role="log",
            content=f"agent state: {state}. {detail}",
            kind="log",
        )
        return AgentOutcome(
            state=state,
            error=detail,
            steps=steps,
        )


def _dump_arguments(arguments: dict[str, Any]) -> str:
    import json

    return json.dumps(arguments, ensure_ascii=False, default=str)


class RunLog:
    """Bounded, thread-safe in-memory log for a single run."""

    def __init__(self, capacity: int = 2000) -> None:
        self._lines: deque[str] = deque(maxlen=max(1, capacity))

    def append(self, line: str) -> None:
        self._lines.append(line)

    def tail(self, count: int) -> str:
        lines = list(self._lines)[-max(1, count):]
        return "\n".join(lines) if lines else "(run log is empty)"