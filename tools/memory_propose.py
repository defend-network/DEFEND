from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from defend_data.memory_manager import MemoryManager
from defend_data.namespace_policy import resolve_public_scope
from tool_sdk import (
    DataClassification,
    DefendTool,
    RiskLevel,
    SideEffect,
    ToolContext,
    ToolError,
    ToolErrorCode,
    ToolPermission,
    ToolResult,
)


class MemoryProposeInput(BaseModel):
    scope: Literal["global", "user", "project"] = "user"
    subject: str = Field(min_length=1, max_length=256)
    predicate: str = Field(min_length=1, max_length=128)
    value: str = Field(min_length=1, max_length=4000)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    sensitivity: Literal["public", "internal", "confidential"] = "internal"
    provenance: list[dict[str, Any]] = Field(default_factory=list, max_length=20)


class MemoryProposeOutput(BaseModel):
    proposal_id: str
    namespace: str
    status: str
    message: str


class MemoryProposeTool(DefendTool[MemoryProposeInput, MemoryProposeOutput]):
    name = "memory.propose"
    version = "1.1.0"
    description = (
        "Create a pending durable-memory proposal. Use for explicit remember requests or stable, "
        "long-lived state that would materially help later. This never commits memory; owner review "
        "is required."
    )
    permissions = frozenset({ToolPermission.MODIFY_PRIVATE})
    risk_level = RiskLevel.MEDIUM
    side_effect = SideEffect.WRITE
    max_input_classification = DataClassification.INTERNAL
    max_output_classification = DataClassification.INTERNAL
    input_model = MemoryProposeInput
    output_model = MemoryProposeOutput
    timeout_seconds = 15
    idempotent = False
    parallel_safe = False

    def __init__(self, memory_manager: MemoryManager):
        self._memory = memory_manager

    async def execute(
        self, args: MemoryProposeInput, context: ToolContext
    ) -> ToolResult[MemoryProposeOutput]:
        try:
            namespace = resolve_public_scope(
                args.scope,
                user_id=context.user_id,
                project_id=context.project_id,
            )
        except PermissionError as exc:
            return ToolResult(
                ok=False,
                error=ToolError(
                    code=ToolErrorCode.PERMISSION_DENIED,
                    message=str(exc),
                    retryable=False,
                ),
            )

        if not context.session_id:
            return ToolResult(
                ok=False,
                error=ToolError(
                    code=ToolErrorCode.INVALID_INPUT,
                    message="memory.propose requires a conversation/session id for provenance",
                    retryable=False,
                ),
            )

        provenance = list(args.provenance)
        provenance.append(
            {
                "source_id": f"conversation:{context.session_id}",
                "request_id": context.request_id,
                "kind": "current_conversation_statement",
            }
        )

        try:
            prop = self._memory.propose(
                namespace=namespace,
                subject=args.subject,
                predicate=args.predicate,
                value=args.value,
                value_text=args.value,
                confidence=args.confidence,
                sensitivity=args.sensitivity,
                origin="model",
                provenance=provenance,
            )
        except Exception as exc:
            return ToolResult(
                ok=False,
                error=ToolError(
                    code=ToolErrorCode.INTERNAL_ERROR,
                    message=str(exc),
                    retryable=False,
                ),
            )

        return ToolResult(
            ok=True,
            data=MemoryProposeOutput(
                proposal_id=prop.proposal_id,
                namespace=namespace,
                status=prop.status,
                message="Pending only; durable commit requires owner approval.",
            ),
        )
