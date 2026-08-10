from __future__ import annotations

from control_plane import PolicyDecision, AgentRequest
from tool_sdk import DefendTool, ToolPermission, RiskLevel, SideEffect
from execution_protocol import PlanStep


# Public agent allowlist.
# Permanent rag.ingest stays OFF for public chat.
# research.cache_ingest is system-only ephemeral indexing for Research PDFs.
ALLOWED_TOOLS = {
    "calculator.evaluate",
    "time.now",
    "web.search",
    "web.fetch",
    "documents.fetch",
    "documents.read",
    "documents.search",
    "rag.query",
    "research.cache_ingest",  # ephemeral research cache only
    "memory.search",
    "memory.propose",  # pending proposal only; commit is owner HTTP route
}


class ProductionPolicy:
    """
    Public deployment policy.
    - Explicit tool allowlist
    - No permanent knowledge writes from public agent
    - Ephemeral research cache ingest allowed for system research path
    """

    async def evaluate_tool(
        self,
        *,
        request: AgentRequest,
        tool: DefendTool,
        step: PlanStep,
    ) -> PolicyDecision:
        if tool.name not in ALLOWED_TOOLS:
            return PolicyDecision(
                allowed=False,
                granted_permissions=set(),
                approved=False,
                reason=f"Tool not allowed in production: {tool.name}",
            )

        if tool.side_effect in {SideEffect.EXTERNAL_WRITE, SideEffect.DESTRUCTIVE}:
            return PolicyDecision(
                allowed=False,
                granted_permissions=set(),
                approved=False,
                reason="Write/destructive tools disabled in production policy",
            )

        if tool.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
            return PolicyDecision(
                allowed=False,
                granted_permissions=set(),
                approved=False,
                reason="High-risk tools require elevated policy",
            )

        # Permanent ingest never on public agent (even if someone registers it)
        if tool.name == "rag.ingest":
            return PolicyDecision(
                allowed=False,
                granted_permissions=set(),
                approved=False,
                reason="Permanent rag.ingest is admin-only",
            )

        return PolicyDecision(
            allowed=True,
            granted_permissions=set(tool.permissions),
            approved=True,
            reason="production allowlist",
        )
