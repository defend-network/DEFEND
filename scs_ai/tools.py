from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ToolState = Literal["not_configured", "available", "unavailable"]

TOOL_NAMES = (
    "customers",
    "contacts",
    "jobs",
    "estimates",
    "invoices",
    "equipment",
    "service_history",
    "documents",
    "business_analytics",
    "hvac_knowledge",
)


@dataclass(frozen=True)
class ToolStatus:
    name: str
    state: ToolState
    detail: str


class ToolRegistry:
    """Honest SCS AI tool/service boundary.

    Every SCS domain capability reports an explicit not-configured or
    unavailable state until a reviewed provider is wired. Nothing here calls
    an external service, mutates SCS data, or invents results.
    """

    def __init__(self, tools: tuple[ToolStatus, ...]) -> None:
        names = {tool.name for tool in tools}
        if names != set(TOOL_NAMES):
            raise ValueError("tool registry must cover every SCS AI tool name")
        self._tools = tools

    @classmethod
    def default(cls) -> "ToolRegistry":
        return cls(
            tuple(
                ToolStatus(name=name, state="not_configured", detail="not configured")
                for name in TOOL_NAMES
            )
        )

    def status(self) -> tuple[ToolStatus, ...]:
        return self._tools

    def state(self) -> ToolState:
        configured = [item for item in self._tools if item.state == "available"]
        unavailable = [item for item in self._tools if item.state == "unavailable"]
        if configured:
            return "available"
        if unavailable:
            return "unavailable"
        return "not_configured"