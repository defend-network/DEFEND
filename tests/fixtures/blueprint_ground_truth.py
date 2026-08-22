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


# ---------------------------------------------------------------------------
# M1.2 enriched mechanical set ground truth (build_blueprint_m12)
# ---------------------------------------------------------------------------

M12_EXPECTED_SHEETS = {
    1: ("M0.1", "COVER"),
    2: ("M1.1", "MECHANICAL_GENERAL_NOTES"),
    3: ("M2.1", "AIR_DEVICE_SCHEDULE"),
    4: ("M2.2", "EQUIPMENT_SCHEDULE"),
    5: ("M3.1", "MECHANICAL_PLAN"),
    6: ("M3.2", "MECHANICAL_PLAN"),
    7: ("M0.2", "MECHANICAL_LEGEND"),
    8: ("E1.1", "ELECTRICAL"),
    9: ("M7.1", "DETAIL"),
}

M12_EXPECTED_EQUIPMENT = {
    "RTU-5": {"manufacturer": "GREENHECK", "model": "SQ-30",
              "supply_cfm": 1180.0, "oa_cfm": 620.0, "esp": 0.5,
              "fan_rpm": 1130.0, "motor_hp": 5.0, "vfd": "YES",
              "volts": 208, "phase": 3, "refrigerant": "R-410A",
              "remarks": "SERVES WORKOUT STUDIO A"},
    "RTU-6": {"manufacturer": "GREENHECK", "model": "SQ-30",
              "supply_cfm": 1240.0, "oa_cfm": 650.0, "esp": 0.5,
              "fan_rpm": 1150.0, "motor_hp": 5.0, "vfd": "YES",
              "volts": 208, "phase": 3, "refrigerant": "R-410A",
              "remarks": "SERVES WORKOUT STUDIO B"},
}

M12_EXPECTED_DEVICES = {
    # Studio A supply (DD types)
    "SA-1": {"room": "WORKOUT STUDIO A", "cfm": 180.0, "size": "8x8", "function": "SUPPLY"},
    "SA-2": {"room": "WORKOUT STUDIO A", "cfm": 180.0, "size": "8x8", "function": "SUPPLY"},
    "SA-3": {"room": "WORKOUT STUDIO A", "cfm": 200.0, "size": "10x10", "function": "SUPPLY"},
    "SA-4": {"room": "WORKOUT STUDIO A", "cfm": 200.0, "size": "10x10", "function": "SUPPLY"},
    "SA-5": {"room": "WORKOUT STUDIO A", "cfm": 210.0, "size": "10x10", "function": "SUPPLY"},
    "SA-6": {"room": "WORKOUT STUDIO A", "cfm": 210.0, "size": "10x10", "function": "SUPPLY"},
    "RA-1": {"room": "WORKOUT STUDIO A", "cfm": 600.0, "size": "24x12", "function": "RETURN"},
    "EF-1": {"room": "WORKOUT STUDIO A", "cfm": 120.0, "size": "8x8", "function": "EXHAUST"},
    # Studio B supply
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

M12_EXPECTED_DAMPERS = {
    "BD-1": "BALANCING_DAMPER", "BD-2": "BALANCING_DAMPER", "BD-3": "BALANCING_DAMPER",
    "BD-4": "BALANCING_DAMPER", "BD-5": "BALANCING_DAMPER",
    "FD-1": "FIRE_DAMPER", "FSD-1": "COMBINATION_FIRE_SMOKE_DAMPER",
    "SMD-1": "SMOKE_DAMPER", "MD-1": "MOTORIZED_DAMPER",
}

M12_EXPECTED_CONTROLS = {
    "T-5": "THERMOSTAT", "DSD-1": "DUCT_SMOKE_DETECTOR",
    "SP-1": "STATIC_PRESSURE_SENSOR", "CO2-1": "CO2_SENSOR",
}

M12_EXPECTED_DUCTS = {"18x12", "12x8", "14x14"}
M12_EXPECTED_REFERENCES = {"3/M7.1": True, "5/M7.2": False}
M12_EXPECTED_AIRDEVICE_COLUMNS = {
    "TAG", "TYPE", "SERVICE", "NECK SIZE", "FACE SIZE", "DESIGN CFM",
    "NC", "THROW", "DAMPER", "REMARKS",
}
M12_EXPECTED_EQUIPMENT_COLUMNS = {
    "TAG", "TYPE", "MFR", "MODEL", "SUPPLY CFM", "OA CFM", "ESP", "FAN RPM",
    "MOTOR", "HPVFD", "VOLTS", "PH", "REFRIG", "REMARKS",
}
