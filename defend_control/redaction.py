from collections.abc import Iterable
import re


_MAX_INPUT_BYTES = 64 * 1024
_MAX_OUTPUT_BYTES = 16 * 1024
_REDACTED = "[REDACTED]"
_SECRET_KEY = (
    r"[A-Za-z0-9_.-]*"
    r"(?:token|password|secret|cookie|authorization|api_key|app_password)"
    r"[A-Za-z0-9_.-]*"
)
_QUOTED_VALUE = re.compile(
    rf"(?P<prefix>(?<![A-Za-z0-9_.-])[\"']?{_SECRET_KEY}[\"']?\s*[:=]\s*)"
    rf"(?P<quote>[\"'])(?P<value>.*?)(?P=quote)",
    re.IGNORECASE,
)
_AUTHORIZATION_VALUE = re.compile(
    rf"(?P<prefix>(?<![A-Za-z0-9_.-])[\"']?{_SECRET_KEY}[\"']?\s*[:=]\s*)"
    r"(?P<value>Bearer\s+[^\s,;}\]]+)",
    re.IGNORECASE,
)
_UNQUOTED_VALUE = re.compile(
    rf"(?P<prefix>(?<![A-Za-z0-9_.-])[\"']?{_SECRET_KEY}[\"']?\s*[:=]\s*)"
    r"(?P<value>[^\s,;}\]]+)",
    re.IGNORECASE,
)


def _truncate_utf8(value: str, limit: int) -> str:
    encoded = value.encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return value
    return encoded[:limit].decode("utf-8", errors="ignore")


def redact_text(value: str, known_secrets: Iterable[str]) -> str:
    """Redact exact and secret-shaped values within strict UTF-8 byte bounds."""

    cleaned = _truncate_utf8(value, _MAX_INPUT_BYTES)
    secrets = sorted(
        {
            secret
            for secret in known_secrets
            if isinstance(secret, str) and secret and secret != _REDACTED
        },
        key=len,
        reverse=True,
    )

    for _ in range(3):
        previous = cleaned
        for secret in secrets:
            cleaned = cleaned.replace(secret, _REDACTED)
        cleaned = _QUOTED_VALUE.sub(
            lambda match: (
                f"{match.group('prefix')}{match.group('quote')}"
                f"{_REDACTED}{match.group('quote')}"
            ),
            cleaned,
        )
        cleaned = _AUTHORIZATION_VALUE.sub(
            lambda match: f"{match.group('prefix')}{_REDACTED}", cleaned
        )
        cleaned = _UNQUOTED_VALUE.sub(
            lambda match: f"{match.group('prefix')}{_REDACTED}", cleaned
        )
        if cleaned == previous:
            break

    return _truncate_utf8(cleaned, _MAX_OUTPUT_BYTES)
