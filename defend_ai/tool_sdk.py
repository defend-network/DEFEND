from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SideEffect(str, Enum):
    NONE = "none"
    READ = "read"
    WRITE = "write"
    EXTERNAL_WRITE = "external_write"
    EXECUTION = "execution"
    DESTRUCTIVE = "destructive"


class ToolPermission(str, Enum):
    READ_EXTERNAL = "read_external"
    READ_PRIVATE = "read_private"
    WRITE_FILE = "write_file"
    MODIFY_PRIVATE = "modify_private"
    EXECUTE_CODE = "execute_code"
    NETWORK = "network"
    SEND_MESSAGE = "send_message"
    PUBLISH_EXTERNAL = "publish_external"
    ADMIN = "admin"


class DataClassification(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class ToolErrorCode(str, Enum):
    INVALID_INPUT = "invalid_input"
    PERMISSION_DENIED = "permission_denied"
    APPROVAL_REQUIRED = "approval_required"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    UPSTREAM_ERROR = "upstream_error"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    VERSION_MISMATCH = "version_mismatch"
    REFERENCE_ERROR = "reference_error"
    BUDGET_EXCEEDED = "budget_exceeded"
    INTERNAL_ERROR = "internal_error"
    CANCELLED = "cancelled"


class ToolError(BaseModel):
    code: ToolErrorCode
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class ToolMetadata(BaseModel):
    duration_ms: int | None = None
    cached: bool = False
    attempts: int = 1
    source_count: int | None = None
    cost_usd: float = Field(default=0.0, ge=0)
    warnings: list[str] = Field(default_factory=list)


class SourceRef(BaseModel):
    source_id: str
    url: str | None = None
    title: str | None = None
    retrieved_at: str | None = None


T = TypeVar("T")


class ToolResult(BaseModel, Generic[T]):
    ok: bool
    data: T | None = None
    error: ToolError | None = None
    metadata: ToolMetadata = Field(default_factory=ToolMetadata)
    sources: list[SourceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_result_state(self):
        if self.ok:
            if self.error is not None:
                raise ValueError("Successful ToolResult cannot contain an error.")
        else:
            if self.error is None:
                raise ValueError("Failed ToolResult must contain an error.")
            if self.data is not None:
                raise ValueError("Failed ToolResult cannot contain data.")
        return self


class ToolContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    request_id: str
    trace_id: str
    user_id: str | None = None
    session_id: str | None = None
    project_id: str | None = None

    granted_permissions: set[ToolPermission] = Field(default_factory=set)
    deadline_ms: int | None = None
    cancellation_token: Any | None = None
    idempotency_key: str | None = None

    # References/handles only. Never put real secrets in model-visible context.
    secret_refs: dict[str, str] = Field(default_factory=dict)


InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


class DefendTool(ABC, Generic[InputT, OutputT]):
    name: ClassVar[str]
    description: ClassVar[str]
    version: ClassVar[str] = "1.0.0"

    input_model: ClassVar[type[InputT]]
    output_model: ClassVar[type[OutputT]]

    permissions: ClassVar[frozenset[ToolPermission]]
    risk_level: ClassVar[RiskLevel]
    side_effect: ClassVar[SideEffect] = SideEffect.NONE

    timeout_seconds: ClassVar[float] = 30.0
    max_retries: ClassVar[int] = 0
    idempotent: ClassVar[bool] = True
    parallel_safe: ClassVar[bool] = True

    max_input_classification: ClassVar[DataClassification] = DataClassification.PUBLIC
    max_output_classification: ClassVar[DataClassification] = DataClassification.PUBLIC

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return cls.input_model.model_json_schema()

    @classmethod
    def output_schema(cls) -> dict[str, Any]:
        return cls.output_model.model_json_schema()

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    async def healthcheck(self) -> dict[str, Any]:
        return {"status": "ok"}

    @abstractmethod
    async def execute(
        self,
        args: InputT,
        context: ToolContext,
    ) -> ToolResult[OutputT]:
        ...
