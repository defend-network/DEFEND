"""Natural-language measurement capture for the field copilot.

Turns quick owner statements into structured facts WITHOUT overwriting
as-found values. Example:

    "Studio A SA-3 was 142 CFM as found. I opened the damper and got 181 final."

becomes:

    MeasurementCapture(device_id="SA-3", area_served="Studio A",
                       as_found_cfm=142.0, final_cfm=181.0,
                       notes="damper opened")
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_DEVICE_RE = re.compile(
    r"\b([A-Z][A-Z0-9]{0,3}(?:[ -]\d{1,3})?)\b"
)
_DEVICE_STOP = {
    "CFM", "FPM", "FINAL", "DESIGN", "AS", "FOUND", "PRELIM", "TOTAL",
    "SYSTEM", "STUDIO", "ROOM", "AREA", "DAMPER", "BELT", "OPENED", "CLOSED",
    "ADJUSTED", "I", "A", "B", "SA", "WAS", "GOT", "READING", "READINGS",
}
_NUM = re.compile(r"(\d{1,5}(?:\.\d+)?)\s*(CFM|FPM)\b", re.IGNORECASE)
_AREA_RE = re.compile(r"(Studio\s+[A-Z]?\w*|Room\s+\d+|Zone\s+\w+|Area\s+\w+)",
                      re.IGNORECASE)
_ADJUSTMENT_WORDS = ("damper", "belt", "opened", "closed", "adjusted",
                     "balanc", "readjust", "set", "turned", "throttled")


@dataclass
class MeasurementCapture:
    device_id: str | None
    area_served: str | None = None
    as_found_cfm: float | None = None
    final_cfm: float | None = None
    design_cfm: float | None = None
    avg_velocity_fpm: float | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "area_served": self.area_served,
            "as_found_cfm": self.as_found_cfm,
            "final_cfm": self.final_cfm,
            "design_cfm": self.design_cfm,
            "avg_velocity_fpm": self.avg_velocity_fpm,
            "notes": self.notes,
        }


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.;!?])\s+|\n", text.strip())
    return [p for p in parts if p.strip()]


def _find_device(sentence: str) -> str | None:
    """Return the most specific device tag (SA-3 > A) mentioned."""
    tokens = _DEVICE_RE.findall(sentence)
    candidates = []
    for token in tokens:
        token = token.upper().replace(" ", "-")
        if token in _DEVICE_STOP or len(token) < 2:
            continue
        candidates.append(token)
    if not candidates:
        return None
    candidates.sort(key=lambda t: len(t), reverse=True)
    return candidates[0]


def _find_area(sentence: str) -> str | None:
    match = _AREA_RE.search(sentence)
    return match.group(1) if match else None


def parse_measurements(text: str) -> list[MeasurementCapture]:
    """Parse a natural-language block into structured measurement captures.

    As-found values are only set when the statement marks them as-found
    (never overwritten by final). If a sentence has no explicit qualifier the
    value is treated as the latest reading. A sentence naming only an area
    (e.g. "Studio B total 1184 CFM final") is treated as a system total.
    """
    captures: list[MeasurementCapture] = []
    seen_device_last: MeasurementCapture | None = None
    last_unit = "CFM"
    for sentence in _split_sentences(text):
        low = sentence.lower()
        explicit_device = _find_device(sentence)
        area = _find_area(sentence)
        numbers = _NUM.findall(sentence)
        if not numbers:
            bare = re.findall(r"\d{1,5}(?:\.\d+)?", sentence)
            if bare and (explicit_device or (area is None and seen_device_last)):
                numbers = [(bare[-1], last_unit)]
        if not numbers:
            continue
        device = explicit_device
        if device is None and area is None and seen_device_last is not None:
            device = seen_device_last.device_id
            area = seen_device_last.area_served
        if device is None and any(w in low for w in ("total", "system")):
            device = "TOTAL"
        has_as_found = any(w in low for w in ("as found", "as-found", "found ",
                                              "prelim", "before"))
        has_final = any(w in low for w in ("final", "after", "got", "adjusted to"))
        has_design = any(w in low for w in ("design", "target", "rated"))
        if not has_as_found and not has_final and not has_design:
            has_final = True
        capture = MeasurementCapture(device_id=device)
        if area:
            capture.area_served = area
        for raw_value, unit in numbers:
            value = float(raw_value.replace(",", ""))
            if unit.upper() == "FPM":
                capture.avg_velocity_fpm = value
                last_unit = "FPM"
            elif has_as_found and capture.as_found_cfm is None:
                capture.as_found_cfm = value
                last_unit = "CFM"
            elif has_design and capture.design_cfm is None:
                capture.design_cfm = value
            elif capture.final_cfm is None:
                capture.final_cfm = value
        if any(w in low for w in _ADJUSTMENT_WORDS):
            capture.notes = sentence.strip()
        if capture.final_cfm is None and capture.as_found_cfm is None \
                and capture.design_cfm is None and capture.avg_velocity_fpm is None:
            continue
        captures.append(capture)
        seen_device_last = capture
    return captures


def merge_capture(record, capture: MeasurementCapture) -> bool:
    """Merge a parsed capture into an existing or new AirDevice on the record.

    as-found is never overwritten once set; final only updates when a newer
    value is provided. Returns True if the record changed.
    """
    from .schema import AirDevice

    device = None
    if capture.device_id:
        device = next(
            (d for d in record.air_devices
             if d.device_id.upper() == capture.device_id.upper()),
            None,
        )
    if device is None and capture.device_id:
        device = AirDevice(
            device_id=capture.device_id,
            function="SYSTEM" if capture.device_id == "TOTAL" else "SUPPLY",
            measurement_method="rotating vane",
        )
        record.air_devices.append(device)
    if device is None:
        return False
    if capture.area_served and not device.area_served:
        device.area_served = capture.area_served
    if capture.avg_velocity_fpm is not None:
        device.avg_velocity_fpm = capture.avg_velocity_fpm
    if capture.as_found_cfm is not None and device.as_found_cfm is None:
        device.as_found_cfm = capture.as_found_cfm
    if capture.final_cfm is not None and device.final_cfm is None:
        device.final_cfm = capture.final_cfm
    if capture.design_cfm is not None and device.design_cfm is None:
        device.design_cfm = capture.design_cfm
    if capture.notes:
        device.notes = capture.notes if not device.notes else device.notes + " | " + capture.notes
    return True
