from __future__ import annotations

from typing import Literal

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


class MemorySearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    scopes: list[Literal["global", "user", "project"]] = Field(
        default_factory=lambda: ["global", "user"], max_length=3
    )
    subject: str | None = Field(default=None, max_length=256)
    limit: int = Field(default=8, ge=1, le=20)


class MemoryHitOut(BaseModel):
    memory_id: str
    namespace: str
    subject: str
    predicate: str
    value_text: str
    confidence: float
    provenance: list[dict]


class MemorySearchOutput(BaseModel):
    hits: list[MemoryHitOut]
    namespaces_used: list[str]


class MemorySearchTool(DefendTool[MemorySearchInput, MemorySearchOutput]):
    name = "memory.search"
    version = "1.1.0"
    description = (
        "Search committed durable memory visible to this caller. Public callers can search only "
        "global, their own user-scoped memory, and an authorized project scope."
    )
    permissions = frozenset({ToolPermission.READ_PRIVATE})
    risk_level = RiskLevel.LOW
    side_effect = SideEffect.READ
    max_input_classification = DataClassification.INTERNAL
    max_output_classification = DataClassification.INTERNAL
    input_model = MemorySearchInput
    output_model = MemorySearchOutput
    timeout_seconds = 15
    idempotent = True
    parallel_safe = True

    def __init__(self, memory_manager: MemoryManager):
        self._memory = memory_manager

    async def execute(
        self, args: MemorySearchInput, context: ToolContext
    ) -> ToolResult[MemorySearchOutput]:
        namespaces: list[str] = []
        try:
            for scope in args.scopes:
                ns = resolve_public_scope(
                    scope,
                    user_id=context.user_id,
                    project_id=context.project_id,
                )
                if ns not in namespaces:
                    namespaces.append(ns)
        except PermissionError as exc:
            return ToolResult(
                ok=False,
                error=ToolError(
                    code=ToolErrorCode.PERMISSION_DENIED,
                    message=str(exc),
                    retryable=False,
                ),
            )

        # Critical invariant: never convert an empty authorization result to None,
        # because None means "unrestricted namespaces" in MemoryStore.search().
        if not namespaces:
            return ToolResult(ok=True, data=MemorySearchOutput(hits=[], namespaces_used=[]))

        hits_raw = self._memory.search(
            args.query,
            namespaces=namespaces,
            subject=args.subject,
            limit=args.limit,
        )
        hits = [
            MemoryHitOut(
                memory_id=h.memory_id,
                namespace=h.namespace,
                subject=h.subject,
                predicate=h.predicate,
                value_text=h.value_text,
                confidence=float(h.confidence),
                provenance=list(h.provenance or []),
            )
            for h in hits_raw
        ]
        return ToolResult(
            ok=True,
            data=MemorySearchOutput(hits=hits, namespaces_used=namespaces),
        )
