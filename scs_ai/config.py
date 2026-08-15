from __future__ import annotations

from dataclasses import dataclass
import os
import re

from shared_platform.application import _canonical_origin

SCS_AI_PUBLIC_ORIGIN = "https://ai.sunshineclimatesolutions.com"
DEFAULT_API_PORT = 8300
DEFAULT_WEB_PORT = 3300
DEFAULT_MODEL_ALIAS = None

_RESERVED_PLATFORM_PORTS = (
    3000,   # DEFEND web
    8000,   # DEFEND api
    8001,   # DEFEND model
    3100,   # SCS web
    8100,   # SCS api
    3200,   # Sports web
    8200,   # Sports api
)

_PUBLIC_ORIGIN_VALID = re.compile(r"^https://ai\.sunshineclimatesolutions\.com$")
_PORT = re.compile(r"^[0-9]{1,5}$")
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def _port(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65_535:
        raise ValueError(f"{name} must be an integer port in 1..65535")
    return value


def _environment(value: str | None, name: str, default: str) -> str:
    if value is None or not value.strip():
        return default
    return value.strip()


@dataclass(frozen=True)
class ScsAiSettings:
    public_origin: str
    api_port: int
    web_port: int
    model_alias: str | None = None
    tunnel_enabled: bool = False

    def __post_init__(self) -> None:
        origin = self.public_origin
        if not isinstance(origin, str) or not _PUBLIC_ORIGIN_VALID.match(origin):
            raise ValueError("SCS AI public_origin must be exactly the locked SCS AI origin")
        object.__setattr__(self, "public_origin", _canonical_origin(origin))
        object.__setattr__(self, "api_port", _port(self.api_port, "api_port"))
        object.__setattr__(self, "web_port", _port(self.web_port, "web_port"))
        if self.api_port == self.web_port:
            raise ValueError("api_port and web_port must be distinct")
        for port in (self.api_port, self.web_port):
            if port in _RESERVED_PLATFORM_PORTS:
                raise ValueError(
                    f"port {port} is reserved for another platform application"
                )
        if self.model_alias is not None:
            if not isinstance(self.model_alias, str) or not self.model_alias.strip():
                raise ValueError("model_alias must not be empty")
            object.__setattr__(self, "model_alias", self.model_alias.strip())

    @classmethod
    def from_env(cls) -> "ScsAiSettings":
        return cls(
            public_origin=_environment(
                os.environ.get("SCS_AI_PUBLIC_ORIGIN"),
                "SCS_AI_PUBLIC_ORIGIN",
                SCS_AI_PUBLIC_ORIGIN,
            ),
            api_port=int(
                _environment(
                    os.environ.get("SCS_AI_API_PORT"),
                    "SCS_AI_API_PORT",
                    str(DEFAULT_API_PORT),
                )
            ),
            web_port=int(
                _environment(
                    os.environ.get("SCS_AI_WEB_PORT"),
                    "SCS_AI_WEB_PORT",
                    str(DEFAULT_WEB_PORT),
                )
            ),
            model_alias=(
                os.environ.get("SCS_AI_MODEL_ALIAS") or DEFAULT_MODEL_ALIAS
            ),
            tunnel_enabled=(
                _environment(
                    os.environ.get("SCS_AI_TUNNEL_ENABLED"),
                    "SCS_AI_TUNNEL_ENABLED",
                    "false",
                ).casefold()
                in _TRUE_VALUES
            ),
        )


RESERVED_PLATFORM_PORTS = _RESERVED_PLATFORM_PORTS