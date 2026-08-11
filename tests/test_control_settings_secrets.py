from dataclasses import FrozenInstanceError
from decimal import Decimal
import json
from pathlib import Path
import sys

import pytest

from defend_control.redaction import redact_text
from defend_control.secrets import DpapiSecretStore
from defend_control.settings import ControlSettings, JsonSettingsStore


class ReversingBackend:
    def protect(self, data: bytes) -> bytes:
        return data[::-1]

    def unprotect(self, data: bytes) -> bytes:
        return data[::-1]


class IdentityBackend:
    def protect(self, data: bytes) -> bytes:
        return data

    def unprotect(self, data: bytes) -> bytes:
        return data


def valid_settings(tmp_path: Path) -> dict[str, object]:
    return {
        "repo_root": str(tmp_path),
        "data_root": r"C:\DEFEND_DATA",
        "public_web_origin": "https://ai.defend-network.org",
        "cloudflared_exe": r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
        "cloudflared_config": r"C:\Users\operator\.cloudflared\config.yml",
        "cloudflared_tunnel": "defend-ai",
        "adapter_repo": "Defend-network/defend-qwen-32b-lora",
        "local_model": "defend-ai:latest",
        "vast_max_hourly": "3.00",
    }


def test_rejects_non_https_public_origin(tmp_path):
    raw = valid_settings(tmp_path)
    raw["public_web_origin"] = "http://public.example"
    with pytest.raises(ValueError, match="HTTPS"):
        ControlSettings.from_mapping(raw)


def test_secret_store_never_writes_plaintext(tmp_path):
    path = tmp_path / "secrets.dpapi"
    store = DpapiSecretStore(path, backend=ReversingBackend(), acl=lambda _: None)
    store.save({"HF_TOKEN": "hf_private_value"})
    assert b"hf_private_value" not in path.read_bytes()
    assert store.load()["HF_TOKEN"] == "hf_private_value"


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_real_dpapi_round_trip_is_current_user_scoped(tmp_path):
    path = tmp_path / "real-secrets.dpapi"
    store = DpapiSecretStore(path)
    store.save({"DEFEND_OWNER_PASS": "temporary-test-value"})
    assert store.load() == {"DEFEND_OWNER_PASS": "temporary-test-value"}
    assert b"temporary-test-value" not in path.read_bytes()


def test_redacts_known_and_secret_shaped_values():
    raw = "Authorization: Bearer hf_private_value password=visible"
    cleaned = redact_text(raw, ["hf_private_value"])
    assert "hf_private_value" not in cleaned
    assert "visible" not in cleaned


def test_settings_are_frozen_and_apply_required_defaults(tmp_path):
    settings = ControlSettings.from_mapping(valid_settings(tmp_path))

    assert settings.repo_root == tmp_path
    assert settings.vast_max_hourly == Decimal("3.00")
    assert (settings.api_port, settings.web_port, settings.model_port) == (
        8000,
        3000,
        8001,
    )
    with pytest.raises(FrozenInstanceError):
        settings.api_port = 9000  # type: ignore[misc]


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("repo_root", ".", "absolute"),
        ("public_web_origin", "https://example.test/path", "origin"),
        ("adapter_repo", "public/wrong-adapter", "adapter_repo"),
        ("vast_max_hourly", "0", "positive"),
        ("vast_max_hourly", "NaN", "finite"),
        ("api_port", 0, "port"),
        ("api_port", True, "port"),
    ],
)
def test_rejects_invalid_settings_values(tmp_path, key, value, message):
    raw = valid_settings(tmp_path)
    raw[key] = value

    with pytest.raises(ValueError, match=message):
        ControlSettings.from_mapping(raw)


def test_rejects_nonexistent_repo_root(tmp_path):
    raw = valid_settings(tmp_path)
    raw["repo_root"] = str(tmp_path / "missing")

    with pytest.raises(ValueError, match="existing"):
        ControlSettings.from_mapping(raw)


def test_rejects_unknown_settings_keys(tmp_path):
    raw = valid_settings(tmp_path)
    raw["HF_TOKEN"] = "must-not-be-a-setting"

    with pytest.raises(ValueError, match="unknown"):
        ControlSettings.from_mapping(raw)


def test_rejects_duplicate_ports(tmp_path):
    raw = valid_settings(tmp_path)
    raw["model_port"] = 8000

    with pytest.raises(ValueError, match="unique"):
        ControlSettings.from_mapping(raw)


def test_json_settings_store_round_trip(tmp_path):
    path = tmp_path / "control-center.json"
    store = JsonSettingsStore(path)
    expected = ControlSettings.from_mapping(valid_settings(tmp_path))

    store.save(expected)

    assert store.load() == expected
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["vast_max_hourly"] == "3.00"
    assert persisted["adapter_repo"] == "Defend-network/defend-qwen-32b-lora"


def test_secret_store_rejects_non_string_values(tmp_path):
    store = DpapiSecretStore(
        tmp_path / "secrets.dpapi",
        backend=IdentityBackend(),
        acl=lambda _: None,
    )

    with pytest.raises(ValueError, match="strings"):
        store.save({"HF_TOKEN": 123})  # type: ignore[dict-item]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"", "empty"),
        (b'{"version":2,"values":{}}', "version"),
        (b'{"version":true,"values":{}}', "version"),
        (b'{"version":1.0,"values":{}}', "version"),
        (b'{"version":1,"values":{"TOKEN":4}}', "strings"),
    ],
)
def test_secret_store_rejects_invalid_decrypted_payloads(tmp_path, payload, message):
    path = tmp_path / "secrets.dpapi"
    path.write_bytes(payload)
    store = DpapiSecretStore(path, backend=IdentityBackend(), acl=lambda _: None)

    with pytest.raises(ValueError, match=message):
        store.load()


def test_secret_store_rejects_payloads_over_64_kib(tmp_path):
    path = tmp_path / "secrets.dpapi"
    path.write_bytes(b"x" * (64 * 1024 + 1))
    store = DpapiSecretStore(path, backend=IdentityBackend(), acl=lambda _: None)

    with pytest.raises(ValueError, match="64 KiB"):
        store.load()


def test_secret_store_protects_before_opening_destination(tmp_path):
    path = tmp_path / "secrets.dpapi"

    class FailingBackend(IdentityBackend):
        def protect(self, data: bytes) -> bytes:
            raise RuntimeError("synthetic protection failure")

    store = DpapiSecretStore(path, backend=FailingBackend(), acl=lambda _: None)

    with pytest.raises(RuntimeError, match="synthetic protection failure"):
        store.save({"TOKEN": "synthetic-value"})
    assert not path.exists()


def test_secret_store_failed_acl_does_not_replace_existing_file(tmp_path):
    path = tmp_path / "secrets.dpapi"
    store = DpapiSecretStore(path, backend=ReversingBackend(), acl=lambda _: None)
    store.save({"TOKEN": "old-synthetic-value"})

    def reject_acl(_: Path) -> None:
        raise OSError("synthetic ACL failure")

    failing = DpapiSecretStore(path, backend=ReversingBackend(), acl=reject_acl)
    with pytest.raises(OSError, match="synthetic ACL failure"):
        failing.save({"TOKEN": "new-synthetic-value"})

    assert store.load() == {"TOKEN": "old-synthetic-value"}


def test_redacts_case_insensitive_secret_key_shapes():
    raw = (
        "X-Access-Token: alpha\n"
        "database_PASSWORD=bravo\n"
        '"client_secret": "charlie"\n'
        "Cookie: delta\n"
        "x-authorization: Bearer echo\n"
        "API_KEY=foxtrot\n"
        "app_password: golf\n"
        "safe=hotel"
    )

    cleaned = redact_text(raw, [])

    for secret in ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf"):
        assert secret not in cleaned
    assert "safe=hotel" in cleaned


def test_redaction_handles_literal_known_secrets_and_utf8_byte_bounds():
    cleaned = redact_text("prefix a+b? suffix " + "é" * 70_000, ["a+b?"])

    assert "a+b?" not in cleaned
    assert len(cleaned.encode("utf-8")) <= 16 * 1024
