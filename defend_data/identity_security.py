from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets


_CURRENT_SCRYPT_VERSION = 2
_SCRYPT_PROFILES = {
    1: {"n": 1 << 14, "r": 8, "p": 1, "dklen": 64, "maxmem": 128 * 1024 * 1024},
    2: {"n": 1 << 17, "r": 8, "p": 1, "dklen": 64, "maxmem": 256 * 1024 * 1024},
}
_TOKEN_PREFIX_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")


def normalize_email(value: str) -> str:
    """Return the canonical form used for account lookup and uniqueness."""
    if not isinstance(value, str):
        raise TypeError("email must be a string")
    normalized = value.strip().casefold()
    if normalized.count("@") != 1:
        raise ValueError("email must contain one @")
    local, domain = normalized.split("@", 1)
    if not local or not domain:
        raise ValueError("email must include a local part and domain")
    return normalized


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    if not isinstance(password, str):
        raise TypeError("password must be a string")
    if not password:
        raise ValueError("password must not be empty")
    profile = _SCRYPT_PROFILES[_CURRENT_SCRYPT_VERSION]
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=profile["n"],
        r=profile["r"],
        p=profile["p"],
        maxmem=profile["maxmem"],
        dklen=profile["dklen"],
    )
    return (
        f"scrypt$v={_CURRENT_SCRYPT_VERSION}"
        f"$n={profile['n']},r={profile['r']},p={profile['p']},dklen={profile['dklen']}"
        f"${_b64encode(salt)}${_b64encode(derived)}"
    )


def _parse_password_hash(encoded: str) -> tuple[int, dict[str, int], bytes, bytes]:
    parts = encoded.split("$")
    if len(parts) == 4:
        algorithm, parameters, salt_text, digest_text = parts
        version = 1
    elif len(parts) == 5:
        algorithm, version_text, parameters, salt_text, digest_text = parts
        if not version_text.startswith("v="):
            raise ValueError("missing scrypt version")
        version = int(version_text.removeprefix("v="))
    else:
        raise ValueError("invalid password hash fields")
    if algorithm != "scrypt" or version not in _SCRYPT_PROFILES:
        raise ValueError("unsupported password hash")
    parameter_parts = parameters.split(",")
    if len(parameter_parts) != 4:
        raise ValueError("invalid scrypt parameters")
    parsed = dict(part.split("=", 1) for part in parameter_parts)
    if set(parsed) != {"n", "r", "p", "dklen"}:
        raise ValueError("invalid scrypt parameters")
    actual_profile = {name: int(value) for name, value in parsed.items()}
    expected_profile = _SCRYPT_PROFILES[version]
    for name in ("n", "r", "p", "dklen"):
        if actual_profile[name] != expected_profile[name]:
            raise ValueError("unexpected scrypt parameters")
    salt = _b64decode(salt_text)
    expected = _b64decode(digest_text)
    if len(salt) != 16 or len(expected) != actual_profile["dklen"]:
        raise ValueError("invalid scrypt material")
    return version, expected_profile, salt, expected


def password_needs_rehash(encoded: str) -> bool:
    if not isinstance(encoded, str):
        return True
    try:
        version, _, _, _ = _parse_password_hash(encoded)
    except (KeyError, TypeError, ValueError):
        return True
    return version != _CURRENT_SCRYPT_VERSION


def verify_password(password: str, encoded: str) -> bool:
    if not isinstance(password, str) or not isinstance(encoded, str):
        return False
    try:
        _, profile, salt, expected = _parse_password_hash(encoded)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=profile["n"],
            r=profile["r"],
            p=profile["p"],
            maxmem=profile["maxmem"],
            dklen=profile["dklen"],
        )
    except (KeyError, MemoryError, OverflowError, TypeError, ValueError):
        return False
    return hmac.compare_digest(actual, expected)


def token_hash(token: str) -> str:
    if not isinstance(token, str):
        raise TypeError("token must be a string")
    return "sha256$" + hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token(prefix: str) -> tuple[str, str]:
    """Return a caller-visible random token and its persistence-safe hash."""
    if not isinstance(prefix, str) or not _TOKEN_PREFIX_RE.fullmatch(prefix):
        raise ValueError("invalid token prefix")
    token = f"{prefix}_{secrets.token_urlsafe(32)}"
    return token, token_hash(token)
