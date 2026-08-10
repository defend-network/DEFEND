from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets


_SCRYPT_N = 1 << 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 64
_SCRYPT_MAXMEM = 128 * 1024 * 1024
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
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        maxmem=_SCRYPT_MAXMEM,
        dklen=_SCRYPT_DKLEN,
    )
    return (
        f"scrypt$n={_SCRYPT_N},r={_SCRYPT_R},p={_SCRYPT_P},dklen={_SCRYPT_DKLEN}"
        f"${_b64encode(salt)}${_b64encode(derived)}"
    )


def verify_password(password: str, encoded: str) -> bool:
    if not isinstance(password, str) or not isinstance(encoded, str):
        return False
    try:
        algorithm, parameters, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "scrypt":
            return False
        parsed = dict(part.split("=", 1) for part in parameters.split(","))
        n = int(parsed["n"])
        r = int(parsed["r"])
        p = int(parsed["p"])
        dklen = int(parsed["dklen"])
        # Refuse attacker-controlled, unexpectedly expensive hash parameters.
        if n != _SCRYPT_N or r != _SCRYPT_R or p != _SCRYPT_P or dklen != _SCRYPT_DKLEN:
            return False
        salt = _b64decode(salt_text)
        expected = _b64decode(digest_text)
        if len(salt) != 16 or len(expected) != dklen:
            return False
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            maxmem=_SCRYPT_MAXMEM,
            dklen=dklen,
        )
    except (KeyError, TypeError, ValueError):
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
