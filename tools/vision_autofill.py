"""Deterministic auto-population + evidence reconciliation for the SCS vision
corpus labeling UI.

Pulls together every available evidence source per photo (OCR exact text,
MiniCPM candidate facts, deterministic rules, photo context, equipment
association) and produces a PROPOSAL for the ground-truth fields:

    proposal = {
        "fields": {
            "photo_type":   {"value": ..., "status": "green"|"yellow"|"red",
                              "source": "OCR"|"VLM"|"RULE", "error_class": ...,
                              "alternatives": [...]},
            "manufacturer": {...},
            "model":        {...},
            "serial":       {...},
            "equipment_type": {...},
            "equipment_tag":  {...},
            "visible_text": {...},
        },
        "readings":  [{"reading_type","value","unit","source_photo","confidence"}],
        "nameplate": "...",            # concise human summary
        "verdict": "SAFE_CONFIRM"|"NEEDS_REVIEW"|"CONFLICTS"|"UNKNOWN",
        "tag": "..." or None,
        "proposed_equipment": "...",
        "association_reason": "...",
        "association_confidence": ...,
    }

Field status colors (used by the UI):
    green  = strongly corroborated (OCR + VLM agree, or deterministic rule)
    yellow = uncertain / low confidence
    red    = conflict or known error class (cert agency as mfr, component as
             equipment type, model/serial swap, label header as manufacturer)

Ground-truth integrity is NOT weakened: proposals are suggestions only; the
owner confirms. Nothing here claims AI output is automatically truth.
"""

from __future__ import annotations

import re
from typing import Any

try:
    import vision_field_catalog as _CATALOG  # type: ignore
except Exception:  # pragma: no cover - catalog is optional for standalone use
    _CATALOG = None

# --------------------------------------------------------------------------
# Reference data (deterministic rules)
# --------------------------------------------------------------------------

KNOWN_MANUFACTURERS = [
    "LG", "CARRIER", "TRANE", "YORK", "RHEEM", "RUUD", "HONEYWELL",
    "JOHNSON CONTROLS", "INTERNATIONAL COMFORT PRODUCTS", "ICP", "TEMPSTAR",
    "HEIL", "KLEIN TOOLS", "FIELDPIECE", "ALNOR", "DAYTON", "CENTURY",
    "MARATHON", "GE", "GENERAL ELECTRIC", "EMERSON", "GOODMAN", "AMANA",
    "LENNOX", "MITSUBISHI", "DAIKIN", "FUJITSU", "BOSCH", "ABB", "SIEMENS",
    "SCHNEIDER", "TURBO ELECTRIC", "DUNSMORE", "SEMCO", "FLÄKTGROUP",
    "FLKTGROUP", "BESTECH", "AUXILION", "HITACHI", "日立",
    "ZHONGSHAN BROAD-OCEAN", "BROAD-OCEAN", "AERUS", "NORDYNE", "WHIRLPOOL",
    "WESTINGHOUSE", "RUSKIN", "TITUS", "PRICE", "GREENHECK", "YORK INTERNATIONAL",
    "RHEEM RUUD", "UPSTAIRS", "STAIRMASTER", "HONEYWELL HOME",
]

# Text that indicates certification/approval/regulatory content, NOT a
# manufacturer. CATCH: CERTIFICATION_AGENCY_AS_MANUFACTURER
CERTIFICATION_MARKERS = [
    "MIAMI-DADE COUNTY PRODUCT CONTROL", "PRODUCT CONTROL", "APPROVAL",
    "APPROVED", "CERTIFIED", "CERTIFICATION", "CONFORMS", "COMPLIANT",
    "COMPLIANCE", "REGISTERED", "LISTED", "ENERGY STAR", "AHRI", "ISO",
    "UNDERWRITERS", "MADE IN", "DISTRIBUTED BY", "IMPORTED BY",
]

# Components are NOT equipment types. CATCH: COMPONENT_AS_EQUIPMENT_TYPE
COMPONENT_TO_EQUIPMENT = {
    "COMPRESSOR": "CONDENSING UNIT / OUTDOOR UNIT",
    "CONDENSER": "CONDENSING UNIT / OUTDOOR UNIT",
    "CONDENSING UNIT": "CONDENSING UNIT / OUTDOOR UNIT",
    "POWER EXHAUST": "RTU",
    "POWER EXHAUST HUMIDIFIER": "RTU",
    "HUMIDIFIER": "EQUIPMENT",
    "FAN": "FAN",
    "BLOWER": "FAN",
    "MOTOR": "MOTOR",
    "VFD": "VFD",
    "VARIABLE FREQUENCY DRIVE": "VFD",
    "DISCONNECT": "DISCONNECT",
    "THERMOSTAT": "THERMOSTAT",
    "CONTROLLER": "CONTROLLER",
    "ACTUATOR": "ACTUATOR",
    "DAMPER": "DAMPER",
    "COIL": "COIL",
    "SENSOR": "SENSOR",
}
EQUIPMENT_TYPES = {
    "RTU": "RTU", "AHU": "AHU", "FCU": "FCU", "VAV": "VAV",
    "HEAT PUMP": "HEAT PUMP", "FURNACE": "FURNACE", "VRF": "VRF",
    "CHILLER": "CHILLER", "PUMP": "PUMP", "OUTDOOR UNIT": "OUTDOOR UNIT",
    "CONDENSING UNIT": "CONDENSING UNIT / OUTDOOR UNIT",
    "CONDENSING UNIT / OUTDOOR UNIT": "CONDENSING UNIT / OUTDOOR UNIT",
    "ROOFTOP UNIT": "RTU", "ROOF TOP UNIT": "RTU",
    "REMOTE TERMINAL UNIT": "REMOTE TERMINAL UNIT (ELECTRICAL)",
}

MODEL_STOPWORDS = {
    "RTU", "AHU", "FCU", "VAV", "FAN", "MOTOR", "COMPRESSOR", "HOME", "UNIT",
    "OTHER", "SYSTEM", "AIR", "HANDLING", "PACKAGED", "COOLING", "HEATING",
    "GAS", "ELECTRIC", "CONDENSING", "NONE", "NOT", "VISIBLE", "UNKNOWN",
    "MODEL", "NUMBER", "SERIAL", "CHARGED", "VOLTS", "HZ", "PHASE",
    "CONFIDENCE", "VALUE", "NAME", "TEXT", "ITEM", "LIST", "BOM", "DATA",
    "TITLE", "FONT", "SIZE", "TYPE", "LEVEL", "TEST", "DATE", "CODE", "LINE",
    "APPROVED", "CERTIFIED", "REGISTERED", "LISTED", "WARNING", "CAUTION",
    "INDOOR", "OUTDOOR", "SPLIT", "SYSTEMS", "SERIES", "CORPORATION", "INC",
    "LLC", "CO", "COMPANY", "KTGROUP", "SEMCO", "FL", "GRP", "GROUP",
}

# tokens that are manufacturer names or equipment types can never be models
_MFR_TOKENS = {tok for name in KNOWN_MANUFACTURERS for tok in name.upper().split()}

# A "serial" value that contains electrical spec text is not a serial.
# CATCH: LABEL_HEADER_AS_MANUFACTURER (sibling) + MODEL_SERIAL_SWAP
ELECTRICAL_MARKERS = [
    "LRA", "RLA", "FLA", "MCA", "MOCP", "PH ", "PHASE", " HZ", "M/C", "RMC",
    "FUSE", "VOLTS", "MAX", "MIN", "WATTS", "CHARGE",
]
ADDRESS_MARKERS = [
    "ST", "AVE", "AVENUE", "DR", "DRIVE", "BLVD", "BLVD.", "ROAD", "RD",
    "NORTH", "SOUTH", "EAST", "WEST", "MORRIS", "STREET",
]

TAG_RE = re.compile(r"^(?:RTU|AC|AHU|FCU|VAV|HP|CU|CD|MS|FC|OD|PU|CP)-?\s?\d{1,3}$")
LOOSE_TAG_RE = re.compile(r"^[A-Z]{1,4}-?\d{1,3}$")

PHOTO_TYPES = ["NAMEPLATE", "INSTRUMENT_READING", "TEMP_RH_READING", "DUCTWORK",
               "EQUIPMENT", "SYSTEM_STATIC", "OTHER"]

# --------------------------------------------------------------------------
# OCR normalization
# --------------------------------------------------------------------------


def flatten_ocr(ocr_text: Any) -> list[str]:
    """Return the list of raw OCR strings, tolerating varied entry shapes."""
    if not ocr_text:
        return []
    out: list[str] = []
    for entry in ocr_text:
        if isinstance(entry, str):
            out.append(entry)
        elif isinstance(entry, dict):
            text = entry.get("text") or entry.get("name") or entry.get("value")
            if isinstance(text, str):
                out.append(text)
        else:
            out.append(str(entry))
    return [t for t in out if t and t.strip()]


def ocr_joined(ocr_text: Any) -> str:
    return " ".join(flatten_ocr(ocr_text)).upper().strip()


def ocr_tokens(ocr_text: Any) -> list[str]:
    joined = ocr_joined(ocr_text)
    if not joined:
        return []
    return re.findall(r"[A-Z0-9]+(?:-[A-Z0-9]+)+|[A-Z0-9]+", joined)


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).upper()


# --------------------------------------------------------------------------
# Deterministic recognizers
# --------------------------------------------------------------------------


def _token_contains(tokens: list[str], marker: str) -> bool:
    joined = " " + " ".join(tokens) + " "
    return marker in joined


def detect_manufacturer_from_ocr(ocr_text: Any) -> tuple[str | None, float]:
    joined = ocr_joined(ocr_text)
    if not joined:
        return None, 0.0
    for name in sorted(KNOWN_MANUFACTURERS, key=len, reverse=True):
        if name.upper() in joined:
            return name.upper(), 0.95
    return None, 0.0


def is_certification_text(value: str) -> bool:
    v = _clean(value)
    return any(m.upper() in v for m in CERTIFICATION_MARKERS)


def looks_like_address(value: str) -> bool:
    v = _clean(value)
    words = v.split()
    if len(words) >= 3 and any(w in ADDRESS_MARKERS for w in words):
        return True
    return bool(re.search(r"\d{1,5}\s+[A-Z]+\s+(ST|AVE|DR|RD|BLVD)\.?", v))


def looks_like_electrical_spec(value: str) -> bool:
    v = _clean(value)
    return any(m in v for m in ELECTRICAL_MARKERS) and not re.fullmatch(
        r"[A-Z0-9-]{6,20}", v
    )


def is_serial_token(token: str) -> bool:
    if not token or token in MODEL_STOPWORDS:
        return False
    if re.fullmatch(r"[0-9]{6,}", token):
        return True
    if re.fullmatch(r"[A-Z0-9]{7,}", token) and any(c.isdigit() for c in token):
        return True
    if token.startswith("N2") and len(token) >= 6:
        return True
    return False


def is_manufacturer_or_type_token(token: str) -> bool:
    return token in _MFR_TOKENS or token in EQUIPMENT_TYPES


def is_model_token(token: str) -> bool:
    if not token or token in MODEL_STOPWORDS:
        return False
    if len(token) < 4:
        return False
    if not re.fullmatch(r"[A-Z0-9./+-]+", token):
        return False
    if not any(c.isalpha() for c in token):
        return False
    if any(c.isdigit() for c in token) or len(token) >= 7:
        return True
    return False


def _norm_key(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def known_manufacturer_match(value: str) -> str | None:
    """Return the canonical manufacturer if value matches a known name."""
    v = _clean(value)
    if not v:
        return None
    for name in sorted(KNOWN_MANUFACTURERS, key=len, reverse=True):
        if v == name.upper():
            return name.upper()
    head = v.split()[0] if v.split() else ""
    if head in {n.split()[0] for n in KNOWN_MANUFACTURERS}:
        return next((n.upper() for n in KNOWN_MANUFACTURERS
                     if n.split()[0] == head), None)
    return None


NON_SERIAL_LITERALS = {
    "NONE VISIBLE IN IMAGE", "<STRING|NULL>", "<STRING>", "NULL", "SF-6",
    "SF6", "R-410A", "R410A", "R-22", "R22", "R-32", "R32", "R-454B",
    "R454B", "UNKNOWN", "N/A", "NA", "NOT VISIBLE",
}


def near_match(a: str, b: str) -> bool:
    """Equal, substring, or single-edit (transposition/char) match."""
    ka, kb = _norm_key(a), _norm_key(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    if min(len(ka), len(kb)) >= 6 and (ka in kb or kb in ka):
        return True
    if len(ka) == len(kb) and _is_adjacent_swap(ka, kb):
        return True
    if len(ka) >= 6 and len(kb) >= 6 and abs(len(ka) - len(kb)) <= 1:
        if _levenshtein(ka, kb) <= 1:
            return True
    return False


def _is_adjacent_swap(a: str, b: str) -> bool:
    diff = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
    if len(diff) == 2 and diff[1] == diff[0] + 1:
        return a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]]
    return False


def _levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


SERIAL_TRAILING_GARBAGE = re.compile(r"(?:CHARGED|EVIDENCE|VERSION|REFRIGERANT)$")


# --------------------------------------------------------------------------
# Nameplate reading extraction (structural: reading_type/value/unit/...)
# --------------------------------------------------------------------------

_READING_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    ("RLA", re.compile(r"RLA\s*[:=]?\s*([\d.]+)"), "A"),
    ("FLA", re.compile(r"FLA\s*[:=]?\s*([\d.]+)"), "A"),
    ("MCA", re.compile(r"MCA\s*[:=]?\s*([\d.]+)"), "A"),
    ("MOCP", re.compile(r"MOCP\s*[:=]?\s*([\d.]+)"), "A"),
    ("MAX_FUSE", re.compile(r"MAX\s*FUSE\s*[:=]?\s*([\d.]+)"), "A"),
    ("MIN_FUSE", re.compile(r"MIN\s*FUSE\s*[:=]?\s*([\d.]+)"), "A"),
    ("VOLTAGE", re.compile(r"(?:VOLTS?|VOLTAGE|V\s*[:=]?)\s*[:=]?\s*(\d{3,4})"), "V"),
    ("PHASE", re.compile(r"(\d)\s*PH(?:ASE)?\b"), ""),
    ("FREQUENCY", re.compile(r"(\d{2})\s*HZ\b"), "Hz"),
    ("MOTOR_HP", re.compile(r"([\d.]+)\s*HP\b"), "HP"),
    ("DESIGN_PRESSURE", re.compile(r"DESIGN\s*PRESSURE\s*[:=]?\s*([\d.]+)"), "PSIG"),
    ("REFRIGERANT", re.compile(r"R-?(410A|454B|32|22|134A|404A|407C|12)\b"), ""),
    ("CHARGE", re.compile(r"CHARGE\s*[:=]?\s*([\d.]+)\s*(LBS?|OZ|KG)"), "LB"),
    ("MFG_DATE", re.compile(r"(?:MFG|MFR|MANUFACTURED|DATE)\s*[:=]?\s*(\d{2}[-/]\d{2,4}|\d{4})"), ""),
]

_READING_LABELS = {
    "RLA": "RLA", "FLA": "FLA", "MCA": "MCA", "MOCP": "MOCP",
    "MAX_FUSE": "Max fuse", "MIN_FUSE": "Min fuse", "VOLTAGE": "Voltage",
    "PHASE": "Phase", "FREQUENCY": "Frequency", "MOTOR_HP": "Motor HP",
    "DESIGN_PRESSURE": "Design pressure", "REFRIGERANT": "Refrigerant",
    "CHARGE": "Factory charge", "MFG_DATE": "Manufacture date",
}


def extract_nameplate_readings(ocr_text: Any,
                               facts: list[dict]) -> list[dict]:
    """Extract structural technical values from OCR + candidate facts."""
    joined = ocr_joined(ocr_text)
    readings: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for rtype, pattern, unit in _READING_PATTERNS:
        m = pattern.search(joined)
        if m:
            value = m.group(1)
            key = (rtype, value)
            if key not in seen:
                seen.add(key)
                readings.append({
                    "reading_type": rtype,
                    "value": value,
                    "unit": unit,
                    "source_photo": None,
                    "confidence": 0.55,
                })
    for fact in facts or []:
        if fact.get("unit") and fact.get("value"):
            key = (str(fact.get("field", "")), str(fact["value"]))
            if key not in seen:
                seen.add(key)
                readings.append({
                    "reading_type": str(fact.get("field", "")),
                    "value": str(fact["value"]),
                    "unit": str(fact.get("unit") or ""),
                    "source_photo": None,
                    "confidence": float(fact.get("confidence") or 0.5),
                })
    return readings


def nameplate_summary(readings: list[dict]) -> str:
    if not readings:
        return "No extractable nameplate values from available evidence."
    parts = []
    for r in readings:
        label = _READING_LABELS.get(r["reading_type"], r["reading_type"].replace("_", " ").title())
        unit = r.get("unit") or ""
        parts.append(f"{label} {r['value']} {unit}".strip())
    return " | ".join(parts)


# --------------------------------------------------------------------------
# Canonical multi-fact extraction (report-driven; SCS_REPORT_FIELD_CATALOG_V1)
# --------------------------------------------------------------------------

_READING_TO_FIELD = {
    "RLA": "rla", "FLA": "fla", "MCA": "mca", "MOCP": "mocp",
    "MAX_FUSE": "max_fuse", "MIN_FUSE": "min_fuse", "VOLTAGE": "voltage",
    "PHASE": "phase", "FREQUENCY": "frequency_hz", "MOTOR_HP": "horsepower",
    "DESIGN_PRESSURE": "design_pressures", "REFRIGERANT": "refrigerant",
    "CHARGE": "factory_charge", "MFG_DATE": "manufacture_date",
}

_AIRFLOW_PHOTO_TYPES = {"DUCTWORK", "TRAVERSE", "BUILDING_PRESSURE", "AIR_DEVICE",
                        "OA_INTAKE", "EXHAUST", "SYSTEM_STATIC"}
_INSTRUMENT_PHOTO_TYPES = {"AMP_READING", "VOLTAGE_READING", "RPM_READING",
                           "INSTRUMENT_READING", "MICROMANOMETER"}
_NUMERIC_RE = re.compile(r"^\d+(?:\.\d+)?(?:[-/]\d+(?:\.\d+)?)?$")


def _unit_to_field_id(unit: str, photo_type: str) -> str | None:
    """Map a measurement unit to the canonical catalog field for a photo type."""
    u = (unit or "").upper().strip()
    if not u:
        return None
    if u in ("V", "VAC", "VOLTS", "VDC"):
        return "voltage_a" if photo_type in _INSTRUMENT_PHOTO_TYPES else "voltage"
    if u in ("A", "AMP", "AMPS"):
        return "current_a" if photo_type in _INSTRUMENT_PHOTO_TYPES else "amps"
    if u in ("HZ", "HERTZ"):
        return "frequency_hz"
    if u in ("RPM",):
        return "rpm_measured" if photo_type in _INSTRUMENT_PHOTO_TYPES else "rpm"
    if u in ("HP", "HORSEPOWER"):
        return "horsepower"
    if u in ("CFM", "CFM2"):
        return "supply_air_cfm" if photo_type in _AIRFLOW_PHOTO_TYPES else "rated_airflow"
    if u in ("F", "C", "DEGF", "DEGC", "DEG F", "DEG C"):
        return "temperature"
    if u in ("%", "%RH", "RH", "PERCENT", "PCT"):
        return "rh"
    if u in ("INWC", "IN. WC", "IN.WC", "WC", "INH2O", "PA", "PSI", "PSIG", "MBAR"):
        return "static_pressure"
    if u in ("MFD", "UF", "MF"):
        return "capacitor_mfd"
    if u in ("TON", "TONS"):
        return "nominal_tonnage"
    if u in ("LB", "LBS", "OZ", "KG"):
        return "factory_charge"
    if u in ("KW",):
        return "electric_heat_kw"
    if u in ("BTUH", "BTU/H"):
        return "gas_input"
    return None


def _destination_candidates(field_id: str, catalog=None) -> list[dict]:
    """Serialize the catalog destinations for a field into JSON-safe records."""
    catalog = catalog or _CATALOG
    if not catalog:
        return []
    out: list[dict] = []
    for dest in catalog.field_def(field_id).get("DESTINATION_SHEETS") or []:
        if isinstance(dest, dict):
            out.append(dest)
        else:
            try:
                sheet, form_id, section, label = dest
            except Exception:
                continue
            out.append({"sheet": sheet, "form_id": form_id,
                        "section": section, "field_label": label})
    return out


def _ocr_region(value: str, ocr_lines: list[str]) -> str:
    v = str(value or "").strip().upper()
    for i, line in enumerate(ocr_lines):
        if v and v in line.upper():
            return f"OCR line {i + 1}"
    return "OCR"


def _merge_identity_facts(canon: dict, fields: dict[str, dict]) -> dict:
    """Fold reconcile adjudication into identity facts so the UI never shows
    raw garbage (cert agency, electrical spec, address) as truth."""
    for fid in ("photo_type", "manufacturer", "model", "serial",
                "equipment_type", "equipment_tag"):
        fld = fields.get(fid) or {}
        fval = str(fld.get("value") or "")
        fstatus = fld.get("status")
        ferr = fld.get("error_class")
        fact = next((f for f in canon["facts"] if f["field_type"] == fid), None)
        if ferr:
            if fact is None:
                fact = {
                    "field_type": fid, "value": fval, "unit": "",
                    "source_region": "reconcile", "OCR_text": fval,
                    "confidence": 0.2, "extraction_method": "RULE",
                    "corroboration": "SINGLE", "needs_confirmation": True,
                    "expected_by_report": fid in canon["expected_fields"],
                    "destination_candidates": _destination_candidates(fid),
                }
                canon["facts"].append(fact)
            fact["value"] = fval
            fact["error_class"] = ferr
            fact["needs_confirmation"] = True
            fact["extraction_method"] = "RULE"
            fact["confidence"] = min(float(fact.get("confidence") or 1.0), 0.3)
        elif fval and fstatus == "green":
            if fact is None:
                fact = {
                    "field_type": fid, "value": fval, "unit": "",
                    "source_region": "reconcile", "OCR_text": fval,
                    "confidence": 0.9, "extraction_method": "OCR_REGEX",
                    "corroboration": "SINGLE", "needs_confirmation": False,
                    "expected_by_report": fid in canon["expected_fields"],
                    "destination_candidates": _destination_candidates(fid),
                }
                canon["facts"].append(fact)
            elif fact["value"] != fval:
                fact["value"] = fval
                fact["needs_confirmation"] = False
                fact["confidence"] = max(float(fact.get("confidence") or 0.0), 0.85)
    have = {f["field_type"] for f in canon["facts"]}
    canon["absent_fields"] = {fid: v for fid, v in canon["absent_fields"].items()
                              if fid not in have}
    return canon


def extract_canonical_facts(photo: dict,
                           ocr_text: Any = None,
                           facts: list[dict] = None,
                           candidate_class: str = None,
                           photo_type: str = None,
                           catalog=None) -> dict:
    """Build the report-driven candidate-fact list for one photo.

    Every candidate fact carries full provenance (field_type, value, unit,
    source_region, OCR_text, confidence, extraction_method, corroboration,
    needs_confirmation, expected_by_report, destination_candidates[]) so the
    labeling UI can confirm/reject facts per catalog field and the benchmark
    can measure fact recall/precision against the report schema.
    """
    catalog = catalog or _CATALOG
    ocr_text = ocr_text if ocr_text is not None else photo.get("ocr_text")
    facts = facts if facts is not None else photo.get("candidate_facts")
    candidate_class = candidate_class if candidate_class is not None else photo.get("candidate_class")
    ocr_lines = flatten_ocr(ocr_text)

    et_val = ""
    for f in facts or []:
        if str(f.get("field") or "") == "equipment_type":
            et_val = str(f.get("value") or "")
            break
    if photo_type is None:
        photo_type = catalog.canonical_photo_type(candidate_class, et_val) if catalog else "OTHER"
    schema = list(catalog.schema_fields(photo_type)) if catalog else []

    seen: dict[str, list[dict]] = {}

    def add(field_id: str, value, unit, region, raw, conf, method):
        if not field_id or value is None:
            return
        v = str(value).strip()
        if v in ("", "N/A", "NA", "UNKNOWN", "NONE", "NOT VISIBLE"):
            return
        defn = catalog.field_def(field_id) if catalog else {}
        dtype = defn.get("DATA_TYPE")
        if dtype == "NUMBER" and not _NUMERIC_RE.match(v):
            return
        if dtype in ("STRING", "ENUM", "CODE"):
            v = " ".join(v.upper().split())
        item = {
            "field_type": field_id,
            "value": v,
            "unit": unit or defn.get("UNIT") or "",
            "source_region": region,
            "OCR_text": raw,
            "confidence": round(float(conf), 2),
            "extraction_method": method,
            "corroboration": "SINGLE",
            "needs_confirmation": float(conf) < 0.7,
            "expected_by_report": field_id in schema,
            "destination_candidates": _destination_candidates(field_id, catalog),
        }
        seen.setdefault(field_id, []).append(item)

    # 1) OCR structural readings -> canonical fields
    for r in extract_nameplate_readings(ocr_text, facts):
        field_id = _READING_TO_FIELD.get(r["reading_type"])
        if field_id is None:
            field_id = str(r["reading_type"]).lower()
            if catalog and field_id not in catalog.FIELD_CATALOG_V1:
                continue
        add(field_id, r["value"], r["unit"], _ocr_region(r["value"], ocr_lines),
            r.get("source_photo") or r["value"], r["confidence"], "OCR_REGEX")

    # 2) OCR identity facts (manufacturer / tag) for corroboration
    ocr_mfr, _ = detect_manufacturer_from_ocr(ocr_text)
    if ocr_mfr:
        add("manufacturer", ocr_mfr, "", _ocr_region(ocr_mfr, ocr_lines),
            ocr_mfr, 0.9, "OCR_REGEX")
    ocr_tag = detect_tag_from_ocr(ocr_text)
    if ocr_tag:
        add("equipment_tag", ocr_tag, "", _ocr_region(ocr_tag, ocr_lines),
            ocr_tag, 0.85, "OCR_REGEX")

    # 3) VLM candidate facts -> canonical fields
    for f in facts or []:
        fname = str(f.get("field") or "").strip()
        fval = f.get("value")
        funit = f.get("unit")
        conf = f.get("confidence") or 0.5
        region = f"VLM fact '{fname}'"
        if fname in ("manufacturer", "model", "serial", "equipment_type", "equipment_tag"):
            add(fname, fval, "", region, str(fval), conf, "VLM_FACT")
        elif fname.startswith("reading_"):
            field_id = _unit_to_field_id(funit, photo_type)
            if field_id:
                add(field_id, fval, funit, region, str(fval), conf, "VLM_FACT")
        else:
            field_id = re.sub(r"[^a-z0-9_]", "", fname.lower().replace(" ", "_"))
            if catalog and field_id in catalog.FIELD_CATALOG_V1:
                add(field_id, fval, funit, region, str(fval), conf, "VLM_FACT")

    # 4) merge duplicate evidence per canonical field (corroboration)
    merged: list[dict] = []
    for field_id, items in seen.items():
        if len(items) == 1:
            merged.append(items[0])
            continue
        best = max(items, key=lambda x: x["confidence"])
        agreeing = [x for x in items
                    if x["value"] == best["value"] or near_match(str(x["value"]), str(best["value"]))]
        if len(agreeing) >= 2:
            best["corroboration"] = "OCR+VLM"
            best["confidence"] = min(1.0, round(max(x["confidence"] for x in agreeing) + 0.05, 2))
            best["OCR_text"] = " | ".join(dict.fromkeys(str(x["OCR_text"]) for x in agreeing))
            best["source_region"] = " | ".join(dict.fromkeys(str(x["source_region"]) for x in agreeing))
            best["needs_confirmation"] = False
        else:
            best["needs_confirmation"] = True
        merged.append(best)

    # 5) absent fields per report schema (NOT_VISIBLE marking)
    have = {f["field_type"] for f in merged}
    absent: dict[str, dict] = {}
    for fid in schema:
        if fid in ("visible_text", "notes") or fid in have:
            continue
        absent[fid] = {
            "reason": "NOT_VISIBLE_IN_PHOTO",
            "destination_candidates": _destination_candidates(fid, catalog),
        }

    merged.sort(key=lambda f: (not f["expected_by_report"], f["field_type"]))
    return {
        "photo_type_schema": photo_type,
        "facts": merged,
        "expected_fields": schema,
        "absent_fields": absent,
    }


# --------------------------------------------------------------------------
# Equipment tag + association
# --------------------------------------------------------------------------


def detect_tag_from_ocr(ocr_text: Any) -> str | None:
    tokens = ocr_tokens(ocr_text)
    for token in tokens:
        if TAG_RE.match(token):
            return token
    for token in tokens:
        if LOOSE_TAG_RE.match(token) and not is_model_token(token) \
                and not re.fullmatch(r"[0-9]{1,4}", token):
            return token
    return None


def _equipment_tag(photo: dict) -> str | None:
    """Best known tag for a photo: confirmed label first, then AI proposal."""
    label = photo.get("label") or {}
    if label.get("equipment_tag"):
        return label["equipment_tag"]
    return photo.get("tag")


def proposal_equipment_association(photos: list[dict], idx: int,
                                   window: int = 6) -> tuple[str | None, str, float]:
    """Propose association to a nearby equipment record (sequence context only)."""
    current = photos[idx]
    for back in range(1, min(idx + 1, window + 1)):
        prev = photos[idx - back]
        tag = _equipment_tag(prev)
        if tag:
            conf = max(0.3, 0.95 - 0.12 * back)
            return (tag,
                    f"adjacent photo sequence + {tag} context (Δ{back} photos)",
                    round(conf, 2))
    return (None, "", 0.0)


# --------------------------------------------------------------------------
# Main reconciliation
# --------------------------------------------------------------------------


def _field(value, status, source, error_class=None, alternatives=None):
    out = {"value": value, "status": status, "source": source}
    if error_class:
        out["error_class"] = error_class
    if alternatives:
        out["alternatives"] = alternatives
    return out


def _facts_map(facts: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for f in facts or []:
        field = f.get("field")
        if field:
            out.setdefault(field, f)
    return out


def reconcile(photo: dict, ocr_text: Any = None, facts: list[dict] = None,
              candidate_class: str = None,
              candidate_confidence: float | None = None,
              catalog=None) -> dict:
    """Build the ground-truth proposal for one photo."""
    ocr_text = ocr_text if ocr_text is not None else photo.get("ocr_text")
    facts = facts if facts is not None else photo.get("candidate_facts")
    candidate_class = candidate_class if candidate_class is not None else photo.get("candidate_class")
    if candidate_confidence is None:
        candidate_confidence = photo.get("candidate_confidence")

    fm = _facts_map(facts)
    tokens = ocr_tokens(ocr_text)
    joined = ocr_joined(ocr_text)

    fields: dict[str, dict] = {}

    # --- PHOTO_TYPE -----------------------------------------------------
    if candidate_class and candidate_class in PHOTO_TYPES:
        status = "green" if (candidate_confidence or 0) >= 0.8 else "yellow"
        fields["photo_type"] = _field(candidate_class, status, "VLM")
    else:
        fields["photo_type"] = _field("OTHER", "yellow", "RULE")

    # --- MANUFACTURER ---------------------------------------------------
    ocr_mfr, _ = detect_manufacturer_from_ocr(ocr_text)
    vlm_mfr = _clean(fm.get("manufacturer", {}).get("value"))
    known_vlm = known_manufacturer_match(vlm_mfr) if vlm_mfr else None
    if ocr_mfr:
        if known_vlm and near_match(known_vlm, ocr_mfr):
            fields["manufacturer"] = _field(ocr_mfr, "green", "OCR+VLM",
                                            alternatives=[vlm_mfr] if vlm_mfr != ocr_mfr else None)
        elif known_vlm and is_certification_text(vlm_mfr):
            # CATCH: CERTIFICATION_AGENCY_AS_MANUFACTURER
            fields["manufacturer"] = _field(
                ocr_mfr, "green", "OCR",
                error_class="CERTIFICATION_AGENCY_AS_MANUFACTURER",
                alternatives=[vlm_mfr])
        else:
            fields["manufacturer"] = _field(ocr_mfr, "green", "OCR",
                                            alternatives=[vlm_mfr] if vlm_mfr else None)
    elif vlm_mfr:
        if is_certification_text(vlm_mfr):
            # CATCH: CERTIFICATION_AGENCY_AS_MANUFACTURER
            fields["manufacturer"] = _field(
                "", "red", "VLM",
                error_class="CERTIFICATION_AGENCY_AS_MANUFACTURER",
                alternatives=[vlm_mfr])
        else:
            status = "green" if known_vlm else "yellow"
            fields["manufacturer"] = _field(known_vlm or vlm_mfr, status, "VLM")
    else:
        fields["manufacturer"] = _field("", "yellow", "RULE")

    # --- MODEL -----------------------------------------------------------
    ocr_models = [t for t in tokens
                  if is_model_token(t) and not is_manufacturer_or_type_token(t)
                  and not t.startswith(("N2", "R2")) and "XXXX" not in t]
    vlm_model = _clean(fm.get("model", {}).get("value"))
    if vlm_model in ("UNKNOWN", "UNKNOWN MODEL NUMBER.", "NONE"):
        vlm_model = ""
    if vlm_model and (not is_model_token(vlm_model)
                      or is_manufacturer_or_type_token(vlm_model)):
        vlm_model = next((t for t in vlm_model.replace("/", " ").split()
                          if is_model_token(t) and not is_manufacturer_or_type_token(t)), "")
    if ocr_models and vlm_model:
        if near_match(ocr_models[0], vlm_model):
            fields["model"] = _field(vlm_model, "green", "OCR+VLM")
        elif any(near_match(m, vlm_model) for m in ocr_models):
            fields["model"] = _field(vlm_model, "green", "OCR+VLM")
        else:
            fields["model"] = _field(
                ocr_models[0], "red", "OCR",
                error_class="OCR_VLM_CONFLICT",
                alternatives=[vlm_model])
    elif ocr_models:
        fields["model"] = _field(ocr_models[0], "green", "OCR")
    elif vlm_model:
        fields["model"] = _field(vlm_model, "yellow", "VLM")
    else:
        fields["model"] = _field("", "yellow", "RULE")

    # --- SERIAL ----------------------------------------------------------
    vlm_serial = _clean(fm.get("serial", {}).get("value"))
    if vlm_serial in NON_SERIAL_LITERALS:
        vlm_serial = ""
    ocr_serials = [SERIAL_TRAILING_GARBAGE.sub("", t) or t for t in tokens
                   if is_serial_token(t) and "XXXX" not in t]
    model_norm = _norm_key(fields["model"].get("value", ""))
    ocr_serials = [t for t in ocr_serials
                   if not model_norm or model_norm not in _norm_key(t)]
    vlm_serial_invalid = bool(
        vlm_serial and len(re.sub(r"[^A-Z0-9-]", "", vlm_serial)) < len(vlm_serial))
    if ocr_serials:
        if vlm_serial and not vlm_serial_invalid and not looks_like_address(vlm_serial) \
                and not looks_like_electrical_spec(vlm_serial):
            if near_match(ocr_serials[0], vlm_serial):
                fields["serial"] = _field(vlm_serial, "green", "OCR+VLM")
            else:
                fields["serial"] = _field(
                    ocr_serials[0], "red", "OCR",
                    error_class="OCR_VLM_CONFLICT", alternatives=[vlm_serial])
        else:
            fields["serial"] = _field(ocr_serials[0], "green", "OCR")
    elif vlm_serial:
        if looks_like_address(vlm_serial):
            # CATCH: address captured as serial
            fields["serial"] = _field("", "red", "VLM",
                                      error_class="ADDRESS_AS_SERIAL",
                                      alternatives=[vlm_serial])
        elif looks_like_electrical_spec(vlm_serial):
            # CATCH: electrical spec captured as serial (PHOTO-003 style)
            fields["serial"] = _field("", "red", "VLM",
                                      error_class="ELECTRICAL_SPEC_AS_SERIAL",
                                      alternatives=[vlm_serial])
        else:
            fields["serial"] = _field(vlm_serial, "yellow", "VLM")
    else:
        fields["serial"] = _field("", "yellow", "RULE")

    # --- EQUIPMENT_TYPE --------------------------------------------------
    vlm_et = _clean(fm.get("equipment_type", {}).get("value"))
    if vlm_et in ("UNKNOWN", "NONE", "UNKNOWN EQUIPMENT TYPE"):
        vlm_et = ""
    ocr_et_hit = None
    for token in tokens:
        if token in EQUIPMENT_TYPES:
            ocr_et_hit = EQUIPMENT_TYPES[token]
            break
    if vlm_et:
        base = vlm_et.split("(")[0].strip().rstrip(" /-")
        if base in EQUIPMENT_TYPES:
            # plain type normalization (RTU/AHU/ROOFTOP UNIT -> RTU) is not an error
            canonical = EQUIPMENT_TYPES[base]
            if ocr_et_hit:
                if near_match(ocr_et_hit, canonical):
                    fields["equipment_type"] = _field(canonical, "green", "OCR+VLM")
                else:
                    fields["equipment_type"] = _field(
                        ocr_et_hit, "red", "OCR",
                        error_class="OCR_VLM_CONFLICT", alternatives=[canonical])
            else:
                fields["equipment_type"] = _field(canonical, "yellow", "VLM")
        elif base in COMPONENT_TO_EQUIPMENT:
            mapped = COMPONENT_TO_EQUIPMENT[base]
            # CATCH: COMPONENT_AS_EQUIPMENT_TYPE (COMPRESSOR etc.)
            fields["equipment_type"] = _field(
                mapped, "red" if ocr_et_hit and not near_match(ocr_et_hit, mapped) else "yellow",
                "RULE", error_class="COMPONENT_AS_EQUIPMENT_TYPE",
                alternatives=[vlm_et])
        elif ocr_et_hit:
            if near_match(ocr_et_hit, base):
                fields["equipment_type"] = _field(base, "green", "OCR+VLM")
            else:
                fields["equipment_type"] = _field(
                    ocr_et_hit, "red", "OCR",
                    error_class="OCR_VLM_CONFLICT", alternatives=[base])
        else:
            fields["equipment_type"] = _field(base, "yellow", "VLM")
    elif ocr_et_hit:
        if candidate_class in ("INSTRUMENT_READING", "TEMP_RH_READING"):
            fields["equipment_type"] = _field(ocr_et_hit, "yellow", "OCR")
        else:
            fields["equipment_type"] = _field(ocr_et_hit, "green", "OCR")
    else:
        fields["equipment_type"] = _field("", "yellow", "RULE")

    # --- EQUIPMENT_TAG (never fabricated) --------------------------------
    vlm_tag = _clean(fm.get("equipment_tag", {}).get("value"))
    ocr_tag = detect_tag_from_ocr(ocr_text)
    if vlm_tag and (TAG_RE.match(vlm_tag) or LOOSE_TAG_RE.match(vlm_tag)) \
            and not re.fullmatch(r"[0-9]{1,4}", vlm_tag):
        if ocr_tag and near_match(ocr_tag, vlm_tag):
            fields["equipment_tag"] = _field(vlm_tag, "green", "OCR+VLM")
        else:
            fields["equipment_tag"] = _field(vlm_tag, "yellow", "VLM")
    elif ocr_tag:
        fields["equipment_tag"] = _field(ocr_tag, "green", "OCR")
    else:
        fields["equipment_tag"] = _field("", "yellow", "RULE")

    # --- VISIBLE_TEXT ----------------------------------------------------
    visible = []
    for tok in tokens:
        if (len(tok) >= 3 and tok not in MODEL_STOPWORDS
                and not is_model_token(tok) and not is_serial_token(tok)
                and tok not in EQUIPMENT_TYPES and not TAG_RE.match(tok)):
            visible.append(tok)
    if visible:
        fields["visible_text"] = _field(" ".join(visible), "yellow", "OCR")
    else:
        fields["visible_text"] = _field("", "yellow", "RULE")

    # --- readings + summary ----------------------------------------------
    readings = extract_nameplate_readings(ocr_text, facts)
    nameplate = nameplate_summary(readings)

    # --- report-driven canonical facts (SCS_REPORT_FIELD_CATALOG_V1) -----
    catalog = catalog or _CATALOG
    et_val = _clean(fm.get("equipment_type", {}).get("value")) \
        or fields["equipment_type"].get("value") or ""
    photo_type_schema = (catalog.canonical_photo_type(fields["photo_type"]["value"], et_val)
                         if catalog else fields["photo_type"]["value"])
    canon = extract_canonical_facts(photo, ocr_text=ocr_text, facts=facts,
                                    candidate_class=candidate_class,
                                    photo_type=photo_type_schema, catalog=catalog)
    canon = _merge_identity_facts(canon, fields)

    # --- verdict ----------------------------------------------------------
    identity = ["manufacturer", "model", "serial", "equipment_type"]
    red = [f for f in identity if fields[f].get("status") == "red"]
    has_error_class = any(fields[f].get("error_class") for f in identity)
    model_serial_green = (fields["model"].get("status") == "green"
                          and fields["serial"].get("status") == "green")
    mfr_ok = bool(fields["manufacturer"].get("value")
                  and fields["manufacturer"].get("status") == "green")
    et_ok = (fields["equipment_type"].get("status") == "green"
             and bool(fields["equipment_type"].get("value")))
    no_evidence = all(not fields[f].get("value") for f in identity)

    if red or has_error_class:
        verdict = "CONFLICTS"
    elif no_evidence:
        verdict = "UNKNOWN"
    elif model_serial_green and mfr_ok and et_ok:
        verdict = "SAFE_CONFIRM"
    else:
        verdict = "NEEDS_REVIEW"

    proposal = {
        "fields": fields,
        "readings": readings,
        "nameplate": nameplate,
        "verdict": verdict,
        "tag": fields["equipment_tag"].get("value") or None,
        "photo_type_schema": photo_type_schema,
        "expected": canon["expected_fields"],
        "facts": canon["facts"],
        "absent_fields": canon["absent_fields"],
    }
    return proposal


def autopopulated_fields(proposal: dict) -> int:
    """Count identity fields carrying real evidence (photo_type/visible_text
    are not identity; default OTHER photo_type never counts)."""
    f = proposal["fields"]
    return sum(1 for k in ("manufacturer", "model", "serial", "equipment_type")
               if f[k].get("value"))


def attach_sequences(photos: list[dict], window: int = 6) -> None:
    """Attach proposed_equipment / association context to each photo."""
    for idx, p in enumerate(photos):
        tag, reason, conf = proposal_equipment_association(photos, idx, window)
        p["proposed_equipment"] = tag
        p["association_reason"] = reason
        p["association_confidence"] = conf