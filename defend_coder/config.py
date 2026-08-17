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
        )
