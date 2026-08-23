from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import time
from typing import Any, Callable
from uuid import UUID

from .agent_client import (
    AgentChatClient,
    AgentChatResponse,
)
from .identity import default_identity_profile
from .prompts import PROMPT_VERSION
from .provider_adapters import (
    ChatCompletionsProvider,
    CoderGenerationRequest,
    CoderGenerationResult,
    CoderProvider,
    CoderProviderAuthenticationError,
    CoderProviderConfigurationError,
    CoderProviderError,
    CoderProviderProtocolError,
    CoderProviderRateLimited,
    CoderProviderTimeout,
    CoderProviderUnavailable,
)
from .registry import PromptAuthorityComposer
from .telemetry import ModelCallRecord, build_call_record
from .tool_ledger import (
    ToolAlreadyFailedError,
    ToolIdentityMismatchError,
    ToolRecoveryRequiredError,
)
from .tools import CoderToolkit


@dataclass(frozen=True)
class AgentOutcome:
    """Terminal outcome of an agent run.

    state is the explicit terminal classification:
      succeeded       - terminal response obtained inside the working
                        budget (natural completion)
      partial_success - incomplete work stopped by the action or
                        wall-clock limit, including the reserved
                        finalization turn failing to produce a terminal
                        response; NOT a full success
      failed          - model / tool / internal failure
      cancelled       - user requested cancellation

    reason is the precise terminal reason:
      natural_completion, finalized, action_limit, wall_clock_limit,
      model_timeout, model_unavailable, model_error, tool_error,
      user_cancel, internal_error, invalid_prompt
    """

    state: str
    error: str | None
    steps: int
    reason: str | None = None


FINALIZATION_MESSAGE = (
    "Finalization: provide your final response now. Summarize what "
    "changed (file paths), files changed, commands/tests run, failures, "
    "unresolved work, and whether the task is actually complete. "
    "Do NOT call any tools."
)

#: Minimum output budget retained for a meaningful terminal report.
MIN_FINAL_BUDGET_TOKENS = 256

#: Phase output-token budgets (P4). tool_work defaults to the client's
#: configured ceiling (behavior unchanged); recovery and synthesis turn
#: budgets are halved by default and clamped to [256, client ceiling].
_PHASE_BUDGET_DEFAULTS = {
    "tool_work": None,
    "error_recovery": 2048,
    "final_synthesis": 2048,
}
_PHASE_BUDGET_MIN = 256


class CodingAgent:
    """Step-by-step tool-calling agent loop.

    Runs synchronously inside a caller-owned worker thread. Every step is
    reported through the sink so the run can be persisted and streamed to
    the UI. Failures are honest: model problems surface as
    model_unavailable, never as a fake success. The caller can observe
    progress through the phase sink (waiting_for_model, model_generating,
    executing_tool, ...) and can request cancellation through the
    cancelled callback, which the loop honors at every step boundary.
    """

    def __init__(
        self,
        *,
        client: AgentChatClient | None = None,
        provider: CoderProvider | None = None,
        toolkit: CoderToolkit,
        log: Callable[[str], None] | None = None,
        max_steps: int = 12,
        max_loop_seconds: float = 2400.0,
        finalization_enabled: bool = True,
        finalization_timeout_seconds: float = 600.0,
        phase_sink: Callable[[str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
        telemetry_sink: Callable[[ModelCallRecord], None] | None = None,
        phase_max_tokens: dict[str, int] | None = None,
        system_authority: str | None = None,
        max_output_tokens: int = 4096,
        timeout_seconds: float = 600.0,
        tool_ledger: object | None = None,
        run_id: UUID | None = None,
        context_coordinator: object | None = None,
        checkpoint_persist: Callable[[object], object] | None = None,
    ) -> None:
        if not isinstance(toolkit, CoderToolkit):
            raise TypeError("toolkit must be a CoderToolkit")
        if provider is not None:
            self._provider = provider
            self._ceiling = max(1, int(max_output_tokens))
            self._timeout_seconds = max(1.0, float(timeout_seconds))
        elif isinstance(client, AgentChatClient):
            # Legacy client is wrapped as a normalized provider (internal
            # transport reuse). The agent itself is provider-neutral.
            self._provider = ChatCompletionsProvider(
                client.provider,
                client.model_name,
                transport=client,
            )
            self._ceiling = client.max_tokens
            self._timeout_seconds = client.timeout_seconds
        else:
            raise TypeError("a CoderProvider or AgentChatClient is required")
        self._toolkit = toolkit
        self._tool_ledger = tool_ledger
        self._run_id = run_id
        self._context_coordinator = context_coordinator
        self._checkpoint_persist = checkpoint_persist
        self._log = log or (lambda _line: None)
        self._max_steps = max(1, min(100, int(max_steps)))
        self._max_loop_seconds = max(30.0, float(max_loop_seconds))
        self._finalization_enabled = bool(finalization_enabled)
        self._finalization_timeout = max(
            30.0, min(3600.0, float(finalization_timeout_seconds))
        )
        self._phase_sink = phase_sink or (lambda _phase: None)
        self._is_cancelled = cancelled or (lambda: False)
        self._telemetry_sink = telemetry_sink
        self._phase_max_tokens = self._resolve_phase_budgets(phase_max_tokens)
        # Provider-scoped, per-turn private reasoning state (never visible,
        # never persisted, never crosses provider).
        self._reasoning_by_call: dict[str, str] = {}
        self._protocol_state: dict[str, Any] = {}
        self._provider_key: tuple[str, str] | None = None
        # ONE prompt authority: the resolved system authority is always the
        # composed bundle (identity + owner directive + contracts). When the
        # caller does not supply one, compose from the default identity via
        # the SAME composer — never a separate SYSTEM_PROMPT path.
        self._system_authority = system_authority or (
            PromptAuthorityComposer().compose(default_identity_profile())
        )

    def _resolve_phase_budgets(
        self,
        overrides: dict[str, int] | None,
    ) -> dict[str, int]:
        ceiling = self._ceiling
        budgets: dict[str, int] = {}
        for phase, default in _PHASE_BUDGET_DEFAULTS.items():
            if overrides and phase in overrides:
                raw = int(overrides[phase])
            elif default is None:
                raw = ceiling
            else:
                raw = default
            budgets[phase] = max(
                _PHASE_BUDGET_MIN,
                min(ceiling, raw),
            )
        return budgets

    def _max_tokens_for(self, phase: str) -> int:
        if phase == "finalizing":
            budget = self._phase_max_tokens["final_synthesis"]
            if budget < MIN_FINAL_BUDGET_TOKENS:
                self._log(
                    f"agent: final-synthesis budget {budget} is below "
                    f"the {MIN_FINAL_BUDGET_TOKENS}-token minimum; "
                    "raising it"
                )
                budget = MIN_FINAL_BUDGET_TOKENS
            return budget
        if phase == "error_recovery":
            return self._phase_max_tokens["error_recovery"]
        return self._phase_max_tokens["tool_work"]

    def _emit_call(
        self,
        *,
        step: int,
        phase: str,
        roundtrip_seconds: float,
        remaining_action_budget: int,
        response: CoderGenerationResult | None = None,
        error: Exception | None = None,
    ) -> None:
        if self._telemetry_sink is None:
            return
        try:
            record = build_call_record(
                step=step,
                phase=phase,
                roundtrip_seconds=roundtrip_seconds,
                max_tokens_requested=self._max_tokens_for(phase),
                tool_calls_requested=(
                    len(response.tool_calls) if response is not None else 0
                ),
                remaining_action_budget=remaining_action_budget,
                content=response.content if response is not None else None,
                usage=response.usage if response is not None else None,
                finish_reason=(
                    response.finish_reason if response is not None else None
                ),
                error_class=(
                    type(error).__name__ if error is not None else None
                ),
            )
        except Exception as exc:  # noqa: BLE001
            self._log(f"agent: telemetry build failed: {exc!r}")
            return
        try:
            self._telemetry_sink(record)
        except Exception as exc:  # noqa: BLE001
            self._log(f"agent: telemetry sink failed: {exc!r}")

    def _record_provider_private_state(
        self,
        response: CoderGenerationResult,
    ) -> None:
        """Track provider-scoped, per-turn reasoning state.

        On a provider/model change, prior private state is discarded so it
        can never cross a provider boundary.
        """
        key = (response.provider, response.model)
        if self._provider_key != key:
            self._provider_key = key
            self._reasoning_by_call = {}
            self._protocol_state = {}
        self._protocol_state = dict(response.protocol_state)
        reasoning = response.protocol_state.get("reasoning_content")
        if reasoning:
            for call in response.tool_calls:
                self._reasoning_by_call[call.id] = reasoning

    def _continuation_state(self) -> dict[str, Any]:
        return {
            **self._protocol_state,
            "reasoning_by_call": self._reasoning_by_call,
        }

    def _set_phase(self, phase: str) -> None:
        try:
            self._phase_sink(phase)
        except Exception:  # noqa: BLE001
            self._log(f"agent: phase sink failed for {phase}")

    def _execute_tool(
        self,
        call,
        *,
        account_id: UUID,
        workspace_id: UUID,
    ):
        """Execute a tool call with the durable mutation crash policy.

        Mutating tools are recorded in the durable ledger before execution.
        A completed mutation is never re-executed (idempotent skip with the
        durable result_ref); an interrupted/in-flight execution raises
        ToolRecoveryRequiredError (never auto-run); a same call id with
        changed identity raises ToolIdentityMismatchError (fail closed).
        """
        from .tool_ledger import (
            TOOL_STATE_FAILED,
            TOOL_STATE_SUCCEEDED,
            TOOL_STATE_UNKNOWN,
            ToolAlreadySucceededError,
            argument_hash,
            mutation_class_for,
        )
        from .tools import ToolResult

        if self._tool_ledger is None or self._run_id is None:
            return self._toolkit.execute(
                call.name,
                call.arguments,
                account_id=account_id,
                workspace_id=workspace_id,
            )
        mutation_class = mutation_class_for(call.name)
        if mutation_class != "mutating":
            return self._toolkit.execute(
                call.name,
                call.arguments,
                account_id=account_id,
                workspace_id=workspace_id,
            )
        try:
            execution_id = self._tool_ledger.begin(
                run_id=self._run_id,
                tool_call_id=call.id,
                tool_name=call.name,
                argument_hash=argument_hash(call.arguments),
                mutation_class=mutation_class,
            )
        except ToolAlreadySucceededError as error:
            return ToolResult(
                content=(
                    "already completed (durable ledger); not re-executed"
                    + (
                        f" — {error.result_ref}"
                        if error.result_ref
                        else ""
                    )
                ),
                kind="tool",
                ok=True,
            )
        # ToolRecoveryRequiredError / ToolAlreadyFailedError /
        # ToolIdentityMismatchError propagate unchanged: the run must NOT
        # silently re-execute the mutation.
        try:
            result = self._toolkit.execute(
                call.name,
                call.arguments,
                account_id=account_id,
                workspace_id=workspace_id,
            )
        except Exception:
            self._tool_ledger.finish(
                execution_id, state=TOOL_STATE_UNKNOWN
            )
            raise
        self._tool_ledger.finish(
            execution_id,
            state=TOOL_STATE_SUCCEEDED if result.ok else TOOL_STATE_FAILED,
        )
        return result

    def _persist_checkpoint(self, coordinator) -> None:
        """Persist the coordinator's checkpoint (revision N+1) BEFORE any
        dynamic context is dropped. Raises on failure so compaction does not
        discard the conversation when durability is unavailable."""
        if self._checkpoint_persist is None:
            return
        persisted = self._checkpoint_persist(coordinator.checkpoint)
        if persisted is not None:
            coordinator.update_checkpoint(persisted)

    def _bounded_conversation(
        self,
        coordinator,
        tool_schemas,
        output_tokens: int,
    ) -> list[dict[str, Any]] | None:
        """Run the live budget decision and protocol-safe compaction.

        Returns the conversation to send, or None if the request would
        exceed the hard budget (the caller must fail closed with ZERO
        provider calls).
        """
        budget = coordinator.budget
        conversation = coordinator.conversation()
        decision = budget.decide(
            conversation, tools=tool_schemas, output_tokens=output_tokens
        )
        if decision.compact:
            coordinator.emit(
                "context_budget_warning",
                estimated_tokens=decision.estimated_tokens,
                limit_tokens=decision.limit_tokens,
            )
            coordinator.emit("context_compaction_started")
            # P0: fold the server-observed work that is about to be dropped
            # into the checkpoint, THEN persist the next revision, THEN drop.
            coordinator.fold_progress()
            self._persist_checkpoint(coordinator)
            coordinator.compact()
            coordinator.emit(
                "context_checkpoint_persisted",
                messages_retained=len(coordinator.conversation()),
            )
            conversation = coordinator.conversation()
            decision = budget.decide(
                conversation, tools=tool_schemas, output_tokens=output_tokens
            )
        if decision.hard_overflow:
            coordinator.emit(
                "context_budget_blocked",
                estimated_tokens=decision.estimated_tokens,
                limit_tokens=decision.limit_tokens,
            )
            return None
        return conversation

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
                reason="invalid_prompt",
            )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_authority},
        ]
        coordinator = self._context_coordinator
        if coordinator is not None:
            coordinator.add({"role": "user", "content": prompt})
        else:
            messages.append({"role": "user", "content": prompt})
        tool_schemas = self._toolkit.schema()
        steps = 0
        started_at = time.monotonic()
        previous_tool_failed = False

        def record(message: dict[str, Any]) -> None:
            if coordinator is not None:
                coordinator.add(message)
            else:
                messages.append(message)

        def current_conversation() -> list[dict[str, Any]]:
            if coordinator is not None:
                return coordinator.conversation()
            return messages[1:]

        self._log(
            f"agent: run started (max {self._max_steps} steps, "
            f"prompt {PROMPT_VERSION})"
        )
        try:
            while steps < self._max_steps:
                if self._is_cancelled():
                    return self._cancelled(sink, steps)
                elapsed = time.monotonic() - started_at
                if elapsed > self._max_loop_seconds:
                    sink(
                        role="log",
                        content=(
                            f"reached the wall-clock limit of "
                            f"{self._max_loop_seconds:.0f}s; the task may "
                            "be incomplete."
                        ),
                        kind="log",
                    )
                    self._log("agent: wall-clock limit reached")
                    return AgentOutcome(
                        state="partial_success",
                        error=(
                            f"wall-clock limit of "
                            f"{self._max_loop_seconds:.0f}s reached; the "
                            "task may be incomplete"
                        ),
                        steps=steps,
                        reason="wall_clock_limit",
                    )
                steps += 1
                self._set_phase(
                    "waiting_for_model_after_tool"
                    if steps > 1
                    else "waiting_for_model"
                )
                call_phase = (
                    "error_recovery"
                    if previous_tool_failed
                    else "tool_work"
                )
                call_started = time.monotonic()
                response = None
                call_error = None
                try:
                    self._set_phase("model_generating")
                    max_tokens = self._max_tokens_for(call_phase)
                    if coordinator is not None:
                        conversation = self._bounded_conversation(
                            coordinator, tool_schemas, max_tokens
                        )
                        if conversation is None:
                            # Hard context overflow: fail closed with ZERO
                            # provider calls this turn.
                            sink(
                                role="log",
                                content=(
                                    "context_budget_exceeded: the pending "
                                    "request would exceed the configured "
                                    "context budget; no model call was made."
                                ),
                                kind="log",
                                ok=False,
                            )
                            return AgentOutcome(
                                state="partial_success",
                                error=(
                                    "context budget exceeded; the request "
                                    "was not sent"
                                ),
                                steps=steps,
                                reason="action_limit",
                            )
                    else:
                        conversation = messages[1:]
                    response = self._provider.generate(
                        CoderGenerationRequest(
                            system_authority=self._system_authority,
                            conversation=tuple(conversation),
                            tools=tuple(tool_schemas),
                            max_output_tokens=max_tokens,
                            continuation_state=self._continuation_state(),
                        )
                    )
                    self._record_provider_private_state(response)
                    call_error = None
                except Exception as error:
                    response = None
                    call_error = error
                    raise
                finally:
                    self._emit_call(
                        step=steps,
                        phase=call_phase,
                        roundtrip_seconds=(
                            time.monotonic() - call_started
                        ),
                        remaining_action_budget=(
                            self._max_steps - steps
                        ),
                        response=response,
                        error=call_error,
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
                        reason="natural_completion",
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
                # Provider protocol state (e.g. DeepSeek reasoning_content)
                # is NOT embedded in the conversation: the provider replays it
                # internally from continuation_state on the next turn.
                record(assistant_message)

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
                    self._set_phase("executing_tool")
                    self._log(
                        f"agent: executing tool {call.name} "
                        f"(step {steps})"
                    )
                    try:
                        result = self._execute_tool(
                            call,
                            account_id=account_id,
                            workspace_id=workspace_id,
                        )
                    except ToolRecoveryRequiredError as error:
                        sink(
                            role="log",
                            content=(
                                "MUTATION_STATE_UNKNOWN_AFTER_INTERRUPTION: "
                                f"{error}; the mutation was NOT re-executed. "
                                "Owner recovery is required."
                            ),
                            kind="mutation_state",
                            ok=False,
                        )
                        return self._fail(
                            sink,
                            "tool_error",
                            (
                                f"tool {call.name} requires recovery: "
                                f"{error}; not re-executed"
                            ),
                            steps,
                        )
                    except ToolAlreadyFailedError as error:
                        sink(
                            role="log",
                            content=(
                                "MUTATION_STATE_FAILED (terminal): "
                                f"{error}; retry requires a new tool call id."
                            ),
                            kind="mutation_state",
                            ok=False,
                        )
                        return self._fail(
                            sink,
                            "tool_error",
                            f"tool {call.name} is terminal (failed): {error}",
                            steps,
                        )
                    except ToolIdentityMismatchError as error:
                        sink(
                            role="log",
                            content=(
                                "MUTATION_IDENTITY_MISMATCH: "
                                f"{error}; protocol integrity failure."
                            ),
                            kind="mutation_state",
                            ok=False,
                        )
                        return self._fail(
                            sink,
                            "tool_error",
                            f"tool {call.name} identity mismatch: {error}",
                            steps,
                        )
                    except Exception as error:  # noqa: BLE001
                        return self._fail(
                            sink,
                            "tool_error",
                            (
                                f"tool {call.name} raised an unexpected "
                                f"exception: {error!r}"
                            ),
                            steps,
                        )
                    self._set_phase("waiting_for_model_after_tool")
                    self._log(
                        f"agent: tool {call.name} -> "
                        f"{'ok' if result.ok else 'error'}"
                    )
                    previous_tool_failed = not result.ok
                    if coordinator is not None:
                        coordinator.note_tool_execution(
                            call.name,
                            call.arguments,
                            ok=result.ok,
                            content=result.content,
                            kind=result.kind,
                        )
                    record(
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
                    "attempting the reserved finalization turn."
                ),
                kind="log",
            )
            self._log("agent: step limit reached")
            return self._finalize(
                sink,
                [{"role": "system", "content": self._system_authority}]
                + current_conversation(),
                steps,
                started_at,
            )
        except CoderProviderTimeout as error:
            return self._fail(
                sink,
                "model_timeout",
                f"model request timed out: {error}",
                steps,
            )
        except (
            CoderProviderUnavailable,
            CoderProviderAuthenticationError,
            CoderProviderConfigurationError,
            CoderProviderRateLimited,
        ) as error:
            return self._fail(
                sink,
                "model_unavailable",
                f"model endpoint is unavailable: {error}",
                steps,
            )
        except CoderProviderProtocolError as error:
            return self._fail(
                sink,
                "model_error",
                f"model returned an unusable response: {error}",
                steps,
            )

    def _finalize(
        self,
        sink: Callable[..., None],
        messages: list[dict[str, Any]],
        steps: int,
        started_at: float,
    ) -> AgentOutcome:
        """One bounded, non-tool finalization turn after the working
        budget is exhausted.

        The finalization request carries NO tools, so the model cannot
        start another tool loop. If it fails or times out, the run is
        PARTIAL_SUCCESS (ACTION_LIMIT) with all previous work preserved:
        incomplete work must never be labeled a full success.
        """
        if self._is_cancelled():
            return self._cancelled(sink, steps)
        elapsed = time.monotonic() - started_at
        if elapsed > self._max_loop_seconds:
            return AgentOutcome(
                state="partial_success",
                error=(
                    f"wall-clock limit of "
                    f"{self._max_loop_seconds:.0f}s reached; the task "
                    "may be incomplete"
                ),
                steps=steps,
                reason="wall_clock_limit",
            )
        if not self._finalization_enabled:
            self._log("agent: finalization disabled; marking partial")
            return AgentOutcome(
                state="partial_success",
                error=(
                    f"reached the maximum of {self._max_steps} agent steps "
                    "without a terminal response (finalization disabled)"
                ),
                steps=steps,
                reason="action_limit",
            )

        budget = min(
            self._timeout_seconds,
            self._finalization_timeout,
        )
        if budget < 1.0:
            return AgentOutcome(
                state="partial_success",
                error=(
                    f"reached the maximum of {self._max_steps} agent steps "
                    "without a terminal response (finalization budget "
                    "exhausted)"
                ),
                steps=steps,
                reason="action_limit",
            )

        finalization_messages = list(messages) + [
            {"role": "user", "content": FINALIZATION_MESSAGE}
        ]
        self._set_phase("finalizing")
        self._log(
            f"agent: finalization turn (budget {budget:.0f}s, no tools)"
        )
        call_started = time.monotonic()
        try:
            response = self._provider.generate(
                CoderGenerationRequest(
                    system_authority=self._system_authority,
                    conversation=tuple(finalization_messages[1:]),
                    tools=(),
                    max_output_tokens=self._max_tokens_for("finalizing"),
                    timeout_seconds=budget,
                    continuation_state=self._continuation_state(),
                )
            )
        except CoderProviderTimeout as error:
            self._emit_call(
                step=steps + 1,
                phase="finalizing",
                roundtrip_seconds=time.monotonic() - call_started,
                remaining_action_budget=0,
                error=error,
            )
            self._log(f"agent: finalization timed out: {error}")
            return AgentOutcome(
                state="partial_success",
                error=(
                    f"reached the maximum of {self._max_steps} agent steps "
                    f"and the finalization turn timed out: {error}"
                ),
                steps=steps,
                reason="action_limit",
            )
        except CoderProviderError as error:
            self._emit_call(
                step=steps + 1,
                phase="finalizing",
                roundtrip_seconds=time.monotonic() - call_started,
                remaining_action_budget=0,
                error=error,
            )
            self._log(f"agent: finalization failed: {error}")
            return AgentOutcome(
                state="partial_success",
                error=(
                    f"reached the maximum of {self._max_steps} agent steps "
                    f"and the finalization turn failed: {error}"
                ),
                steps=steps,
                reason="action_limit",
            )
        self._emit_call(
            step=steps + 1,
            phase="finalizing",
            roundtrip_seconds=time.monotonic() - call_started,
            remaining_action_budget=0,
            response=response,
        )

        if response.tool_calls:
            self._log(
                "agent: finalization returned tool calls; marking partial"
            )
            return AgentOutcome(
                state="partial_success",
                error=(
                    f"reached the maximum of {self._max_steps} agent steps "
                    "and the finalization turn returned tool calls"
                ),
                steps=steps,
                reason="action_limit",
            )

        final = response.content or "Done."
        sink(
            role="assistant",
            content=final,
        )
        self._log("agent: finalization produced the terminal response")
        return AgentOutcome(
            state="succeeded",
            error=None,
            steps=steps,
            reason="finalized",
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
            state="failed",
            error=detail,
            steps=steps,
            reason=state,
        )

    def _cancelled(
        self,
        sink: Callable[..., None],
        steps: int,
    ) -> AgentOutcome:
        self._log(f"agent: cancelled by user after {steps} steps")
        sink(
            role="log",
            content="agent state: cancelled. run cancelled by user.",
            kind="log",
        )
        return AgentOutcome(
            state="cancelled",
            error="cancelled by user",
            steps=steps,
            reason="user_cancel",
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