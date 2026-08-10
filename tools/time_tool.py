from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tool_sdk import (
    DataClassification,
    DefendTool,
    RiskLevel,
    SideEffect,
    ToolContext,
    ToolError,
    ToolErrorCode,
    ToolResult,
)
from bootstrap_models import TimeNowInput, TimeNowOutput


class TimeNowTool(DefendTool[TimeNowInput, TimeNowOutput]):
    name = "time.now"
    description = "Return the current authoritative time."
    version = "1.0.0"

    input_model = TimeNowInput
    output_model = TimeNowOutput

    permissions = frozenset()
    risk_level = RiskLevel.LOW
    side_effect = SideEffect.NONE
    idempotent = True
    parallel_safe = True
    max_input_classification = DataClassification.PUBLIC
    max_output_classification = DataClassification.PUBLIC
    timeout_seconds = 2.0

    async def execute(
        self,
        args: TimeNowInput,
        context: ToolContext,
    ) -> ToolResult[TimeNowOutput]:
        try:
            requested = args.timezone.strip()

            if requested.upper() == "UTC":
                tz = timezone.utc
                canonical_name = "UTC"
            else:
                tz = ZoneInfo(requested)
                canonical_name = requested

            now = datetime.now(tz)

            return ToolResult(
                ok=True,
                data=TimeNowOutput(
                    iso=now.isoformat(),
                    unix=now.timestamp(),
                    timezone=canonical_name,
                ),
            )

        except ZoneInfoNotFoundError:
            return ToolResult(
                ok=False,
                error=ToolError(
                    code=ToolErrorCode.INVALID_INPUT,
                    message=f"Unknown timezone: {args.timezone}",
                    retryable=False,
                ),
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
