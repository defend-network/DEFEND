from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path

from shared_platform.application import ApplicationContext


_DEFAULT_DATA_ROOT = (
    Path(r"C:\DEFEND_SPORTS_DATA")
    if os.name == "nt"
    else Path("./DEFEND_SPORTS_DATA")
)


def _required_database_url() -> str:
    value = os.environ.get("SPORTS_DATABASE_URL")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("SPORTS_DATABASE_URL must be configured")
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
    value = os.environ.get("SPORTS_DATA_ROOT")
    if value is not None and not value.strip():
        raise ValueError("SPORTS_DATA_ROOT must not be empty")
    return Path(value if value is not None else _DEFAULT_DATA_ROOT).expanduser().resolve(
        strict=False
    )


@dataclass(frozen=True)
class SportsSettings:
    data_root: Path
    database_url: str = field(repr=False)
    api_port: int = 8200
    web_port: int = 3200
    public_origin: str = "https://defendsports.defend-network.org"
    session_cookie: str = "sports_session"

    def __post_init__(self) -> None:
        data_root = Path(self.data_root).expanduser().resolve(strict=False)
        object.__setattr__(self, "data_root", data_root)
        if not isinstance(self.database_url, str) or not self.database_url.strip():
            raise ValueError("SPORTS_DATABASE_URL must be configured")
        self.application_context()

    @classmethod
    def from_env(cls) -> "SportsSettings":
        return cls(
            data_root=_environment_data_root(),
            database_url=_required_database_url(),
            api_port=_environment_port("SPORTS_API_PORT", 8200),
            web_port=_environment_port("SPORTS_WEB_PORT", 3200),
            public_origin=_environment_value(
                "SPORTS_PUBLIC_ORIGIN", "https://defendsports.defend-network.org"
            ),
            session_cookie=_environment_value("SPORTS_SESSION_COOKIE", "sports_session"),
        )

    def application_context(self) -> ApplicationContext:
        return ApplicationContext(
            application_id="sports",
            data_root=self.data_root,
            environment_prefix="SPORTS",
            secret_namespace="SPORTS",
            session_cookie=self.session_cookie,
            public_origin=self.public_origin,
            api_port=self.api_port,
            web_port=self.web_port,
        )
