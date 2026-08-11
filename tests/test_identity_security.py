from __future__ import annotations

import base64
import hashlib

from defend_data.identity_security import (
    hash_password,
    new_token,
    normalize_email,
    password_needs_rehash,
    verify_password,
)


def test_email_normalization_strips_and_casefolds():
    assert normalize_email("  Chairman@DEFEND-NETWORK.ORG  ") == "chairman@defend-network.org"


def test_scrypt_hash_round_trip():
    encoded = hash_password("correct horse battery staple")
    assert encoded.startswith("scrypt$v=2$n=131072,r=8,p=1,dklen=64$")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong", encoded)
    assert not password_needs_rehash(encoded)


def test_legacy_scrypt_hash_verifies_and_requests_rehash():
    password = "legacy password"
    salt = b"0123456789abcdef"
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=1 << 14,
        r=8,
        p=1,
        maxmem=128 * 1024 * 1024,
        dklen=64,
    )
    def encode(value):
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    legacy = f"scrypt$n=16384,r=8,p=1,dklen=64${encode(salt)}${encode(digest)}"

    assert verify_password(password, legacy)
    assert password_needs_rehash(legacy)


def test_password_verification_rejects_malformed_hashes():
    assert not verify_password("correct horse battery staple", "not-a-password-hash")
    assert not verify_password("correct horse battery staple", "scrypt$bad$parameters")
    encoded = hash_password("correct horse battery staple")
    duplicate_parameter = encoded.replace("$n=", "$n=1,n=", 1)
    assert not verify_password("correct horse battery staple", duplicate_parameter)
    assert password_needs_rehash(duplicate_parameter)


def test_new_token_returns_prefixed_secret_and_distinct_hash():
    first_token, first_hash = new_token("inv")
    second_token, second_hash = new_token("inv")

    assert first_token.startswith("inv_")
    assert first_token != second_token
    assert first_hash != second_hash
    assert first_token not in first_hash
