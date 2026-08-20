"""Vision provider interface.

The report pipeline never changes when the provider changes. Today the local
providers are HONEST stubs: they classify nothing and extract nothing, so no
unreliable OCR can block report generation. Swap in a real provider behind
the same interface (P1/P2).
"""
from __future__ import annotations

import base64
import json
import os
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import requests

from .schema import PhotoClassification, ReviewStatus

CLASSIFICATION_LABELS = {
    "NAMEPLATE",
    "INSTRUMENT_READING",
    "AIRFLOW_READING",
    "PRESSURE_READING",
    "TEMP_RH_READING",
    "EQUIPMENT",
    "DUCTWORK",
    "UNKNOWN",
}

_MIN_CONFIDENCE = float(os.environ.get("SCS_VISION_MIN_CONFIDENCE", "0.6"))
_OLLAMA_ENDPOINT = os.environ.get("SCS_OLLAMA_ENDPOINT", "http://127.0.0.1:11434")


class PhotoClassifier(ABC):
    @abstractmethod
    def classify(self, path: Path) -> tuple[PhotoClassification, float | None]:
        """Return (classification, confidence)."""


class FactExtractor(ABC):
    @abstractmethod
    def extract_nameplate(self, path: Path) -> list[dict[str, Any]]:
        """Candidate nameplate facts: [{field, value, unit, confidence}...]."""

    @abstractmethod
    def extract_display(self, path: Path) -> list[dict[str, Any]]:
        """Candidate instrument-display facts: [{field, value, unit, confidence}...]."""


class LocalVisionStub(PhotoClassifier, FactExtractor):
    """No-op provider: classification UNKNOWN, no extraction. Honest by design."""

    def classify(self, path: Path) -> tuple[PhotoClassification, float | None]:
        return PhotoClassification.UNKNOWN, None

    def extract_nameplate(self, path: Path) -> list[dict[str, Any]]:
        return []

    def extract_display(self, path: Path) -> list[dict[str, Any]]:
        return []


class RemoteVisionUnconfigured(PhotoClassifier, FactExtractor):
    def __init__(self, provider_name: str) -> None:
        self._provider_name = provider_name

    def classify(self, path: Path) -> tuple[PhotoClassification, float | None]:
        raise NotImplementedError(
            f"remote vision provider {self._provider_name!r} is not configured"
        )

    def extract_nameplate(self, path: Path) -> list[dict[str, Any]]:
        raise NotImplementedError(
            f"remote vision provider {self._provider_name!r} is not configured"
        )

    def extract_display(self, path: Path) -> list[dict[str, Any]]:
        raise NotImplementedError(
            f"remote vision provider {self._provider_name!r} is not configured"
        )


class OllamaVisionProvider(PhotoClassifier, FactExtractor):
    """Local VLM through Ollama's /api/generate (images as base64).

    Model name selects the actual weights (e.g. qwen2.5vl:3b, minicpm-v).
    Every failure degrades to honest abstention: UNKNOWN / no facts. No value
    is ever invented: facts below the confidence gate are dropped, and the
    review screen marks anything PHOTO_EXTRACTED as NEEDS_CONFIRMATION.
    """

    def __init__(
        self,
        model: str,
        *,
endpoint: str = _OLLAMA_ENDPOINT,
        min_confidence: float = _MIN_CONFIDENCE,
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self._endpoint = endpoint.rstrip("/")
        self._min_confidence = min_confidence
        self._timeout = timeout

    def _generate(self, image_path: Path, prompt: str) -> dict[str, Any] | None:
        try:
            encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
            payload = {
                "model": self.model,
                "prompt": prompt,
                "images": [encoded],
                "format": "json",
                "stream": False,
                "keep_alive": "10m",
            }
            response = requests.post(
                f"{self._endpoint}/api/generate",
                json=payload,
                timeout=self._timeout,
            )
            if response.status_code != 200:
                return None
            text = response.json().get("response", "")
            if self._is_degenerate(text):
                return None
            return json.loads(text)
        except Exception:
            return None

    @staticmethod
    def _is_degenerate(text: str) -> bool:
        """Small VLMs occasionally emit repeated-garbage tokens (e.g. '@@@@')
        instead of JSON. Treat as a failed generation, never a fact source."""
        stripped = text.strip()
        if not stripped:
            return True
        if len(stripped) >= 8 and len(set(stripped)) <= 2:
            return True
        if len(stripped) >= 64 and len(set(stripped)) <= 4:
            return True
        return False

    @staticmethod
    def _clamp(value: Any, default: float | None = None) -> float | None:
        if value is None:
            return default
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        return max(0.0, min(1.0, number))

    def classify(self, path: Path) -> tuple[PhotoClassification, float | None]:
        prompt = (
            "You are an HVAC TAB field-tool photo classifier. "
            "Return ONLY JSON: {\"classification\": <one of NAMEPLATE, "
            "INSTRUMENT_READING, AIRFLOW_READING, PRESSURE_READING, "
            "TEMP_RH_READING, EQUIPMENT, DUCTWORK, UNKNOWN>, "
            "\"confidence\": <0..1>}. If the image is unclear, use UNKNOWN "
            "with a low confidence."
        )
        payload = self._generate(path, prompt)
        if not payload:
            return PhotoClassification.UNKNOWN, None
        label = str(payload.get("classification", "UNKNOWN")).upper()
        if label not in CLASSIFICATION_LABELS:
            return PhotoClassification.UNKNOWN, None
        confidence = self._clamp(payload.get("confidence"))
        if confidence is not None and confidence < self._min_confidence:
            return PhotoClassification.UNKNOWN, confidence
        return PhotoClassification(label), confidence

    def _facts(self, payload: dict[str, Any] | None, fields: list[str]) -> list[dict[str, Any]]:
        if not payload:
            return []
        facts: list[dict[str, Any]] = []
        overall = self._clamp(payload.get("confidence"))
        for field in fields:
            value = payload.get(field)
            if value is None or str(value).strip() == "":
                continue
            confidence = self._clamp(payload.get(f"confidence_{field}"), overall)
            if confidence is None or confidence < self._min_confidence:
                continue
            facts.append(
                {
                    "field": field,
                    "value": str(value).strip(),
                    "unit": payload.get("unit"),
                    "confidence": confidence,
                }
            )
        return facts

    def _generate_structured(self, image_path: Path, prompt: str, fields: list[str]) -> dict[str, Any] | None:
        """Generate + retry once when the small model ignores format:json."""
        payload = self._generate(image_path, prompt)
        if payload and any(payload.get(field) is not None for field in fields):
            return payload
        if payload and "readings" in payload:
            return payload
        return self._generate(image_path, prompt)

    def extract_nameplate(self, path: Path) -> list[dict[str, Any]]:
        prompt = (
            "You are an HVAC TAB field-tool. Read the equipment nameplate in "
            "this photo. Return ONLY JSON: {\"manufacturer\": <string|null>, "
            "\"model\": <string|null>, \"serial\": <string|null>, "
            "\"equipment_type\": <RTU|AHU|VAV|FCU|FAN|VFD|OTHER|null>, "
            "\"confidence\": <0..1>, \"confidence_model\": <0..1>, "
            "\"confidence_serial\": <0..1>}. If the photo is not a readable "
            "nameplate, return nulls with a low confidence. Never guess."
        )
        payload = self._generate_structured(path, prompt, ["manufacturer", "model", "serial", "equipment_type"])
        facts = self._facts(payload, ["manufacturer", "model", "serial", "equipment_type"])
        return facts

    def extract_display(self, path: Path) -> list[dict[str, Any]]:
        prompt = (
            "You are an HVAC TAB field-tool. Read the instrument display in "
            "this photo. Return ONLY JSON: {\"readings\": [{\"value\": "
            "<exact digits or signed decimal>, \"unit\": <string>, "
            "\"confidence\": <0..1>}], \"confidence\": <0..1>}. Transcribe "
            "exactly what the display shows. If unreadable, return an empty "
            "readings array with low confidence. Never guess values."
        )
        payload = self._generate_structured(path, prompt, ["readings"])
        if not payload:
            return []
        readings = payload.get("readings")
        if not isinstance(readings, list):
            return []
        facts: list[dict[str, Any]] = []
        overall = self._clamp(payload.get("confidence"))
        for index, reading in enumerate(readings):
            if not isinstance(reading, dict):
                continue
            value = reading.get("value")
            if value is None or str(value).strip() == "":
                continue
            confidence = self._clamp(reading.get("confidence"), overall)
            if confidence is None or confidence < self._min_confidence:
                continue
            facts.append(
                {
                    "field": f"reading_{index + 1}",
                    "value": str(value).strip(),
                    "unit": reading.get("unit"),
                    "confidence": confidence,
                }
            )
        return facts


class PaddleOcrProvider(FactExtractor):
    """PaddleOCR-equivalent exact-text pass via RapidOCR (ONNX Runtime).

    paddlepaddle has no wheels for this Python (3.14); RapidOCR runs the same
    PP-OCRv5 detection+recognition models on ONNX locally. No classification:
    OCR reads text, it never infers what the photo IS.
    """

    def __init__(self) -> None:
        from rapidocr_onnxruntime import RapidOCR

        self._ocr = RapidOCR()

    def _lines(self, path: Path) -> list[tuple[str, float]]:
        try:
            result, _ = self._ocr(str(path))
        except Exception:
            return []
        if not result:
            return []
        return [(str(text), float(score)) for box, text, score in result]

    def _facts_from_lines(self, lines: list[tuple[str, float]]) -> list[dict[str, Any]]:
        facts: list[dict[str, Any]] = []
        for text, score in lines:
            stripped = text.strip()
            if not stripped:
                continue
            facts.append({"field": "ocr_text", "value": stripped, "unit": None, "confidence": score})
        return facts

    def extract_nameplate(self, path: Path) -> list[dict[str, Any]]:
        return self._facts_from_lines(self._lines(path))

    def extract_display(self, path: Path) -> list[dict[str, Any]]:
        return self._facts_from_lines(self._lines(path))


class CombinedProvider(PhotoClassifier, FactExtractor):
    """VLM + OCR reconciliation.

    A VLM fact is corroborated when the OCR text contains its value (normalized
    digits). Corroborated facts keep VLM confidence (capped 0.9); uncorroborated
    facts are cut in half, so they surface as NEEDS_CONFIRMATION in review.
    """

    def __init__(
        self,
        vlm: OllamaVisionProvider,
        ocr: PaddleOcrProvider,
        *,
        min_confidence: float = _MIN_CONFIDENCE,
    ) -> None:
        self._vlm = vlm
        self._ocr = ocr
        self._min_confidence = min_confidence

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"[^A-Z0-9.-]", "", value.upper())

    def _corroboration(self, path: Path) -> set[str]:
        return {self._normalize(text) for text, _ in self._ocr._lines(path)}

    def _is_corroborated(self, value: str, seen: set[str]) -> bool:
        normalized = self._normalize(value)
        if normalized in seen:
            return True
        return any(normalized and normalized in line for line in seen)

    def classify(self, path: Path) -> tuple[PhotoClassification, float | None]:
        return self._vlm.classify(path)

    def _reconcile(self, facts: list[dict[str, Any]], seen: set[str]) -> list[dict[str, Any]]:
        reconciled: list[dict[str, Any]] = []
        for fact in facts:
            if self._is_corroborated(str(fact["value"]), seen):
                confidence = min(float(fact.get("confidence") or 0.0), 0.9)
            else:
                confidence = (float(fact.get("confidence") or 0.0)) * 0.5
            entry = {**fact, "confidence": confidence}
            if confidence < self._min_confidence:
                entry["needs_confirmation"] = True
            reconciled.append(entry)
        return reconciled

    def extract_nameplate(self, path: Path) -> list[dict[str, Any]]:
        seen = self._corroboration(path)
        return self._reconcile(self._vlm.extract_nameplate(path), seen)

    def extract_display(self, path: Path) -> list[dict[str, Any]]:
        seen = self._corroboration(path)
        return self._reconcile(self._vlm.extract_display(path), seen)
class ModelRouter:
    """Routes work by capability: LOCAL_TEXT / LOCAL_VISION / REMOTE_VISION /
    REMOTE_REASONING. Pipeline code talks to this interface only."""

    def __init__(
        self,
        classifier: PhotoClassifier | None = None,
        extractor: FactExtractor | None = None,
    ) -> None:
        self._classifier = classifier or LocalVisionStub()
        self._extractor = extractor or LocalVisionStub()

    @property
    def vision_capable(self) -> bool:
        return not isinstance(self._classifier, LocalVisionStub) or not isinstance(
            self._extractor, LocalVisionStub
        )

    def classify_photo(self, path: Path) -> tuple[PhotoClassification, float | None]:
        classification, confidence = self._classifier.classify(path)
        return classification, confidence

    def candidate_nameplate_facts(self, path: Path) -> list[dict[str, Any]]:
        return self._extractor.extract_nameplate(path)

    def candidate_display_facts(self, path: Path) -> list[dict[str, Any]]:
        return self._extractor.extract_display(path)


def build_vision_router() -> ModelRouter:
    """Pick the provider stack from SCS_VISION_PROVIDER (empty = NOT_CONFIGURED).

    LOCAL_QWEN_VL            -> Qwen2.5-VL-3B via Ollama
    LOCAL_MINICPM_V          -> MiniCPM-V via Ollama
    LOCAL_PADDLE_OCR         -> RapidOCR only (PaddleOCR-equivalent, ONNX)
    LOCAL_QWEN_PLUS_OCR      -> Qwen2.5-VL + OCR reconciliation
    LOCAL_MINICPM_PLUS_OCR   -> MiniCPM-V + OCR reconciliation
    """
    provider = os.environ.get("SCS_VISION_PROVIDER", "").strip().upper()
    if not provider:
        return ModelRouter()
    if provider == "LOCAL_PADDLE_OCR":
        return ModelRouter(extractor=PaddleOcrProvider())
    if provider == "LOCAL_QWEN_VL":
        provider_obj = OllamaVisionProvider("qwen2.5vl:3b")
        return ModelRouter(provider_obj, provider_obj)
    if provider == "LOCAL_MINICPM_V":
        provider_obj = OllamaVisionProvider("minicpm-v")
        return ModelRouter(provider_obj, provider_obj)
    if provider == "LOCAL_QWEN_PLUS_OCR":
        provider_obj = CombinedProvider(OllamaVisionProvider("qwen2.5vl:3b"), PaddleOcrProvider())
        return ModelRouter(provider_obj, provider_obj)
    if provider == "LOCAL_MINICPM_PLUS_OCR":
        provider_obj = CombinedProvider(OllamaVisionProvider("minicpm-v"), PaddleOcrProvider())
        return ModelRouter(provider_obj, provider_obj)
    return ModelRouter()


def vision_provider_status(router: ModelRouter) -> dict[str, Any]:
    if not router.vision_capable:
        return {
            "status": "NOT_CONFIGURED",
            "provider": None,
            "note": (
                "No vision provider is configured. All evidence is "
                "technician-entered/confirmed. The review screen supports "
                "PHOTO_EXTRACTED candidates with NEEDS_CONFIRMATION when a "
                "provider is added."
            ),
        }
    provider_name = os.environ.get("SCS_VISION_PROVIDER", "").strip().upper()
    return {
        "status": "LOCAL",
        "provider": provider_name,
        "note": (
            f"Local-only {provider_name}. Photos never leave this machine. "
            "Extracted candidates appear in review as NEEDS_CONFIRMATION; "
            "nothing is written to the report without technician confirmation."
        ),
    }
