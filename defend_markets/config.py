from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path


_DEFAULT_DATA_ROOT = (
    Path(r"C:\DEFEND_MARKETS_DATA")
    if os.name == "nt"
    else Path("./DEFEND_MARKETS_DATA")
)


def _required_database_url() -> str:
    value = os.environ.get("MARKETS_DATABASE_URL")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("MARKETS_DATABASE_URL must be configured")
    return value


def _environment_value(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None:
        return default
    if not value.strip():
        raise ValueError(f"{name} must not be empty")
    return value


def _environment_port(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"{name} must be an integer") from None


def _environment_data_root() -> Path:
    value = os.environ.get("MARKETS_DATA_ROOT")
    if value is not None and not value.strip():
        raise ValueError("MARKETS_DATA_ROOT must not be empty")
    return Path(value if value is not None else _DEFAULT_DATA_ROOT).expanduser().resolve(
        strict=False
    )


@dataclass(frozen=True)
class MarketsSettings:
    data_root: Path
    database_url: str = field(repr=False)
    api_port: int = 8300
    web_port: int = 3300
    public_origin: str = "https://defendmarkets.defend-network.org"
    session_cookie: str = "markets_session"

    def __post_init__(self) -> None:
        data_root = Path(self.data_root).expanduser().resolve(strict=False)
        object.__setattr__(self, "data_root", data_root)
        if not isinstance(self.database_url, str) or not self.database_url.strip():
            raise ValueError("MARKETS_DATABASE_URL must be configured")

    @classmethod
    def from_env(cls) -> "MarketsSettings":
        return cls(
            data_root=_environment_data_root(),
            database_url=_required_database_url(),
            api_port=_environment_port("MARKETS_API_PORT", 8300),
            web_port=_environment_port("MARKETS_WEB_PORT", 3300),
            public_origin=_environment_value(
                "MARKETS_PUBLIC_ORIGIN", "https://defendmarkets.defend-network.org"
            ),
            session_cookie=_environment_value("MARKETS_SESSION_COOKIE", "markets_session"),
        )

    def application_context(self) -> "ApplicationContext":
        """Shared-platform registration for the markets application."""
        from shared_platform.application import ApplicationContext

        return ApplicationContext(
            application_id="markets",
            data_root=self.data_root,
            environment_prefix="MARKETS",
            secret_namespace="MARKETS",
            session_cookie=self.session_cookie,
            public_origin=self.public_origin,
            api_port=self.api_port,
            web_port=self.web_port,
        )