from __future__ import annotations

from defend_data.identity_security import (
    hash_password,
    new_token,
    normalize_email,
    verify_password,
)


def test_email_normalization_strips_and_casefolds():
    assert normalize_email("  Chairman@DEFEND-NETWORK.ORG  ") == "chairman@defend-network.org"


def test_scrypt_hash_round_trip():
    encoded = hash_password("correct horse battery staple")
    assert encoded.startswith("scrypt$")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong", encoded)


def test_password_verification_rejects_malformed_hashes():
    assert not verify_password("correct horse battery staple", "not-a-password-hash")
    assert not verify_password("correct horse battery staple", "scrypt$bad$parameters")


def test_new_token_returns_prefixed_secret_and_distinct_hash():
    first_token, first_hash = new_token("inv")
    second_token, second_hash = new_token("inv")

    assert first_token.startswith("inv_")
    assert first_token != second_token
    assert first_hash != second_hash
    assert first_token not in first_hash
