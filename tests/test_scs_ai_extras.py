from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from scs_ai import calculations
from scs_ai.app import build_scs_ai_app
from scs_ai.chat import ScsAssistant
from scs_ai.client import ModelError, OpenAiCompatibleChatClient
from scs_ai.config import ScsAiSettings
from scs_ai.model_gateway import ModelGateway, ProviderProfile
from scs_ai.office.toolkit import OfficeToolkit
from scs_ai.providers import ScsAiModelConfig, load_model_config
from scs_ai.tools import ToolRegistry
from scs_ai.tunnel import TunnelController


class _FakeTunnel:
    def status(self) -> object:
        from scs_ai.tunnel import TunnelStatus

        return TunnelStatus(state="stopped", enabled=False, pid=None, returncode=None)


def _settings() -> ScsAiSettings:
    return ScsAiSettings.from_env()


def _build(**kwargs):
    return build_scs_ai_app(
        _settings(),
        gateway=kwargs.pop("gateway", ModelGateway(alias=None)),
        tunnel=kwargs.pop("tunnel", _FakeTunnel()),
        tools=kwargs.pop("tools", ToolRegistry.default()),
        **kwargs,
    )


class FakeChatClient(OpenAiCompatibleChatClient):
    def __init__(self, *, reply: str | None = "answer", error: Exception | None = None):
        self.reply = reply
        self.error = error
        self.calls: list[list[dict[str, str]]] = []

    def generate(self, messages, **kwargs) -> str:
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        return self.reply or ""

    @property
    def model_name(self) -> str:
        return "FakeModel"


class _FakeGateway(ModelGateway):
    def __init__(self, *, client):
        super().__init__(alias="fake")
        self._client_obj = client

    def status(self):
        from scs_ai.model_gateway import GatewayStatus

        return GatewayStatus(
            state="configured", alias="fake", provider="openai_compatible",
            model_name="FakeModel", ready=True,
        )

    def client(self):
        return self._client_obj


class TestCalculations:
    def test_cfm_from_velocity_area(self) -> None:
        result = calculations.calculate(
            "cfm_from_velocity_area", {"velocity_fpm": 500, "area_sqft": 2.0}
        )
        assert result["ok"] is True
        assert result["result"]["cfm"] == 1000.0

    def test_velocity_from_cfm_area(self) -> None:
        result = calculations.calculate(
            "velocity_from_cfm_area", {"cfm": 1000, "area_sqft": 2.5}
        )
        assert result["ok"] is True
        assert result["result"]["velocity_fpm"] == 400.0

    def test_cfm_from_sensible_heat(self) -> None:
        result = calculations.calculate(
            "cfm_from_sensible_heat", {"sensible_btuh": 10800, "delta_t_f": 20}
        )
        assert result["ok"] is True
        assert result["result"]["cfm"] == pytest.approx(500.0)

    def test_traverse_cfm(self) -> None:
        result = calculations.calculate(
            "traverse_cfm", {"readings_fpm": [400, 600, 500], "area_sqft": 2.0}
        )
        assert result["ok"] is True
        assert result["result"]["average_velocity_fpm"] == 500.0
        assert result["result"]["cfm"] == 1000.0

    def test_total_static_pressure(self) -> None:
        result = calculations.calculate(
            "total_static_pressure", {"drops_inwc": [0.1, 0.2, 0.05]}
        )
        assert result["ok"] is True
        assert result["result"]["total_inwc"] == pytest.approx(0.35)

    def test_pressure_convert(self) -> None:
        result = calculations.calculate("pressure_convert", {"value": 1, "from_unit": "inwc"})
        assert result["ok"] is True
        assert result["result"]["pa"] == pytest.approx(248.84)
        back = calculations.calculate("pressure_convert", {"value": 248.84, "from_unit": "pa"})
        assert back["result"]["inwc"] == pytest.approx(1.0, abs=0.01)

    def test_unknown_calculation_reports_error(self) -> None:
        result = calculations.calculate("nope", {})
        assert result["ok"] is False
        assert result["errors"]

    def test_invalid_inputs_report_error(self) -> None:
        result = calculations.calculate("cfm_from_velocity_area", {"velocity_fpm": -5, "area_sqft": 1})
        assert result["ok"] is False
        assert result["errors"]

    def test_schema_lists_all_calculations(self) -> None:
        names = {item["name"] for item in calculations.schema()}
        assert names == {
            "cfm_from_velocity_area",
            "velocity_from_cfm_area",
            "cfm_from_sensible_heat",
            "traverse_cfm",
            "total_static_pressure",
            "pressure_convert",
        }


class TestScsAiModelConfig:
    def test_empty_config(self) -> None:
        config = ScsAiModelConfig()
        assert config.alias is None
        assert config.providers() == {}
        assert config.requires_api_key is False

    def test_loopback_http_allowed(self) -> None:
        config = ScsAiModelConfig(
            alias="scs-language",
            model_name="Qwen/Qwen3-30B-A3B-Instruct-2507",
            base_url="http://127.0.0.1:8301/v1",
        )
        assert config.providers()["scs-language"].base_url == "http://127.0.0.1:8301/v1"

    def test_remote_http_rejected(self) -> None:
        with pytest.raises(ValueError):
            ScsAiModelConfig(base_url="http://example.com/v1")

    def test_api_key_never_repr(self) -> None:
        config = ScsAiModelConfig(api_key="super-secret", requires_api_key=True)
        assert "super-secret" not in repr(config)
        assert str(config) == repr(config)

    def test_requires_key_without_key_rejected(self) -> None:
        with pytest.raises(ValueError):
            ScsAiModelConfig(alias="a", base_url="http://127.0.0.1:1", requires_api_key=True)

    def test_load_model_config_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in (
            "SCS_AI_MODEL_ALIAS",
            "SCS_AI_MODEL_NAME",
            "SCS_AI_MODEL_BASE_URL",
            "SCS_AI_MODEL_API_KEY",
            "SCS_AI_MODEL_API_KEY_FILE",
        ):
            monkeypatch.delenv(name, raising=False)
        config = load_model_config()
        assert config.alias is None
        assert config.providers() == {}

    def test_load_model_config_key_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
    ) -> None:
        for name in (
            "SCS_AI_MODEL_ALIAS",
            "SCS_AI_MODEL_NAME",
            "SCS_AI_MODEL_BASE_URL",
            "SCS_AI_MODEL_API_KEY",
        ):
            monkeypatch.delenv(name, raising=False)
        key_file = tmp_path / "key.txt"
        key_file.write_text("secret-key\n", encoding="utf-8")
        monkeypatch.setenv("SCS_AI_MODEL_API_KEY_FILE", str(key_file))
        config = load_model_config()
        assert config.requires_api_key is True
        assert "secret-key" not in repr(config)


class TestChatRoutes:
    def test_chat_returns_503_when_model_not_configured(self) -> None:
        app = _build(assistant=ScsAssistant(ModelGateway(alias=None)))
        with TestClient(app) as client:
            response = client.post("/v1/chat", json={"message": "hello"})
            assert response.status_code == 503
            body = response.json()
            assert body["state"] == "not_configured"
            assert body["reply"] is None

    def test_chat_returns_answer_when_model_ready(self) -> None:
        assistant = ScsAssistant(_FakeGateway(client=FakeChatClient(reply="42")))
        app = _build(assistant=assistant)
        with TestClient(app) as client:
            response = client.post(
                "/v1/chat", json={"message": "what is 2+2?", "history": []}
            )
            assert response.status_code == 200
            body = response.json()
            assert body["state"] == "answered"
            assert body["reply"] == "42"
            assert body["model"] == "FakeModel"

    def test_chat_reports_model_error_without_fallback(self) -> None:
        assistant = ScsAssistant(
            _FakeGateway(client=FakeChatClient(error=ModelError("endpoint said no")))
        )
        app = _build(assistant=assistant)
        with TestClient(app) as client:
            response = client.post("/v1/chat", json={"message": "hello"})
            assert response.status_code == 503
            body = response.json()
            assert body["state"] == "model_error"
            assert body["reply"] is None
            assert "endpoint said no" in body["detail"]

    def test_chat_keeps_history_bounded_and_never_exposes_secrets(self) -> None:
        fake = FakeChatClient(reply="ok")
        assistant = ScsAssistant(_FakeGateway(client=fake))
        app = _build(assistant=assistant)
        history = [{"role": "user", "content": f"turn {i}"} for i in range(40)]
        with TestClient(app) as client:
            response = client.post(
                "/v1/chat", json={"message": "final", "history": history}
            )
            assert response.status_code == 200
            sent = fake.calls[0]
            assert len(sent) <= 2 + 12
            assert sent[-1]["content"] == "final"
            assert not any("Bearer" in message.get("content", "") for message in sent)

    def test_chat_rejects_empty_message(self) -> None:
        app = _build(assistant=ScsAssistant(_FakeGateway(client=FakeChatClient())))
        with TestClient(app) as client:
            response = client.post("/v1/chat", json={"message": "  "})
            assert response.status_code == 503
            assert response.json()["state"] == "model_error"


class TestCalculationsRoutes:
    def test_list_and_run(self) -> None:
        app = _build()
        with TestClient(app) as client:
            listing = client.get("/v1/calculations")
            assert listing.status_code == 200
            assert listing.json()["ok"] is True
            names = {item["name"] for item in listing.json()["items"]}
            assert "cfm_from_sensible_heat" in names
            result = client.post(
                "/v1/calculations",
                json={"calculation": "cfm_from_velocity_area", "inputs": {"velocity_fpm": 400, "area_sqft": 1.5}},
            )
            assert result.status_code == 200
            assert result.json()["ok"] is True
            assert result.json()["result"]["cfm"] == 600.0

    def test_invalid_input_reports_errors(self) -> None:
        app = _build()
        with TestClient(app) as client:
            result = client.post(
                "/v1/calculations",
                json={"calculation": "traverse_cfm", "inputs": {"readings_fpm": ["a"], "area_sqft": 1}},
            )
            assert result.status_code == 200
            assert result.json()["ok"] is False
            assert result.json()["errors"]


class TestOfficeRoutes:
    def test_office_not_configured_returns_honest_body(self) -> None:
        app = _build()
        with TestClient(app) as client:
            response = client.post(
                "/v1/office/document/read", json={"path": "x.docx"}
            )
            assert response.status_code == 200
            body = response.json()
            assert body["success"] is False
            assert body["state"] == "not_configured"

    def test_office_read_roundtrip(self, tmp_path: pytest.TempPathFactory) -> None:
        import docx

        workspace = tmp_path / "office"
        toolkit = OfficeToolkit(workspace)
        doc_path = workspace / "jobs" / "job-1" / "report.docx"
        doc_path.parent.mkdir(parents=True)
        document = docx.Document()
        document.add_paragraph("Fan readings complete")
        document.save(doc_path)
        app = _build(office_toolkit=toolkit)
        with TestClient(app) as client:
            response = client.post(
                "/v1/office/document/read", json={"path": "jobs/job-1/report.docx"}
            )
            assert response.status_code == 200
            body = response.json()
            assert body["success"] is True
            assert "Fan readings complete" in body["data"]["text"]

    def test_office_rejects_path_traversal(self, tmp_path: pytest.TempPathFactory) -> None:
        import docx

        workspace = tmp_path / "office"
        toolkit = OfficeToolkit(workspace)
        app = _build(office_toolkit=toolkit)
        with TestClient(app) as client:
            response = client.post(
                "/v1/office/document/read", json={"path": "../outside.docx"}
            )
            assert response.status_code == 200
            assert response.json()["success"] is False


class TestSystemStatus:
    def test_status_reports_chat_calculations_office_states(self) -> None:
        app = _build(assistant=ScsAssistant(_FakeGateway(client=FakeChatClient())))
        with TestClient(app) as client:
            body = client.get("/v1/system/status").json()
            assert body["chat"] == {"available": True, "state": "configured"}
            assert body["calculations"] == {"enabled": True}
            assert body["office"] == {"state": "not_configured"}

    def test_cors_headers_for_scs_web_origin(self) -> None:
        app = _build()
        with TestClient(app) as client:
            response = client.options(
                "/v1/calculations",
                headers={
                    "Origin": "http://127.0.0.1:3100",
                    "Access-Control-Request-Method": "POST",
                },
            )
            assert response.status_code == 200
            assert "http://127.0.0.1:3100" in response.headers.get("access-control-allow-origin", "")