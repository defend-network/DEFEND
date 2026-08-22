"""Ground truth for the SANITIZED synthetic blueprint fixture.

Used by tools/blueprint_benchmark.py and tests/test_scs_blueprint_intelligence.py.
Contains no customer data.
"""
from __future__ import annotations

EXPECTED_SHEETS = {
    1: ("M0.1", "COVER"),
    2: ("M1.1", "MECHANICAL_GENERAL_NOTES"),
    3: ("M2.1", "AIR_DEVICE_SCHEDULE"),
    4: ("M2.2", "EQUIPMENT_SCHEDULE"),
    5: ("M3.1", "MECHANICAL_PLAN"),
    6: ("M3.2", "MECHANICAL_PLAN"),
    7: ("E1.1", "ELECTRICAL"),
}

EXPECTED_EQUIPMENT = {
    "RTU-5": {"manufacturer": "GREENHECK", "supply_cfm": 1180.0},
    "RTU-6": {"manufacturer": "GREENHECK", "supply_cfm": 1240.0},
}

EXPECTED_DEVICES = {
    # studio A supply
    "SA-1": {"room": "WORKOUT STUDIO A", "cfm": 180.0, "size": "8x8", "function": "SUPPLY"},
    "SA-2": {"room": "WORKOUT STUDIO A", "cfm": 180.0, "size": "8x8", "function": "SUPPLY"},
    "SA-3": {"room": "WORKOUT STUDIO A", "cfm": 200.0, "size": "10x10", "function": "SUPPLY"},
    "SA-4": {"room": "WORKOUT STUDIO A", "cfm": 200.0, "size": "10x10", "function": "SUPPLY"},
    "SA-5": {"room": "WORKOUT STUDIO A", "cfm": 210.0, "size": "10x10", "function": "SUPPLY"},
    "SA-6": {"room": "WORKOUT STUDIO A", "cfm": 210.0, "size": "10x10", "function": "SUPPLY"},
    # studio A return / exhaust
    "RA-1": {"room": "WORKOUT STUDIO A", "cfm": 600.0, "size": "24x12", "function": "RETURN"},
    "EF-1": {"room": "WORKOUT STUDIO A", "cfm": 120.0, "size": "8x8", "function": "EXHAUST"},
    # studio B supply
    "SA-7": {"room": "WORKOUT STUDIO B", "cfm": 180.0, "size": "8x8", "function": "SUPPLY"},
    "SA-8": {"room": "WORKOUT STUDIO B", "cfm": 180.0, "size": "8x8", "function": "SUPPLY"},
    "SA-9": {"room": "WORKOUT STUDIO B", "cfm": 180.0, "size": "8x8", "function": "SUPPLY"},
    "SA-10": {"room": "WORKOUT STUDIO B", "cfm": 180.0, "size": "8x8", "function": "SUPPLY"},
    "SA-11": {"room": "WORKOUT STUDIO B", "cfm": 190.0, "size": "10x10", "function": "SUPPLY"},
    "SA-12": {"room": "WORKOUT STUDIO B", "cfm": 165.0, "size": "10x10", "function": "SUPPLY"},
    "SA-13": {"room": "WORKOUT STUDIO B", "cfm": 165.0, "size": "10x10", "function": "SUPPLY"},
    "RA-2": {"room": "WORKOUT STUDIO B", "cfm": 650.0, "size": "24x12", "function": "RETURN"},
    "EF-2": {"room": "WORKOUT STUDIO B", "cfm": 120.0, "size": "8x8", "function": "EXHAUST"},
}

EXPECTED_SUPPLY_TOTALS = {
    "WORKOUT STUDIO A": {"cfm": 1180.0, "count": 6},
    "WORKOUT STUDIO B": {"cfm": 1240.0, "count": 7},
}
