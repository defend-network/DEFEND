"""Vast destruction verification tests — fake transport; no live billing.

Regression coverage for the live false alarm: Vast reports a destroyed
instance as HTTP 200 with ``instances: null`` (same shape as a
never-existing ID), NOT as HTTP 404. Destruction must treat both as
confirmed absent, and must never claim the instance may still be
running unless the provider state genuinely cannot confirm absence.
"""

import json
from typing import Any

import pytest

from defend_control.vast import (
    VastClient,
    VastDestructionPendingError,
    VastDestructionRequestFailedError,
    VastDestructionUnverifiedError,
)

_ROOT = "https://console.vast.ai/api/v0"


class _Response:
    def __init__(self, status_code: int, body: bytes) -> None:
        self.status_code = status_code
        self.body = body


class _Clock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now


class ScriptedTransport:
    def __init__(self, clock: _Clock, responses: list[_Response]) -> None:
        self.clock = clock
        self._responses = responses
        self.requests: list[tuple[str, str]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: object | None,
        timeout: float,
        max_response_bytes: int,
    ) -> _Response:
        self.requests.append((method, url))
        assert max_response_bytes in (64 * 1024, 4 * 1024 * 1024)
        if not self._responses:
            raise AssertionError("no response scripted")
        return self._responses.pop(0)


class TransportError:
    """Transport whose GETs always fail; clock is advanced past the
    verification deadline on the first call."""

    def __init__(self, clock: _Clock) -> None:
        self.clock = clock
        self.requests: list[tuple[str, str]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: object | None,
        timeout: float,
        max_response_bytes: int,
    ) -> _Response:
        self.requests.append((method, url))
        assert max_response_bytes in (64 * 1024, 4 * 1024 * 1024)
        if method == "GET":
            self.clock.now += 31.0
            raise RuntimeError("verification endpoint unreachable")
        return _json_response({"success": True})


class RepeatingTransport:
    """Always returns the same response; only the DELETE is special."""

    def __init__(self, clock: _Clock, get_response: _Response) -> None:
        self.clock = clock
        self._get_response = get_response
        self.requests: list[tuple[str, str]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: object | None,
        timeout: float,
        max_response_bytes: int,
    ) -> _Response:
        self.requests.append((method, url))
        assert max_response_bytes in (64 * 1024, 4 * 1024 * 1024)
        if method == "GET":
            return self._get_response
        return _json_response({"success": True})


def _json_response(document: object, status_code: int = 200) -> _Response:
    return _Response(status_code, json.dumps(document).encode("utf-8"))


def _client(transport: Any) -> VastClient:
    clock = getattr(transport, "clock", None)
    return VastClient(
        "vast_synthetic_secret",
        transport=transport,  # type: ignore[arg-type]
        jitter=lambda: 1.0,
        monotonic=(lambda: clock.now) if clock is not None else None,
        sleep=(lambda seconds: setattr(clock, "now", clock.now + seconds))
        if clock is not None
        else None,
    )


def _instance_document(instance_id: int) -> dict[str, object]:
    return {
        "instances": [
            {
                "id": instance_id,
                "actual_status": "running",
                "ssh_host": "ssh.example.test",
                "ssh_port": 22,
                "gpu_name": "H100 PCIE",
                "gpu_ram": 81920,
                "dph_total": 4.3111,
                "direct_port_count": 1,
            }
        ]
    }


def test_destroy_confirmed_via_http_404_after_delayed_absence():
    clock = _Clock()
    transport = ScriptedTransport(
        clock,
        [
            _json_response({"success": True}),
            _json_response(_instance_document(47892785)),
            _Response(404, b""),
        ],
    )
    client = _client(transport)

    assert client.destroy_instance(
        47892785, confirmed_instance_id=47892785
    ) is True
    assert transport.requests == [
        ("DELETE", f"{_ROOT}/instances/47892785/"),
        ("GET", f"{_ROOT}/instances/47892785/"),
        ("GET", f"{_ROOT}/instances/47892785/"),
    ]


def test_destroy_confirmed_via_instances_null_200_regression():
    """The live false-alarm shape: absent instance is 200 + instances null."""
    clock = _Clock()
    transport = ScriptedTransport(
        clock,
        [
            _json_response({"success": True}),
            _json_response({"instances": None}),
        ],
    )
    client = _client(transport)

    assert client.destroy_instance(
        47892785, confirmed_instance_id=47892785
    ) is True


@pytest.mark.parametrize("absent", [{"instances": []}, {"instances": {}}])
def test_destroy_confirmed_via_empty_instances_shapes(absent: dict[str, object]):
    clock = _Clock()
    transport = ScriptedTransport(
        clock,
        [
            _json_response({"success": True}),
            _json_response(absent),
        ],
    )
    client = _client(transport)

    assert client.destroy_instance(
        47892785, confirmed_instance_id=47892785
    ) is True


def test_destroy_raises_pending_when_instance_still_visible():
    clock = _Clock()
    transport = RepeatingTransport(
        clock, _json_response(_instance_document(47892785))
    )
    client = _client(transport)

    with pytest.raises(VastDestructionPendingError):
        client.destroy_instance(47892785, confirmed_instance_id=47892785)


def test_destroy_raises_unverified_when_verification_only_errors():
    clock = _Clock()
    transport = TransportError(clock)
    client = _client(transport)

    with pytest.raises(VastDestructionUnverifiedError):
        client.destroy_instance(47892785, confirmed_instance_id=47892785)


def test_destroy_raises_request_failed_when_delete_rejected():
    clock = _Clock()
    transport = ScriptedTransport(
        clock,
        [_json_response({"success": False, "msg": "refused"}, status_code=400)],
    )
    client = _client(transport)

    with pytest.raises(VastDestructionRequestFailedError):
        client.destroy_instance(47892785, confirmed_instance_id=47892785)
    assert transport.requests == [("DELETE", f"{_ROOT}/instances/47892785/")]


def test_destroy_requires_exact_confirmed_instance_id():
    clock = _Clock()
    transport = ScriptedTransport(clock, [])
    client = _client(transport)

    with pytest.raises(ValueError):
        client.destroy_instance(47892785, confirmed_instance_id=47892786)
    assert transport.requests == []