from __future__ import annotations

import json
import socket

import pytest

from defend_coder.agent_client import (
    AgentChatClient,
    ModelError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from defend_coder.model_config import CoderModelConfig


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class FakeOpener:
    def __init__(self, behavior):
        self.behavior = behavior
        self.calls: list[tuple[str, dict, dict]] = []

    def __call__(self, request, timeout=None):
        self.calls.append(
            (request.full_url, json.loads(request.data), dict(request.headers))
        )
        behavior = self.behavior
        if callable(behavior):
            behavior = behavior(request)
        if isinstance(behavior, Exception):
            raise behavior
        return behavior


def _client(opener) -> AgentChatClient:
    return AgentChatClient(
        CoderModelConfig(
            alias="defendcoder-heavy",
            model_name="Qwen/Qwen3-Coder-Next",
            base_url="http://127.0.0.1:8001/v1",
            api_key="secret-api-key",
        ),
        timeout_seconds=30,
        urlopen=opener,
    )


def test_content_only_response_is_parsed():
    opener = FakeOpener(
        FakeResponse(
            json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "Done.",
                            }
                        }
                    ]
                }
            ).encode("utf-8")
        )
    )
    client = _client(opener)

    response = client.chat(
        [{"role": "user", "content": "hi"}],
        tools=[],
    )

    assert response.content == "Done."
    assert response.tool_calls == ()
    body = opener.calls[0][1]
    assert body["model"] == "Qwen/Qwen3-Coder-Next"
    assert "tools" not in body


def test_tool_calls_are_parsed():
    opener = FakeOpener(
        FakeResponse(
            json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "Reading the file.",
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "read_file",
                                            "arguments": (
                                                '{"path": "index.html"}'
                                            ),
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }
            ).encode("utf-8")
        )
    )
    client = _client(opener)

    response = client.chat(
        [{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "read_file"}}],
    )

    assert response.content == "Reading the file."
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].id == "call_1"
    assert response.tool_calls[0].name == "read_file"
    assert response.tool_calls[0].arguments == {"path": "index.html"}


def test_malformed_tool_arguments_are_preserved_raw():
    opener = FakeOpener(
        FakeResponse(
            json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "write_file",
                                            "arguments": "not-json",
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }
            ).encode("utf-8")
        )
    )
    client = _client(opener)

    response = client.chat([{"role": "user", "content": "hi"}])

    assert response.tool_calls[0].arguments == {
        "_raw_arguments": "not-json"
    }


def test_http_error_surfaces_as_model_error():
    import urllib.error

    opener = FakeOpener(
        urllib.error.HTTPError(
            "http://127.0.0.1:8001/v1/chat/completions",
            503,
            "Service Unavailable",
            {},
            None,
        )
    )
    client = _client(opener)

    with pytest.raises(ModelError, match="503"):
        client.chat([{"role": "user", "content": "hi"}])


def test_timeout_surfaces_as_model_timeout():
    opener = FakeOpener(socket.timeout("timed out"))
    client = _client(opener)

    with pytest.raises(ModelTimeoutError):
        client.chat([{"role": "user", "content": "hi"}])


def test_connection_error_surfaces_as_unavailable():
    import urllib.error

    opener = FakeOpener(
        urllib.error.URLError("connection refused")
    )
    client = _client(opener)

    with pytest.raises(ModelUnavailableError):
        client.chat([{"role": "user", "content": "hi"}])


def test_invalid_json_response_surfaces_as_model_error():
    opener = FakeOpener(FakeResponse(b"<html>not json</html>"))
    client = _client(opener)

    with pytest.raises(ModelError, match="invalid JSON"):
        client.chat([{"role": "user", "content": "hi"}])


def test_missing_choices_surfaces_as_model_error():
    opener = FakeOpener(FakeResponse(b'{"choices": []}'))
    client = _client(opener)

    with pytest.raises(ModelError):
        client.chat([{"role": "user", "content": "hi"}])


def test_auth_header_carries_api_key_but_payload_and_errors_never_do():
    opener = FakeOpener(
        FakeResponse(
            json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "ok",
                            }
                        }
                    ]
                }
            ).encode("utf-8")
        )
    )
    client = _client(opener)

    client.chat([{"role": "user", "content": "hi"}])

    _url, body, headers = opener.calls[0]
    assert headers["Authorization"] == "Bearer secret-api-key"
    assert "secret-api-key" not in json.dumps(body)
    assert "secret-api-key" not in repr(client._config)
    assert "secret-api-key" not in str(client)


def test_client_rejects_non_loopback_via_config():
    with pytest.raises(ValueError, match="loopback"):
        AgentChatClient(
            CoderModelConfig(base_url="http://remote.example.com/v1")
        )


def test_client_requires_base_url():
    with pytest.raises(ValueError, match="base_url"):
        AgentChatClient(CoderModelConfig(base_url=None))