from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from scs_ai.config import (
    DEFAULT_API_PORT,
    DEFAULT_WEB_PORT,
    RESERVED_PLATFORM_PORTS,
    SCS_AI_PUBLIC_ORIGIN,
    ScsAiSettings,
)
from scs_ai.model_gateway import GatewayStatus, ModelGateway, ProviderProfile
from scs_ai.tools import TOOL_NAMES, ToolRegistry, ToolStatus
from scs_ai.tunnel import (
    EnvTokenSource,
    FileTokenSource,
    TunnelController,
    TunnelStatus,
)
from scs_ai.app import build_scs_ai_app


class FakeProcess:
    def __init__(self, pid: int = 1234) -> None:
        self._pid = int(pid)
        self.terminated = False
        self.killed = False
        self._poll_result: int | None = None
        self.suspended = False

    @property
    def pid(self) -> int:
        return self._pid

    def poll(self) -> int | None:
        return self._poll_result

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float | None = None) -> int:
        if self._poll_result is None:
            self._poll_result = 0
        return self._poll_result


class RecordingTokenSource:
    def __init__(self, token: str = "scs-ai-tunnel-secret-token") -> None:
        self.token = token

    def load(self) -> str:
        return self.token


def make_fake_popen(*procs):
    def _popen(argv, **kwargs):
        proc = procs[len(_popen.calls)]
        _popen.calls.append((tuple(argv), dict(kwargs)))
        return proc

    _popen.calls = []
    return _popen


def enabled_settings() -> ScsAiSettings:
    return ScsAiSettings(
        public_origin="https://ai.sunshineclimatesolutions.com",
        api_port=8300,
        web_port=3300,
        tunnel_enabled=True,
    )


def test_settings_defaults_use_locked_origin_and_deterministic_unused_ports():
    settings = ScsAiSettings.from_env()
    assert settings.public_origin == "https://ai.sunshineclimatesolutions.com"
    assert settings.api_port == DEFAULT_API_PORT == 8300
    assert settings.web_port == DEFAULT_WEB_PORT == 3300
    assert settings.api_port != settings.web_port


def test_scs_ai_default_ports_do_not_collide_with_platform_reservations():
    assert 8300 not in RESERVED_PLATFORM_PORTS
    assert 3300 not in RESERVED_PLATFORM_PORTS
    assert DEFAULT_API_PORT not in RESERVED_PLATFORM_PORTS
    assert DEFAULT_WEB_PORT not in RESERVED_PLATFORM_PORTS


def test_scs_ai_config_rejects_reserved_port_collisions():
    with pytest.raises(ValueError, match="reserved"):
        ScsAiSettings(
            public_origin="https://ai.sunshineclimatesolutions.com",
            api_port=8100,
            web_port=3300,
        )
    with pytest.raises(ValueError, match="reserved"):
        ScsAiSettings(
            public_origin="https://ai.sunshineclimatesolutions.com",
            api_port=8300,
            web_port=3100,
        )


def test_scs_ai_config_rejects_other_origins():
    with pytest.raises(ValueError, match="origin"):
        ScsAiSettings(
            public_origin="https://ai.defend-network.org",
            api_port=8300,
            web_port=3300,
        )


def test_scs_ai_env_prefix_is_distinct_from_platform_namespaces():
    for namespace in ("SCS_", "DEFEND_", "SPORTS_", "CODER_"):
        assert not namespace.startswith("SCS_AI_")
    assert SCS_AI_PUBLIC_ORIGIN == "https://ai.sunshineclimatesolutions.com"


def test_tunnel_token_never_appears_in_settings_status_or_argv(monkeypatch):
    settings = enabled_settings()
    assert "secret-token" not in repr(settings)
    assert "secret-token" not in str(settings)

    gateway = ModelGateway(alias=settings.model_alias)
    tools = ToolRegistry.default()
    source = RecordingTokenSource("scs-ai-tunnel-secret-token")
    proc = FakeProcess()
    popen = make_fake_popen(proc)
    tunnel = TunnelController(
        settings=settings,
        executable="C:/tools/cloudflared.exe",
        token_source=source,
        popen=popen,
        probe=lambda: True,
    )
    result = tunnel.start()
    argv = popen.calls[0][0]
    env = popen.calls[0][1]["env"]
    assert "scs-ai-tunnel-secret-token" not in tuple(argv)
    assert env.get("TUNNEL_TOKEN") == "scs-ai-tunnel-secret-token"
    assert "scs-ai-tunnel-secret-token" not in repr(result)
    assert "scs-ai-tunnel-secret-token" not in str(result)
    assert all(
        "scs-ai-tunnel-secret-token" not in entry[1] for entry in tunnel.logs()
    )


def test_tunnel_token_injected_via_environment_not_argv(monkeypatch):
    settings = enabled_settings()
    proc = FakeProcess()
    popen = make_fake_popen(proc)
    tunnel = TunnelController(
        settings=settings,
        executable="C:/tools/cloudflared.exe",
        token_source=RecordingTokenSource("env-only-secret"),
        popen=popen,
        probe=lambda: True,
    )
    tunnel.start()
    argv, kwargs = popen.calls[0]
    assert all("env-only-secret" not in argument for argument in argv)
    assert kwargs["env"]["TUNNEL_TOKEN"] == "env-only-secret"


def test_tunnel_token_env_source_reads_tunnel_token_environment(monkeypatch):
    monkeypatch.setenv("TUNNEL_TOKEN", "env-provided-token-value")
    source = EnvTokenSource()
    assert source.load() == "env-provided-token-value"
    monkeypatch.delenv("TUNNEL_TOKEN")
    with pytest.raises(ValueError, match="TUNNEL_TOKEN"):
        EnvTokenSource().load()


def test_tunnel_token_file_source_reads_protected_token_file(tmp_path):
    token_file = tmp_path / "tunnel.token"
    token_file.write_text("file-provided-token\n", encoding="utf-8")
    assert FileTokenSource(token_file).load() == "file-provided-token"
    with pytest.raises(ValueError, match="token"):
        FileTokenSource(tmp_path / "missing.token").load()


def test_tunnel_starts_and_reports_connected_when_probe_ok(monkeypatch):
    settings = enabled_settings()
    proc = FakeProcess()
    popen = make_fake_popen(proc)
    tunnel = TunnelController(
        settings=settings,
        executable="C:/tools/cloudflared.exe",
        token_source=RecordingTokenSource(),
        popen=popen,
        probe=lambda: True,
    )
    assert tunnel.status().state == "stopped"
    result = tunnel.start()
    assert result.state == "connected"
    assert result.pid == proc.pid
    assert tunnel.status().state == "connected"


def test_tunnel_starting_until_probe_ok(monkeypatch):
    settings = enabled_settings()
    proc = FakeProcess()
    popen = make_fake_popen(proc)
    tunnel = TunnelController(
        settings=settings,
        executable="C:/tools/cloudflared.exe",
        token_source=RecordingTokenSource(),
        popen=popen,
        probe=lambda: False,
    )
    result = tunnel.start()
    assert result.state == "starting"
    assert tunnel.status().state == "starting"


def test_tunnel_unhealthy_when_process_exits(monkeypatch):
    settings = enabled_settings()
    proc = FakeProcess()
    proc._poll_result = 1
    popen = make_fake_popen(proc)
    tunnel = TunnelController(
        settings=settings,
        executable="C:/tools/cloudflared.exe",
        token_source=RecordingTokenSource(),
        popen=popen,
        probe=lambda: True,
    )
    tunnel.start()
    assert tunnel.status().state == "unhealthy"
    assert tunnel.status().returncode == 1


def test_tunnel_stop_only_terminates_its_own_process(monkeypatch):
    settings = enabled_settings()
    own = FakeProcess(pid=111)
    other = FakeProcess(pid=222)
    popen = make_fake_popen(own)
    tunnel = TunnelController(
        settings=settings,
        executable="C:/tools/cloudflared.exe",
        token_source=RecordingTokenSource(),
        popen=popen,
        probe=lambda: True,
    )
    tunnel.start()
    tunnel.stop()
    assert own.terminated is True
    assert other.terminated is False
    assert other.killed is False
    assert tunnel.status().state == "stopped"


def test_tunnel_never_queries_or_terminates_unowned_processes(monkeypatch):
    settings = enabled_settings()
    own = FakeProcess(pid=333)
    popen = make_fake_popen(own)
    tunnel = TunnelController(
        settings=settings,
        executable="C:/tools/cloudflared.exe",
        token_source=RecordingTokenSource(),
        popen=popen,
        probe=lambda: True,
    )
    tunnel.start()
    tunnel.stop()
    assert own.terminated is True
    assert tunnel.status().state == "stopped"


def test_tunnel_disabled_never_starts_a_process(monkeypatch):
    settings = enabled_settings()
    proc = FakeProcess()
    popen = make_fake_popen(proc)
    tunnel = TunnelController(
        settings=settings,
        executable="C:/tools/cloudflared.exe",
        token_source=RecordingTokenSource(),
        popen=popen,
        probe=lambda: True,
    )
    assert tunnel.status().state == "stopped"
    tunnel.stop()
    assert popen.calls == []


def test_model_gateway_is_provider_neutral_and_unconfigured_by_default():
    gateway = ModelGateway(alias=None)
    status = gateway.status()
    assert status.state == "not_configured"
    assert status.ready is False
    assert gateway.client() is None


def test_model_gateway_alias_resolves_provider_without_model_client_import():
    providers = {
        "qwen3-vl-32b": ProviderProfile(
            provider_id="openai_compatible",
            model_name="Qwen/Qwen3-VL-32B-Instruct",
            base_url="http://127.0.0.1:8301/v1",
            requires_api_key=False,
        )
    }
    gateway = ModelGateway(alias="qwen3-vl-32b", providers=providers)
    status = gateway.status()
    assert status.alias == "qwen3-vl-32b"
    assert status.provider == "openai_compatible"
    assert status.model_name == "Qwen/Qwen3-VL-32B-Instruct"
    assert status.ready is True


def test_model_gateway_unknown_alias_is_not_ready():
    gateway = ModelGateway(alias="does-not-exist")
    status = gateway.status()
    assert status.state == "not_configured"
    assert status.ready is False


def test_model_gateway_status_contains_no_secrets():
    providers = {
        "qwen3-vl-32b": ProviderProfile(
            provider_id="openai_compatible",
            model_name="Qwen/Qwen3-VL-32B-Instruct",
            base_url="http://127.0.0.1:8301/v1",
            requires_api_key=True,
        )
    }
    gateway = ModelGateway(alias="qwen3-vl-32b", providers=providers, api_key="super-secret-key")
    status = gateway.status()
    assert "super-secret-key" not in repr(status)
    assert "super-secret-key" not in str(status)


def test_tool_registry_exposes_honest_unconfigured_boundary():
    registry = ToolRegistry.default()
    statuses = registry.status()
    names = {status.name for status in statuses}
    assert names == set(TOOL_NAMES)
    assert all(status.state in ("not_configured", "unavailable") for status in statuses)
    assert all(status.name for status in statuses)


def test_health_is_truthful_before_model_configuration():
    settings = ScsAiSettings.from_env()
    gateway = ModelGateway(alias=None)
    tools = ToolRegistry.default()
    tunnel = TunnelController(
        settings=settings,
        executable="C:/tools/cloudflared.exe",
        token_source=RecordingTokenSource(),
        probe=lambda: True,
    )
    app = build_scs_ai_app(settings, gateway=gateway, tunnel=tunnel, tools=tools)
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["application_id"] == "scs"
        assert body["service"] == "scs-ai"
        assert body["api"]["state"] == "ready"
        assert body["model_gateway"]["state"] == "not_configured"
        assert body["model_gateway"]["ready"] is False
        assert body["model_gateway"].get("alias") is None
        assert body["tools"]["state"] == "not_configured"


def test_system_status_reports_honest_state_and_no_secrets():
    settings = ScsAiSettings.from_env()
    gateway = ModelGateway(alias=None)
    tools = ToolRegistry.default()
    tunnel = TunnelController(
        settings=settings,
        executable="C:/tools/cloudflared.exe",
        token_source=RecordingTokenSource("status-secret-token"),
        probe=lambda: True,
    )
    app = build_scs_ai_app(settings, gateway=gateway, tunnel=tunnel, tools=tools)
    with TestClient(app) as client:
        response = client.get("/v1/system/status")
        assert response.status_code == 200
        text = response.text
        assert "status-secret-token" not in text
        assert "ai.sunshineclimatesolutions.com" in text
        body = response.json()
        assert body["application_id"] == "scs"
        assert body["service"] == "scs-ai"
        assert body["public_origin"] == "https://ai.sunshineclimatesolutions.com"
        assert body["tunnel"]["state"] in ("stopped", "starting", "connected", "unhealthy")


def test_scs_ai_api_starts_independently_of_scs_product(monkeypatch):
    settings = ScsAiSettings.from_env()
    gateway = ModelGateway(alias=None)
    tools = ToolRegistry.default()
    tunnel = TunnelController(
        settings=settings,
        executable="C:/tools/cloudflared.exe",
        token_source=RecordingTokenSource(),
        probe=lambda: True,
    )
    app = build_scs_ai_app(settings, gateway=gateway, tunnel=tunnel, tools=tools)
    with TestClient(app, base_url="https://ai.sunshineclimatesolutions.com") as client:
        assert client.get("/health").status_code == 200
        assert client.get("/v1/system/status").status_code == 200


def test_runtime_composition_builds_fastapi_app():
    import importlib

    module = importlib.import_module("scs_ai.runtime")
    assert module.app.title == "Sunshine Climate Solutions AI Service"
    assert module.context.public_origin == "https://ai.sunshineclimatesolutions.com"