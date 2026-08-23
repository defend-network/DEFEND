"""Legend / symbol dictionary (M1.2, P16/P17).

A PlanSymbolDictionary is generated per PlanPacket from the project legend.
Project legend wins over generic assumptions; when the legend is absent, symbol
identity is GENERIC_SYMBOL_INFERENCE (tentative), never VERIFIED.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from . import plans

LEGEND_SEMANTICS: dict[str, str] = {
    "FSD": "COMBINATION_FIRE_SMOKE_DAMPER",
    "FD": "FIRE_DAMPER",
    "SD": "SMOKE_DAMPER",
    "SMD": "SMOKE_DAMPER",
    "VD": "VOLUME_DAMPER",
    "BD": "BALANCING_DAMPER",
    "MD": "MOTORIZED_DAMPER",
    "MOTORIZED": "MOTORIZED_DAMPER",
    "BACKDRAFT": "BACKDRAFT_DAMPER",
    "BAROMETRIC": "BAROMETRIC_RELIEF_DAMPER",
    "T": "THERMOSTAT",
    "THERMOSTAT": "THERMOSTAT",
    "DSD": "DUCT_SMOKE_DETECTOR",
    "SP": "STATIC_PRESSURE_SENSOR",
    "CO2": "CO2_SENSOR",
    "TEMP": "SPACE_TEMP_SENSOR",
    "RH": "HUMIDITY_SENSOR",
    "AD": "ACCESS_DOOR",
    "ACCESS": "ACCESS_DOOR",
    "VFD": "VFD",
    "DD": "SUPPLY_DIFFUSER",
    "SD-": "SUPPLY_DIFFUSER",
    "RG": "RETURN_GRILLE",
    "EG": "EXHAUST_GRILLE",
    "TRANSFER": "TRANSFER_GRILLE",
    "LVR": "LOUVER",
}


@dataclass
class SymbolEntry:
    literal_label: str
    normalized_semantic: str | None
    description: str
    source_legend_sheet: str | None
    source_bbox: tuple[float, float, float, float] | None = None
    confidence: str = "PROJECT_LEGEND_VERIFIED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "literal_label": self.literal_label,
            "normalized_semantic": self.normalized_semantic,
            "description": self.description,
            "source_legend_sheet": self.source_legend_sheet,
            "source_bbox": list(self.source_bbox) if self.source_bbox else None,
            "confidence": self.confidence,
        }


@dataclass
class PlanSymbolDictionary:
    entries: dict[str, SymbolEntry] = field(default_factory=dict)
    legend_sheet: str | None = None
    supplied: bool = False

    def lookup(self, label: str) -> SymbolEntry | None:
        key = label.strip().upper().split("-")[0] if "-" in label else label.strip().upper()
        if key in self.entries:
            return self.entries[key]
        return self.entries.get(label.strip().upper())

    def semantic_of(self, label: str, *, generic_ok: bool = True) -> str | None:
        entry = self.lookup(label)
        if entry and entry.normalized_semantic:
            return entry.normalized_semantic
        if generic_ok and self.supplied:
            base = label.strip().upper().split("-")[0]
            return LEGEND_SEMANTICS.get(base)
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "legend_sheet": self.legend_sheet,
            "supplied": self.supplied,
            "entries": {k: v.to_dict() for k, v in self.entries.items()},
        }


def extract_legend(page: plans.PlanPage) -> PlanSymbolDictionary:
    """Parse a legend page: SYMBOL | DESCRIPTION pairs into the dictionary."""
    dictionary = PlanSymbolDictionary(legend_sheet=page.sheet_number, supplied=True)
    records = plans._schedule_from_words(page.words)
    for record in records:
        label = (record.get("tag") or "").strip().upper()
        description = record.get("type") or record.get("description") or ""
        if not label or not description:
            continue
        semantic = _semantic_from_text(label, description)
        dictionary.entries[label] = SymbolEntry(
            literal_label=label,
            normalized_semantic=semantic,
            description=description,
            source_legend_sheet=page.sheet_number,
            confidence="PROJECT_LEGEND_VERIFIED",
        )
    return dictionary


def _semantic_from_text(label: str, description: str) -> str | None:
    combined = (label + " " + description).upper()
    for token, semantic in LEGEND_SEMANTICS.items():
        if re.search(r"(^|\W)" + re.escape(token) + r"(\W|$)", combined):
            return semantic
    base = label.split("-")[0]
    return LEGEND_SEMANTICS.get(base)


def generic_symbol_inference(label: str, description: str = "") -> dict[str, Any]:
    """P17: tentative identity when no project legend was supplied."""
    semantic = _semantic_from_text(label, description)
    return {
        "literal_label": label.upper(),
        "normalized_semantic": semantic,
        "confidence": "GENERIC_SYMBOL_INFERENCE" if semantic else None,
        "legend_context": "LEGEND_CONTEXT_MISSING",
    }
