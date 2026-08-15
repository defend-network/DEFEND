from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
import os
from pathlib import Path
import re
import ipaddress
from typing import Literal
from urllib.parse import urlsplit


ApplicationId = Literal["defend", "scs", "sports"]
_APPLICATION_IDS = ("defend", "scs", "sports")
_UPPER_NAMESPACE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_COOKIE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def _port(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65_535:
        raise ValueError("application port must be an integer in 1..65535")
    return value


def _valid_hostname(hostname: str) -> bool:
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        pass
    try:
        ascii_hostname = hostname.encode("idna").decode("ascii").rstrip(".")
    except UnicodeError:
        return False
    if not ascii_hostname or len(ascii_hostname) > 253:
        return False
    return all(
        label
        and len(label) <= 63
        and label[0].isalnum()
        and label[-1].isalnum()
        and all(character.isalnum() or character == "-" for character in label)
        for label in ascii_hostname.split(".")
    )


def _canonical_origin(value: object) -> str:
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        raise ValueError("public_origin must be an HTTPS origin")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValueError("public_origin must be a valid HTTPS origin") from None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("public_origin must be an HTTPS origin without a path")
    hostname = parsed.hostname.rstrip(".").casefold()
    if not _valid_hostname(hostname):
        raise ValueError("public_origin must contain a valid hostname")
    netloc = hostname if port in {None, 443} else f"{hostname}:{port}"
    return f"https://{netloc}"


def _root_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve(strict=False)))


@dataclass(frozen=True)
class ApplicationContext:
    application_id: ApplicationId
    data_root: Path
    environment_prefix: str
    secret_namespace: str
    session_cookie: str
    public_origin: str
    api_port: int
    web_port: int

    def __post_init__(self) -> None:
        if self.application_id not in _APPLICATION_IDS:
            raise ValueError("application_id must be defend, scs, or sports")
        root = Path(self.data_root).expanduser()
        if not root.is_absolute():
            raise ValueError("data_root must be absolute")
        object.__setattr__(self, "data_root", root.resolve(strict=False))
        for name in ("environment_prefix", "secret_namespace"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _UPPER_NAMESPACE.fullmatch(value):
                raise ValueError(f"{name} must be an uppercase namespace")
        if not isinstance(self.session_cookie, str) or not _COOKIE_NAME.fullmatch(self.session_cookie):
            raise ValueError("session_cookie must be a lowercase cookie name")
        object.__setattr__(self, "public_origin", _canonical_origin(self.public_origin))
        object.__setattr__(self, "api_port", _port(self.api_port))
        object.__setattr__(self, "web_port", _port(self.web_port))
        if self.api_port == self.web_port:
            raise ValueError("api_port and web_port must be distinct")


def _roots_overlap(first: Path, second: Path) -> bool:
    first_root = _root_key(first)
    second_root = _root_key(second)
    try:
        common = os.path.commonpath((first_root, second_root))
    except ValueError:
        return False
    return common in {first_root, second_root}


def validate_applications(
    contexts: tuple[ApplicationContext, ...],
) -> tuple[ApplicationContext, ...]:
    """Validate two or more registered applications with isolated resources."""
    if len(contexts) < 2:
        raise ValueError("deployment requires at least two application contexts")

    by_id = {context.application_id: context for context in contexts}
    if len(by_id) != len(contexts):
        raise ValueError("deployment application ids must be unique")

    for first, second in combinations(contexts, 2):
        if _roots_overlap(first.data_root, second.data_root):
            raise ValueError("application data roots overlap")

        comparisons = {
            "environment prefix": (first.environment_prefix, second.environment_prefix),
            "secret namespace": (first.secret_namespace, second.secret_namespace),
            "session cookie": (first.session_cookie, second.session_cookie),
            "public origin": (first.public_origin, second.public_origin),
        }
        for label, (left, right) in comparisons.items():
            if left.casefold() == right.casefold():
                raise ValueError(f"cross-application {label} collision")

        first_ports = {first.api_port, first.web_port}
        second_ports = {second.api_port, second.web_port}
        if first_ports & second_ports:
            raise ValueError("cross-application port collision")

    return tuple(sorted(contexts, key=lambda context: _APPLICATION_IDS.index(context.application_id)))


def validate_application_pair(
    first: ApplicationContext,
    second: ApplicationContext,
) -> tuple[ApplicationContext, ApplicationContext]:
    """Compatibility validator for the established DEFEND/SCS deployment pair."""
    if first.application_id == second.application_id:
        raise ValueError("deployment requires exactly one defend and one scs context")

    validated = validate_applications((first, second))
    if {context.application_id for context in validated} != {"defend", "scs"}:
        raise ValueError("deployment requires exactly one defend and one scs context")

    by_id = {context.application_id: context for context in validated}
    return by_id["defend"], by_id["scs"]
