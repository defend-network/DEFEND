from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class CoderSettings:
    database_url: str
    host: str = "127.0.0.1"
    port: int = 8301
    public_https: bool = False
    workspace_root: str = "./coder-workspaces"
    idle_timeout_seconds: int = 600
    max_steps: int = 12
    finalization_enabled: bool = True
    finalization_timeout_seconds: float = 600.0
    max_run_seconds: float = 2400.0
    phase_tool_work_max_tokens: int | None = None
    phase_error_recovery_max_tokens: int | None = None
    phase_final_synthesis_max_tokens: int | None = None

    @classmethod
    def from_env(cls) -> "CoderSettings":
        database_url = os.environ.get("CODER_DATABASE_URL", "").strip()

        if not database_url:
            raise RuntimeError("CODER_DATABASE_URL is required")

        idle_timeout_seconds = int(
            os.environ.get("CODER_IDLE_TIMEOUT_SECONDS", "600")
        )

        if idle_timeout_seconds < 0:
            raise RuntimeError(
                "CODER_IDLE_TIMEOUT_SECONDS must be >= 0 "
                "(0 disables the idle policy)"
            )

        max_steps = int(os.environ.get("CODER_MAX_STEPS", "12"))
        if not 1 <= max_steps <= 100:
            raise RuntimeError("CODER_MAX_STEPS must be between 1 and 100")

        finalization_enabled = os.environ.get(
            "CODER_FINALIZATION_ENABLED", "1"
        ).lower() in {"1", "true", "yes", "on"}

        finalization_timeout_seconds = float(
            os.environ.get("CODER_FINALIZATION_TIMEOUT_SECONDS", "600")
        )
        if not 30.0 <= finalization_timeout_seconds <= 3600.0:
            raise RuntimeError(
                "CODER_FINALIZATION_TIMEOUT_SECONDS must be between "
                "30 and 3600"
            )

        max_run_seconds = float(
            os.environ.get("CODER_MAX_RUN_SECONDS", "2400")
        )
        if not 60.0 <= max_run_seconds <= 14400.0:
            raise RuntimeError(
                "CODER_MAX_RUN_SECONDS must be between 60 and 14400"
            )

        def _phase_budget(name: str) -> int | None:
            raw = os.environ.get(name, "").strip()
            if not raw:
                return None
            value = int(raw)
            if not 256 <= value <= 16384:
                raise RuntimeError(
                    f"{name} must be between 256 and 16384"
                )
            return value

        return cls(
            database_url=database_url,
            host=os.environ.get(
                "CODER_HOST",
                "127.0.0.1",
            ),
            port=int(os.environ.get("CODER_PORT", "8301")),
            public_https=os.environ.get(
                "CODER_PUBLIC_HTTPS",
                "",
            ).lower() in {"1", "true", "yes", "on"},
            workspace_root=os.environ.get(
                "CODER_WORKSPACE_ROOT",
                "./coder-workspaces",
            ),
            idle_timeout_seconds=idle_timeout_seconds,
            max_steps=max_steps,
            finalization_enabled=finalization_enabled,
            finalization_timeout_seconds=finalization_timeout_seconds,
            max_run_seconds=max_run_seconds,
            phase_tool_work_max_tokens=_phase_budget(
                "CODER_PHASE_TOOL_WORK_MAX_TOKENS"
            ),
            phase_error_recovery_max_tokens=_phase_budget(
                "CODER_PHASE_ERROR_RECOVERY_MAX_TOKENS"
            ),
            phase_final_synthesis_max_tokens=_phase_budget(
                "CODER_PHASE_FINAL_SYNTHESIS_MAX_TOKENS"
            ),
        )
