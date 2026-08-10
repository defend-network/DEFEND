from __future__ import annotations

from control_plane import PolicyDecision
from tool_sdk import RiskLevel, SideEffect, ToolPermission


class DevWebPolicy:
    ALLOWED_TOOLS = {
	"documents.search",
	"rag.query",
        "calculator.evaluate",
        "time.now",
        "web.search",
        "web.fetch",
        "documents.fetch",
        "documents.read",
        "rag.ingest",
    }

    ALLOWED_PERMISSIONS = {
        ToolPermission.NETWORK,
        ToolPermission.READ_EXTERNAL,
    }

    async def evaluate_tool(self, *, request, tool, step) -> PolicyDecision:
        if tool.name not in self.ALLOWED_TOOLS:
            return PolicyDecision(
                allowed=False,
                reason="Tool not permitted by development policy.",
            )

        if tool.risk_level != RiskLevel.LOW:
            return PolicyDecision(
                allowed=False,
                reason="Development policy permits LOW-risk tools only.",
            )

        # Allow WRITE only for explicit knowledge-index tools
        if tool.side_effect not in {SideEffect.NONE, SideEffect.READ, SideEffect.WRITE}:
            return PolicyDecision(
                allowed=False,
                reason="Side effect not permitted by development policy.",
            )

        if tool.side_effect == SideEffect.WRITE and tool.name not in {"rag.ingest"}:
            return PolicyDecision(
                allowed=False,
                reason="Write side effect not permitted for this tool.",
            )

        required = set(tool.permissions)
        if not required.issubset(self.ALLOWED_PERMISSIONS):
            return PolicyDecision(
                allowed=False,
                reason="Tool requests permissions outside the development policy.",
            )

        return PolicyDecision(
            allowed=True,
            granted_permissions=required,
            approved=False,
        )