from __future__ import annotations

import os

import pytest

from defend_coder.model_config import (
    CODER_MODEL_ALIAS_ENV,
    CODER_MODEL_API_KEY_ENV,
    CODER_MODEL_BASE_URL_ENV,
    CODER_MODEL_NAME_ENV,
    CoderModelConfig,
    load_model_config,
)


def _clear():
    for name in (
        CODER_MODEL_ALIAS_ENV,
        CODER_MODEL_NAME_ENV,
        CODER_MODEL_BASE_URL_ENV,
        CODER_MODEL_API_KEY_ENV,
        "CODER_MODEL_API_KEY_FILE",
    ):
        os.environ.pop(name, None)


def test_defaults_are_defendcoder_heavy():
    _clear()
    config = load_model_config()

    assert config.alias == "defendcoder-heavy"
    assert config.model_name == "Qwen/Qwen3-Coder-Next"
    assert config.base_url is None
    assert config.api_key is None
    assert config.requires_api_key is False


def test_env_values_are_honored():
    _clear()
    os.environ[CODER_MODEL_ALIAS_ENV] = "defendcoder-fast"
    os.environ[CODER_MODEL_NAME_ENV] = "Qwen/Qwen3-Coder-30B-A3B-Instruct"
    os.environ[CODER_MODEL_BASE_URL_ENV] = "http://localhost:8001/v1/"

    config = load_model_config()

    assert config.alias == "defendcoder-fast"
    assert config.model_name == "Qwen/Qwen3-Coder-30B-A3B-Instruct"
    assert config.base_url == "http://localhost:8001/v1"
    assert config.requires_api_key is False


def test_loopback_hosts_are_accepted():
    _clear()
    for url in (
        "http://127.0.0.1:8001/v1",
        "http://localhost:8001/v1",
        "http://[::1]:8001/v1",
        "https://127.0.0.1:8001/v1",
    ):
        config = CoderModelConfig(base_url=url)
        assert config.base_url == url.rstrip("/")


@pytest.mark.parametrize(
    "url",
    [
        "http://evil.example.com/v1",
        "https://model.vast.ai/v1",
        "ftp://127.0.0.1:8001/v1",
        "not-a-url",
        "http://192.168.1.5:8001/v1",
        "http://10.0.0.1:8001/v1",
    ],
)
def test_non_loopback_base_url_is_rejected(url):
    _clear()
    os.environ[CODER_MODEL_BASE_URL_ENV] = url

    with pytest.raises(ValueError, match="loopback"):
        load_model_config()

    with pytest.raises(ValueError, match="loopback"):
        CoderModelConfig(base_url=url)


def test_api_key_from_env_is_never_repr_visible():
    _clear()
    os.environ[CODER_MODEL_API_KEY_ENV] = "super-secret-key-123"

    config = load_model_config()

    assert config.api_key == "super-secret-key-123"
    assert config.requires_api_key is True
    assert "super-secret-key-123" not in repr(config)


def test_api_key_from_file(tmp_path):
    _clear()
    key_file = tmp_path / "key.txt"
    key_file.write_text(" file-secret-456 \n", encoding="utf-8")
    os.environ["CODER_MODEL_API_KEY_FILE"] = str(key_file)

    config = load_model_config()

    assert config.api_key == "file-secret-456"
    assert config.requires_api_key is True
    assert "file-secret-456" not in repr(config)


def test_empty_key_file_is_a_config_error(tmp_path):
    _clear()
    key_file = tmp_path / "empty.txt"
    key_file.write_text("   \n", encoding="utf-8")
    os.environ["CODER_MODEL_API_KEY_FILE"] = str(key_file)

    with pytest.raises(ValueError, match="empty"):
        load_model_config()


def test_missing_key_file_is_a_config_error(tmp_path):
    _clear()
    os.environ["CODER_MODEL_API_KEY_FILE"] = str(
        tmp_path / "missing.txt"
    )

    with pytest.raises(ValueError, match="read"):
        load_model_config()


def test_empty_alias_is_rejected():
    with pytest.raises(ValueError, match="alias"):
        CoderModelConfig(alias="  ")


def test_empty_model_name_is_rejected():
    with pytest.raises(ValueError, match="model_name"):
        CoderModelConfig(model_name="")