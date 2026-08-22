"""Manufacturer model nomenclature decoders (M1.3, P34-P35).

Pluggable ManufacturerDecoder interface. Decoders are added gradually and only
when supported by authoritative manufacturer nomenclature - never speculative
regexes from web folklore. A decoder returns decoded field, value, source
citation, confidence, and the raw characters used. Partial models resolve
family-level information only (FAMILY_LEVEL_REFERENCE); exact-configuration
claims require the exact suffix (EXACT_MODEL_REFERENCE).
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any


class ManufacturerDecoder(ABC):
    manufacturer: str

    @abstractmethod
    def decode(self, model: str) -> dict[str, Any]:
        """Return {family, decoded[], resolution, confidence}."""


class CarrierDecoder(ManufacturerDecoder):
    """Carrier nomenclature - family-level only in V1.

    50TC = WeatherExpert commercial rooftop unit (well-documented family).
    The capacity/configuration suffix requires the exact full model string and
    authoritative nomenclature; V1 resolves only the family and marks the
    configuration EXACT_MODEL_UNRESOLVED.
    """
    manufacturer = "CARRIER"

    _FAMILIES = [
        (r"^50TC", "WeatherExpert commercial rooftop unit"),
        (r"^48TC", "48TC commercial rooftop unit"),
        (r"^50FC", "50FC WeatherExpert rooftop (dedicated)"),
        (r"^48FC", "48FC rooftop"),
        (r"^50LC", "50LC rooftop"),
        (r"^40RM", "40RM vertical indoor air handler"),
        (r"^39M", "39M central station air handler"),
    ]

    def decode(self, model: str) -> dict[str, Any]:
        upper = model.strip().upper()
        family = None
        for pattern, label in self._FAMILIES:
            if re.match(pattern, upper):
                family = label
                break
        if family is None:
            return {"manufacturer": "CARRIER", "family": None,
                    "decoded": [], "resolution": "UNKNOWN_MODEL_NOMENCLATURE",
                    "confidence": "LOW",
                    "source": "Carrier product family nomenclature (family level)"}
        decoded = [{"field": "family", "value": family,
                    "source": "Carrier product nomenclature (family level)",
                    "confidence": "HIGH",
                    "raw_chars_used": re.match(r"[A-Z0-9]+", upper).group(0)}]
        return {
            "manufacturer": "CARRIER", "family": family, "decoded": decoded,
            "resolution": "FAMILY_LEVEL_REFERENCE",
            "confidence": "HIGH",
            "source": "Carrier product nomenclature (family level)",
            "note": "capacity/heat/config require the exact full model string; not fabricated",
        }


class GreenheckDecoder(ManufacturerDecoder):
    """Greenheck fan nomenclature - family level only in V1."""
    manufacturer = "GREENHECK"

    _FAMILIES = [
        (r"^SQ", "Cubed inline centrifugal fan (SQ series)"),
        (r"^G", "G series utility fans"),
        (r"^B", "Belt drive / other family"),
    ]

    def decode(self, model: str) -> dict[str, Any]:
        upper = model.strip().upper()
        for pattern, label in self._FAMILIES:
            if re.match(pattern, upper):
                return {"manufacturer": "GREENHECK", "family": label,
                        "decoded": [{"field": "family", "value": label,
                                     "source": "Greenheck product naming (family level)",
                                     "confidence": "HIGH",
                                     "raw_chars_used": re.match(r"[A-Z0-9]+", upper).group(0)}],
                        "resolution": "FAMILY_LEVEL_REFERENCE", "confidence": "HIGH",
                        "source": "Greenheck product naming (family level)"}
        return {"manufacturer": "GREENHECK", "family": None, "decoded": [],
                "resolution": "UNKNOWN_MODEL_NOMENCLATURE", "confidence": "LOW"}


class TitusDecoder(ManufacturerDecoder):
    """Titus VAV / terminal nomenclature - family level only in V1."""
    manufacturer = "TITUS"

    _FAMILIES = [
        (r"^ESV", "ESV single-duct VAV terminal"),
        (r"^TMS", "TMS single-duct VAV terminal"),
        (r"^TSS", "TSS fan-powered terminal"),
    ]

    def decode(self, model: str) -> dict[str, Any]:
        upper = model.strip().upper()
        for pattern, label in self._FAMILIES:
            if re.match(pattern, upper):
                return {"manufacturer": "TITUS", "family": label,
                        "decoded": [{"field": "family", "value": label,
                                     "source": "Titus terminal nomenclature (family level)",
                                     "confidence": "HIGH",
                                     "raw_chars_used": re.match(r"[A-Z0-9]+", upper).group(0)}],
                        "resolution": "FAMILY_LEVEL_REFERENCE", "confidence": "HIGH",
                        "source": "Titus terminal nomenclature (family level)"}
        return {"manufacturer": "TITUS", "family": None, "decoded": [],
                "resolution": "UNKNOWN_MODEL_NOMENCLATURE", "confidence": "LOW"}


DECODERS: dict[str, ManufacturerDecoder] = {
    d.manufacturer: d() for d in (CarrierDecoder, GreenheckDecoder, TitusDecoder)
}
