"""Exhaustive schedule ingestion (M1.2).

Preserves the ENTIRE schedule - every column, every row, unknown columns
included - rather than cherry-picking TAG/CFM/SIZE. Controlled semantic
normalization maps literal headings to canonical fields while preserving the
literal source heading and raw cell text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from . import plans

# canonical field -> aliases (longest match wins; merged OCR tokens handled)
SCHEDULE_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "TAG": ("tag", "mark", "no.", "no", "device tag", "equip no", "symbol"),
    "SERVICE": ("service", "service/room", "serves", "served by", "area"),
    "LOCATION": ("location", "loc", "room", "space", "area served"),
    "MANUFACTURER": ("manufacturer", "mfr", "mfgr", "make"),
    "MODEL": ("model", "model no", "model number"),
    "TYPE": ("type", "description", "unit type", "device type"),
    "QUANTITY": ("qty", "quantity", "number", "count"),
    "SUPPLY_CFM": ("supply cfm", "supply air cfm", "supply air", "supply"),
    "RETURN_CFM": ("return cfm", "return air cfm", "return air"),
    "OUTSIDE_AIR_CFM": ("outside air cfm", "oa cfm", "outside air", "oa"),
    "EXHAUST_CFM": ("exhaust cfm", "exhaust air cfm", "relief cfm", "exhaust"),
    "TOTAL_CFM": ("total cfm", "total airflow", "total air", "total"),
    "MIN_CFM": ("min cfm", "minimum cfm", "min", "minimum"),
    "MAX_CFM": ("max cfm", "maximum cfm", "max", "maximum"),
    "DESIGN_CFM": ("design cfm", "cfm", "airflow", "air flow", "air quantity",
                   "capacity cfm", "design airflow"),
    "ESP": ("esp", "external static", "external static press", "available esp",
            "ext static"),
    "TSP": ("tsp", "total static", "total static press"),
    "STATIC_PRESSURE": ("static pressure", "static press", "static"),
    "FAN_RPM": ("fan rpm", "rpm fan", "fan speed rpm"),
    "MOTOR_RPM": ("motor rpm", "rpm motor"),
    "RPM": ("rpm", "speed"),
    "BHP": ("bhp", "brake hp", "brake horsepower"),
    "MOTOR_HP": ("motor hp", "motor horsepower", "hp motor"),
    "HP": ("hp", "horsepower"),
    "FAN_TYPE": ("fan type", "blower type"),
    "FAN_SPEED": ("fan speed", "speed setting"),
    "DRIVE_TYPE": ("drive type", "drive", "belt drive", "direct drive"),
    "VFD": ("vfd", "variable freq drive", "variable frequency drive"),
    "VOLTS": ("volts", "voltage", "volt", "v"),
    "PHASE": ("phase", "ph"),
    "HZ": ("hz", "frequency", "hertz"),
    "MCA": ("mca",),
    "MOCP": ("mocp", "max ocpd", "max overcurrent"),
    "FLA": ("fla", "full load amps"),
    "EER": ("eer",),
    "SEER": ("seer",),
    "COP": ("cop",),
    "COOLING_CAPACITY": ("cooling capacity", "cooling tons", "cooling"),
    "HEATING_CAPACITY": ("heating capacity", "heating output", "heating btu"),
    "TOTAL_CAPACITY": ("total capacity", "total tons", "capacity"),
    "SENSIBLE_CAPACITY": ("sensible capacity", "sensible"),
    "ENTERING_DB": ("entering db", "e db", "edb"),
    "ENTERING_WB": ("entering wb", "e wb", "ewb"),
    "LEAVING_DB": ("leaving db", "l db", "ldb"),
    "LEAVING_WB": ("leaving wb", "l wb", "lwb"),
    "EAT": ("eat",),
    "LAT": ("lat",),
    "FILTER": ("filter", "filter type"),
    "FILTER_SIZE": ("filter size",),
    "HEAT_TYPE": ("heat type", "heating type"),
    "HEATER_KW": ("heater kw", "heat kw", "electric heat"),
    "REFRIGERANT": ("refrigerant", "refrig", "refr"),
    "ELECTRICAL": ("electrical", "electrical data"),
    "CONTROL_TYPE": ("control type", "controls"),
    "THERMOSTAT": ("thermostat", "thermostat tag"),
    "BAS": ("bas", "bas point"),
    "INTERLOCK": ("interlock",),
    "NECK_SIZE": ("neck size", "neck", "neck opening"),
    "FACE_SIZE": ("face size", "face", "face dim"),
    "SIZE": ("size", "grille size", "diffuser size", "dimensions", "duct size"),
    "NC": ("nc",),
    "THROW": ("throw",),
    "DAMPER": ("damper",),
    "REMARKS": ("remarks", "notes", "comments", "note"),
    "QUANTITY2": ("qty",),
}
_UNIT_ALIASES = {
    "cfm": "CFM", "ft3/min": "CFM", "l/s": "L/S",
    "fpm": "FPM", "ft/min": "FPM",
    "in wc": "IN.W.C.", "in.w.g.": "IN.W.G.", "in w.g.": "IN.W.G.",
    "pa": "PA", "psig": "PSIG",
    "rpm": "RPM", "hz": "HZ",
    "hp": "HP", "bhp": "BHP", "kw": "KW",
    "v": "V", "volts": "V", "a": "A", "amps": "A",
    "tons": "TONS", "btuh": "BTUH", "btu/h": "BTUH", "kw": "KW",
    "f": "F", "c": "C", "db": "DB", "wb": "WB", "rh": "RH", "%": "%",
    "mfd": "MFD", "vac": "VAC",
}
_UNIT_INFER = {
    "SUPPLY_CFM": "CFM", "RETURN_CFM": "CFM", "OUTSIDE_AIR_CFM": "CFM",
    "EXHAUST_CFM": "CFM", "TOTAL_CFM": "CFM", "DESIGN_CFM": "CFM",
    "MIN_CFM": "CFM", "MAX_CFM": "CFM",
    "FAN_RPM": "RPM", "MOTOR_RPM": "RPM", "RPM": "RPM",
    "ESP": "IN.W.G.", "TSP": "IN.W.G.", "STATIC_PRESSURE": "IN.W.G.",
    "BHP": "BHP", "MOTOR_HP": "HP", "HP": "HP",
    "VOLTS": "V", "HZ": "HZ", "MCA": "A", "MOCP": "A", "FLA": "A",
    "COOLING_CAPACITY": "TONS", "TOTAL_CAPACITY": "TONS",
    "HEATER_KW": "KW", "ENTERING_DB": "F", "LEAVING_DB": "F",
}
_MERGED_TOKENS = {
    "designcfm": "DESIGN_CFM", "necksize": "NECK_SIZE", "facesize": "FACE_SIZE",
    "supplycfm": "SUPPLY_CFM", "returncfm": "RETURN_CFM", "exhaustcfm": "EXHAUST_CFM",
    "outsideaircfm": "OUTSIDE_AIR_CFM", "grillesize": "SIZE",
    "diffusersize": "SIZE", "fanrpm": "FAN_RPM", "motorhp": "MOTOR_HP",
    "coolingcapacity": "COOLING_CAPACITY", "heatingcapacity": "HEATING_CAPACITY",
    "hpvfd": "VFD", "oacfm": "OUTSIDE_AIR_CFM",
}


def normalize_field_heading(literal: str | None) -> tuple[str | None, str]:
    """Return (canonical field, literal heading). Unknown -> (None, literal)."""
    if not literal:
        return None, ""
    norm = re.sub(r"[^a-z0-9 ]", "", literal.strip().lower())
    compact = norm.replace(" ", "")
    if compact in _MERGED_TOKENS:
        return _MERGED_TOKENS[compact], literal
    best: str | None = None
    best_len = 0
    for field, aliases in SCHEDULE_FIELD_ALIASES.items():
        for alias in aliases:
            a = re.sub(r"[^a-z0-9 ]", "", alias.lower())
            if norm == a or (len(a) > 2 and norm.startswith(a[:6])):
                if len(a) > best_len:
                    best, best_len = field, len(a)
    return best, literal


def parse_value(raw: str | None, canonical: str | None) -> dict[str, Any]:
    """raw_text + normalized_value + unit + data_type for a schedule cell."""
    raw_text = (raw or "").strip()
    if not raw_text:
        return {"raw_text": "", "normalized_value": None, "unit": None,
                "data_type": None, "confidence": None}
    text = raw_text
    unit: str | None = None
    unit_match = re.search(r"([A-Za-z/\.]{1,8}$)", text.replace(",", " "))
    for token, canonical_unit in _UNIT_ALIASES.items():
        if re.search(r"\b" + re.escape(token) + r"\b", text, re.IGNORECASE):
            unit = canonical_unit
            break
    number_match = re.search(r"-?\d[\d,.]*", text)
    normalized: float | str | None = None
    data_type = "STRING"
    if number_match:
        try:
            normalized = float(number_match.group(0).replace(",", ""))
            data_type = "NUMBER"
        except ValueError:
            normalized = None
    if normalized is None and text in ("YES", "NO", "Y", "N"):
        data_type = "BOOLEAN"
    elif normalized is None:
        data_type = "STRING"
    if unit is None and canonical in _UNIT_INFER and normalized is not None:
        unit = _UNIT_INFER[canonical]
    return {"raw_text": raw_text, "normalized_value": normalized,
            "unit": unit, "data_type": data_type, "confidence": None}


@dataclass
class RawScheduleColumn:
    literal_heading: str
    normalized_heading: str | None  # None = CUSTOM_SCHEDULE_FIELD
    index: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"literal_heading": self.literal_heading,
                "normalized_heading": self.normalized_heading,
                "index": self.index}


@dataclass
class RawScheduleRow:
    cells: dict[str, dict[str, Any]]  # normalized_heading or CUSTOM -> value dict
    raw_cells: dict[str, str] = field(default_factory=dict)
    source_bbox: tuple[float, float, float, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"cells": self.cells, "raw_cells": self.raw_cells,
                "source_bbox": list(self.source_bbox) if self.source_bbox else None}


@dataclass
class RawSchedule:
    sheet: str | None
    page: int
    kind: str
    columns: list[RawScheduleColumn]
    rows: list[RawScheduleRow]
    literal_headings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "sheet": self.sheet, "page": self.page, "kind": self.kind,
            "columns": [c.to_dict() for c in self.columns],
            "rows": [r.to_dict() for r in self.rows],
            "literal_headings": self.literal_headings,
        }


def _exhaustive_records(words: list[plans.Word]) -> list[dict[str, dict[str, Any]]]:
    """Column-preserving parser: every header word becomes a column.

    Returns rows as {field_key: value_dict} where field_key is the canonical
    field when recognized, else the literal heading (CUSTOM_SCHEDULE_FIELD).
    """
    lines = plans._words_to_rows(words)
    if not lines:
        return []

    def role_of(text: str) -> str | None:
        return normalize_field_heading(text)[0]

    # header line = the line among the first 5 with the most recognized fields
    header_idx = -1
    header_words: list[plans.Word] = []
    best_roles = 0
    for idx, line in enumerate(lines[:6]):
        roles = [1 for w in line if role_of(w.text)]
        if len(roles) >= 3 and len(roles) > best_roles:
            best_roles = len(roles)
            header_idx = idx
            header_words = sorted(line, key=lambda w: w.x0)
    if header_idx < 0:
        return []
    # merge adjacent header words that form a known multi-word heading
    phrases: list[tuple[float, str, float]] = []  # (x0, phrase, x1)
    for w in header_words:
        if phrases and plans._MERGE_HEADER_PAIRS & {phrases[-1][1] + " " + w.text.upper()}:
            x0, phrase, _x1 = phrases[-1]
            phrases[-1] = (x0, phrase + " " + w.text.upper(), w.x1)
        else:
            phrases.append((w.x0, w.text.upper(), w.x1))
    columns: list[tuple[float, str, str | None]] = [
        (x0, phrase, normalize_field_heading(phrase)[0]) for x0, phrase, _x1 in phrases
    ]
    starts = [c[0] for c in columns]

    def column_key(word: plans.Word) -> str | None:
        nearest = min(range(len(starts)), key=lambda i: abs(word.x0 - starts[i]))
        _x0, phrase, canonical = columns[nearest]
        return canonical or phrase  # CUSTOM keeps the literal heading

    tag_re = re.compile(r"^[A-Z]{1,4}-?\d{1,3}$")
    rows: list[dict[str, dict[str, Any]]] = []
    for line in lines[header_idx + 1:]:
        cells: dict[str, list[str]] = {}
        for w in sorted(line, key=lambda x: x.x0):
            key = column_key(w)
            if key is None:
                continue
            cells.setdefault(key, []).append(w.text)
        record: dict[str, dict[str, Any]] = {}
        for key, parts in cells.items():
            raw = " ".join(parts)
            canonical = normalize_field_heading(key)[0] or key
            record[key] = parse_value(raw, canonical)
        tag = next((v.get("raw_text") for k, v in record.items()
                    if normalize_field_heading(k)[0] == "TAG"), "")
        if tag and tag_re.match(tag.strip().upper()):
            rows.append(record)
    # ordered columns from the header phrases (preserves all-empty columns)
    ordered_columns = [(c[1], normalize_field_heading(c[1])[0]) for c in columns]
    return ordered_columns, rows


def schedules_from_words(
    words: list[plans.Word],
    *,
    sheet: str | None = None,
    page: int | None = None,
) -> list[RawSchedule]:
    """Build exhaustive RawSchedules from page words (native or OCR).

    Preserves every column (literal heading + canonical when recognized) and
    every row. Unknown columns are kept as CUSTOM_SCHEDULE_FIELD with the
    literal heading preserved.
    """
    columns_meta, rows = _exhaustive_records(words)
    if not rows:
        return []
    kinds = set()
    for record in rows:
        tag = next((v.get("raw_text", "").upper() for k, v in record.items()
                    if normalize_field_heading(k)[0] == "TAG"), "")
        type_text = next((v.get("raw_text", "").upper() for k, v in record.items()
                          if normalize_field_heading(k)[0] == "TYPE"), "")
        has_cfm = any(normalize_field_heading(k)[0] in (
            "DESIGN_CFM", "SUPPLY_CFM", "RETURN_CFM", "EXHAUST_CFM",
            "OUTSIDE_AIR_CFM", "MIN_CFM", "MAX_CFM") for k in record)
        is_equipment = any(normalize_field_heading(k)[0] in ("MANUFACTURER", "MODEL")
                           for k in record)
        if tag and is_equipment:
            if any(t in type_text for t in ("RTU", "ROOFTOP")):
                kinds.add("RTU_SCHEDULE")
            elif any(t in type_text for t in ("AHU", "AIR HANDLER")):
                kinds.add("AHU_SCHEDULE")
            elif any(t in type_text for t in ("FAN", "BLOWER")):
                kinds.add("FAN_SCHEDULE")
            else:
                kinds.add("EQUIPMENT_SCHEDULE")
        elif tag and has_cfm:
            kinds.add("VAV_SCHEDULE" if "VAV" in type_text else "AIR_DEVICE_SCHEDULE")
        elif tag:
            kinds.add("EQUIPMENT_SCHEDULE")

    columns = [
        RawScheduleColumn(
            literal_heading=literal_heading,
            normalized_heading=canonical or "CUSTOM_SCHEDULE_FIELD",
            index=i,
        )
        for i, (literal_heading, canonical) in enumerate(columns_meta)
    ]
    schedule_rows = [RawScheduleRow(cells=record) for record in rows]
    return [RawSchedule(sheet=sheet, page=page,
                        kind=",".join(sorted(kinds)) or "SCHEDULE",
                        columns=columns, rows=schedule_rows,
                        literal_headings=[c.literal_heading for c in columns])]
