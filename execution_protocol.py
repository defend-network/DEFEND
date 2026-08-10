from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


# ─────────────────────────────────────────────
# What the MODEL is allowed to emit
# ─────────────────────────────────────────────

class ProposedToolCall(BaseModel):
    call_id: str = Field(default_factory=lambda: str(uuid4()))
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    rationale: str | None = None


class SourceChoice(BaseModel):
    source_id: str
    action: Literal["fetch_html", "fetch_pdf", "skip"]
    reason: str


class SourceSelection(BaseModel):
    objective: str
    choices: list[SourceChoice] = Field(min_length=1, max_length=3)
    notes: str | None = None

    @model_validator(mode="after")
    def unique_source_ids(self):
        ids = [c.source_id for c in self.choices]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate source_id in SourceSelection")
        return self


class ProposedStep(BaseModel):
    id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    optional: bool = False


class SingleToolDecision(BaseModel):
    action: Literal["direct", "tool"]
    tool_call: ProposedToolCall | None = None


class ProposedPlan(BaseModel):
    objective: str
    steps: list[ProposedStep]


class PlanStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ─────────────────────────────────────────────
# Value references (data flow between steps)
# ─────────────────────────────────────────────

class ValueRef(BaseModel):
    step_id: str
    path: str  # Example: "data.results.0.document_id"


class LiteralValue(BaseModel):
    kind: Literal["literal"] = "literal"
    value: Any = None


class RefValue(BaseModel):
    kind: Literal["ref"] = "ref"
    ref: ValueRef


class EvidenceItem(BaseModel):
    evidence_id: str
    source_id: str
    claim_supported: str
    excerpt: str
    page: int | None = None
    url: str | None = None
    title: str | None = None
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class ResearchPacket(BaseModel):
    objective: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


ArgumentValue = Annotated[LiteralValue | RefValue, Field(discriminator="kind")]


# ─────────────────────────────────────────────
# Research V2 contracts
# ─────────────────────────────────────────────

class ResearchStatus(str, Enum):
    VERIFIED = "verified"
    PARTIAL = "partial"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class EvidenceAssessment(BaseModel):
    sufficient: bool
    answered_aspects: list[str] = Field(default_factory=list)
    missing_aspects: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    reason: str = ""


class RecoveryDecision(BaseModel):
    action: Literal["try_unused_sources", "refine_search", "stop"]
    revised_query: str | None = None
    reason: str = ""


class SourceOutcome(BaseModel):
    source_id: str
    url: str | None = None
    fetch_status: str  # succeeded | failed | skipped
    evidence_status: str  # accepted | rejected | none
    rejection_reason: str | None = None


class ResearchBudget(BaseModel):
    """FAST = public default; DEEP = explicit expensive research."""
    mode: str = "fast"  # fast | deep
    max_search_rounds: int = 1
    max_sources_total: int = 3
    max_sources_per_round: int = 3
    max_recovery_attempts: int = 1

    @classmethod
    def fast(cls) -> "ResearchBudget":
        return cls(
            mode="fast",
            max_search_rounds=1,
            max_sources_total=3,
            max_sources_per_round=3,
            max_recovery_attempts=1,
        )

    @classmethod
    def deep(cls) -> "ResearchBudget":
        return cls(
            mode="deep",
            max_search_rounds=2,
            max_sources_total=6,
            max_sources_per_round=3,
            max_recovery_attempts=2,
            max_wall_seconds=360.0,
        )


class ResearchState(BaseModel):
    objective: str
    search_round: int = 0
    queries: list[str] = Field(default_factory=list)
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    attempted_source_ids: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    assessments: list[EvidenceAssessment] = Field(default_factory=list)
    source_outcomes: list[SourceOutcome] = Field(default_factory=list)
    recovery_attempts: int = 0
    status: ResearchStatus | None = None
    budget: ResearchBudget = Field(default_factory=ResearchBudget)


# ─────────────────────────────────────────────
# Runtime / authoritative objects
# ─────────────────────────────────────────────

class FailurePolicy(str, Enum):
    ABORT_PLAN = "abort_plan"
    SKIP_STEP = "skip_step"
    CONTINUE = "continue"
    RETRY = "retry"


class ApprovalMode(str, Enum):
    NONE = "none"
    IF_REQUIRED = "if_required"
    ALWAYS = "always"


class RetryPolicy(BaseModel):
    max_attempts: int = Field(default=1, ge=1, le=10)
    initial_backoff_ms: int = Field(default=500, ge=0)
    max_backoff_ms: int = Field(default=10_000, ge=0)
    exponential_backoff: bool = True
    retry_on: set[str] = Field(
        default_factory=lambda: {"timeout", "rate_limited", "upstream_error"}
    )


class StepBudget(BaseModel):
    timeout_seconds: float | None = Field(default=None, gt=0)
    max_cost_usd: float | None = Field(default=None, ge=0)
    max_output_bytes: int | None = Field(default=None, ge=1)


class PlanBudget(BaseModel):
    max_cost_usd: float | None = Field(default=None, ge=0)
    max_runtime_seconds: float | None = Field(default=None, gt=0)
    max_tool_calls: int | None = Field(default=None, ge=1)


class ToolCall(BaseModel):
    call_id: str = Field(default_factory=lambda: str(uuid4()))
    tool_name: str
    tool_version: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    rationale: str | None = None
    approval_mode: ApprovalMode = ApprovalMode.IF_REQUIRED
    idempotency_key: str | None = None


class PlanStep(BaseModel):
    id: str
    call: ToolCall
    depends_on: list[str] = Field(default_factory=list)
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    failure_policy: FailurePolicy = FailurePolicy.ABORT_PLAN
    budget: StepBudget = Field(default_factory=StepBudget)
    optional: bool = False


class ExecutablePlan(BaseModel):
    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    objective: str
    steps: list[PlanStep]
    budget: PlanBudget = Field(default_factory=PlanBudget)
    created_by: Literal["model", "workflow", "system", "user"] = "model"

    @model_validator(mode="after")
    def validate_dag(self):
        ids = [step.id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("Step IDs must be unique.")

        known = set(ids)
        for step in self.steps:
            for dep in step.depends_on:
                if dep not in known:
                    raise ValueError(f"Unknown dependency: {dep}")
                if dep == step.id:
                    raise ValueError("A step cannot depend on itself.")

        if self._has_cycle():
            raise ValueError("Execution plan contains a cycle.")

        return self

    def _has_cycle(self) -> bool:
        graph = {step.id: step.depends_on for step in self.steps}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> bool:
            if node in visiting:
                return True
            if node in visited:
                return False

            visiting.add(node)
            for dep in graph.get(node, []):
                if visit(dep):
                    return True
            visiting.remove(node)
            visited.add(node)
            return False

        return any(visit(node) for node in graph)


# ─────────────────────────────────────────────
# Observed execution state
# ─────────────────────────────────────────────

class StepStatus(str, Enum):
    PENDING = "pending"
    BLOCKED = "blocked"
    READY = "ready"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class StepExecution(BaseModel):
    step_id: str
    call_id: str
    status: StepStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    attempts: int = 0
    tool_result: Any | None = None
    error: Any | None = None


class PlanExecution(BaseModel):
    execution_id: str = Field(default_factory=lambda: str(uuid4()))
    plan_id: str
    status: PlanStatus
    steps: dict[str, StepExecution]
    started_at: datetime
    finished_at: datetime | None = None
    cost_usd: float = 0.0
    tool_calls: int = 0


# ─────────────────────────────────────────────
# Routing + Research V2.1 contracts (integration)
# ─────────────────────────────────────────────

class Route(str, Enum):
    DIRECT = "DIRECT"
    SINGLE_TOOL = "SINGLE_TOOL"
    DOCUMENT = "DOCUMENT"
    RESEARCH = "RESEARCH"
    COMPLEX = "COMPLEX"


class RouteDecision(BaseModel):
    route: Route
    reason_code: str = "other"
    requires_external_evidence: bool = False
    notes: str | None = None


class KnowledgeScope(str, Enum):
    PERMANENT = "permanent"
    RESEARCH = "research"
    SESSION = "session"


class ResearchRequirements(BaseModel):
    requires_currentness: bool = False
    requires_web: bool = False
    requires_primary_source: bool = False
    required_domains: list[str] = Field(default_factory=list)
    attached_document_ids: list[str] = Field(default_factory=list)
    prefer_permanent_rag: bool = False
    query_hints: list[str] = Field(default_factory=list)


class CitedClaim(BaseModel):
    claim_id: str
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float | None = None


class ClaimVerification(BaseModel):
    claim_id: str
    supported: bool
    valid_evidence_ids: list[str] = Field(default_factory=list)
    reason: str = ""


class StatisticalFact(BaseModel):
    evidence_id: str
    value: float | str
    unit: str = ""
    measure: str = ""
    population: str | None = None
    geography: str | None = None
    sex: str | None = None
    age_scope: str | None = None
    period: str | None = None
    source_id: str = ""


class ResearchTrace(BaseModel):
    route: str
    route_reason: str = ""
    search_provider: str | None = None
    queries: list[str] = Field(default_factory=list)
    candidate_count: int = 0
    selected_sources: list[str] = Field(default_factory=list)
    attempted_sources: list[str] = Field(default_factory=list)
    accepted_sources: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    execution_status: str | None = None
    research_status: str | None = None
    missing_aspects: list[str] = Field(default_factory=list)
    scopes_used: list[str] = Field(default_factory=list)
