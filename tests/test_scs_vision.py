"""Local vision provider tests: fail-open honesty, gating, reconciliation.

Never touches a real model server. Ollama timeouts are shortened so a
non-running server fails fast and degrades to UNKNOWN / no facts.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import json as _json

from scs_reports.schema import PhotoClassification
from scs_reports.vision import (
    CombinedProvider,
    LocalVisionStub,
    ModelRouter,
    OllamaVisionProvider,
    PaddleOcrProvider,
    build_vision_router,
    vision_provider_status,
)

SAMPLE = Path(r"C:\SCS_DATA\vision-benchmark\images\carrier_nameplate.png")


def test_stub_is_honest():
    stub = LocalVisionStub()
    assert stub.classify(SAMPLE) == (PhotoClassification.UNKNOWN, None)
    assert stub.extract_nameplate(SAMPLE) == []
    assert stub.extract_display(SAMPLE) == []
    router = ModelRouter()
    assert not router.vision_capable
    assert router.candidate_nameplate_facts(SAMPLE) == []


def test_unconfigured_router_status():
    status = vision_provider_status(ModelRouter())
    assert status["status"] == "NOT_CONFIGURED"
    assert status["provider"] is None


@pytest.mark.parametrize(
    "value,expected",
    [
        ("LOCAL_QWEN_VL", "LOCAL_QWEN_VL"),
        ("LOCAL_MINICPM_V", "LOCAL_MINICPM_V"),
        ("LOCAL_PADDLE_OCR", "LOCAL_PADDLE_OCR"),
        ("LOCAL_QWEN_PLUS_OCR", "LOCAL_QWEN_PLUS_OCR"),
        ("LOCAL_MINICPM_PLUS_OCR", "LOCAL_MINICPM_PLUS_OCR"),
        ("", None),
        ("BOGUS", None),
    ],
)
def test_build_vision_router_env_mapping(monkeypatch, value, expected):
    monkeypatch.setenv("SCS_VISION_PROVIDER", value)
    router = build_vision_router()
    assert router.vision_capable is (expected is not None)
    if expected is not None:
        status = vision_provider_status(router)
        assert status["status"] == "LOCAL"
        assert status["provider"] == expected


def test_ollama_provider_fails_open_when_server_down():
    provider = OllamaVisionProvider(
        "qwen2.5vl:3b", endpoint="http://127.0.0.1:1", timeout=0.5
    )
    classification, confidence = provider.classify(SAMPLE)
    assert classification == PhotoClassification.UNKNOWN
    assert confidence is None
    assert provider.extract_nameplate(SAMPLE) == []
    assert provider.extract_display(SAMPLE) == []


def test_ollama_provider_gates_low_confidence_facts():
    provider = OllamaVisionProvider("qwen2.5vl:3b", min_confidence=0.6)

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "response": (
                    '{"classification": "NAMEPLATE", "confidence": 0.9, '
                    '"manufacturer": "Carrier", "model": "48TC-11A", '
                    '"confidence_model": 0.4, "serial": null}'
                )
            }

    provider._generate = lambda path, prompt: _json.loads(FakeResponse().json()["response"])
    classification, confidence = provider.classify(SAMPLE)
    assert classification == PhotoClassification.NAMEPLATE
    assert confidence == pytest.approx(0.9)
    facts = provider.extract_nameplate(SAMPLE)
    fields = {fact["field"] for fact in facts}
    assert "manufacturer" in fields
    assert "model" not in fields  # gated below 0.6
    assert "serial" not in fields  # null never becomes a fact


def test_ollama_provider_rejects_degenerate_output():
    provider = OllamaVisionProvider("qwen2.5vl:3b")
    assert provider._is_degenerate("@@@@@@@@@@@@@@@@@@@@@@@@")
    assert provider._is_degenerate("aaaaaaaa")
    assert provider._is_degenerate("")
    assert not provider._is_degenerate('{"classification": "NAMEPLATE", "confidence": 0.9}')

    class Degenerate:
        status_code = 200

        def json(self):
            return {"response": "@@@@@@@@@@@@@@@@@@@@@@@@@@@", "done": True}

    provider._generate = lambda path, prompt: Degenerate().json()
    classification, confidence = provider.classify(SAMPLE)
    assert classification == PhotoClassification.UNKNOWN
    assert confidence is None


def test_ollama_provider_rejects_unknown_labels_and_bad_json():
    provider = OllamaVisionProvider("qwen2.5vl:3b")

    class Bad:
        status_code = 200

        def json(self):
            return {"response": '{"classification": "TRICORDER", "confidence": 0.99}'}

    provider._generate = lambda path, prompt: Bad().json()
    classification, _ = provider.classify(SAMPLE)
    assert classification == PhotoClassification.UNKNOWN

    class NotJson:
        status_code = 200

        def json(self):
            return {"response": "definitely not json"}

    provider._generate = lambda path, prompt: NotJson().json()
    classification, confidence = provider.classify(SAMPLE)
    assert classification == PhotoClassification.UNKNOWN
    assert confidence is None


def test_ocr_provider_reads_text_and_never_fabricates(tmp_path):
    provider = PaddleOcrProvider()
    facts = provider.extract_nameplate(SAMPLE)
    assert facts
    assert all(fact["field"] == "ocr_text" for fact in facts)
    assert all(0.0 <= fact["confidence"] <= 1.0 for fact in facts)
    blank = tmp_path / "blank.png"
    from PIL import Image

    Image.new("RGB", (320, 240), "white").save(blank)
    assert provider.extract_display(blank) == []


class FakeVlm:
    def __init__(self, facts, confidence=0.8):
        self._facts = facts
        self._confidence = confidence

    def classify(self, path):
        return PhotoClassification.NAMEPLATE, 0.9

    def extract_nameplate(self, path):
        return list(self._facts)

    def extract_display(self, path):
        return []


class FakeOcr:
    def __init__(self, texts):
        self._texts = texts

    def _lines(self, path):
        return [(text, 0.9) for text in self._texts]


def test_combined_provider_corroboration_and_penalty():
    corroborated = [
        {"field": "serial", "value": "2612C41501", "unit": None, "confidence": 0.85}
    ]
    uncorroborated = [
        {"field": "model", "value": "GHOST-X99", "unit": None, "confidence": 0.85}
    ]
    provider = CombinedProvider(
        FakeVlm(corroborated + uncorroborated), FakeOcr(["SERIAL 2612C41501"])
    )
    facts = provider.extract_nameplate(SAMPLE)
    by_field = {fact["field"]: fact for fact in facts}
    assert by_field["serial"]["confidence"] == pytest.approx(0.85)  # corroborated, uncapped
    assert by_field["model"]["confidence"] == pytest.approx(0.425)  # halved, uncorroborated
    assert by_field["model"].get("needs_confirmation") is True
    assert by_field["serial"].get("needs_confirmation") is None


def test_combined_provider_flags_sub_gate_facts_for_review():
    provider = CombinedProvider(
        FakeVlm([{"field": "model", "value": "X", "unit": None, "confidence": 0.4}]),
        FakeOcr(["X"]),
        min_confidence=0.6,
    )
    facts = provider.extract_nameplate(SAMPLE)
    assert facts == [
        {"field": "model", "value": "X", "unit": None, "confidence": 0.4, "needs_confirmation": True}
    ]