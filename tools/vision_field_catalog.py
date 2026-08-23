"""SCS_REPORT_FIELD_CATALOG_V1 — canonical catalog of report-driven fields.

Source of truth: the owner-approved master workbooks
  * Field_Report_Master.xlsm        (37 sheets, SCS-* forms)
  * Test and Balance MASTER TEMPLATE 001.xlsx   (82 sheets)
as scanned by tools/master_workbook_fields.py -> C:\\SCS_DATA\\masters\\field_scan.json
(real sheet names / labels are referenced in DESTINATION_SHEETS).

The catalog tells the vision/report system what information matters:

  FIELD_ID            canonical identifier used everywhere
  DISPLAY_NAME        human label
  DATA_TYPE           NUMBER | STRING | DATE | ENUM | CODE | BOOL
  UNIT                canonical unit
  APPLIES_TO[]        photo types / equipment classes that can carry the field
  SOURCE_TYPES[]      allowed provenance classes (never blend rated vs measured)
  DESTINATION_SHEETS[] report destinations {workbook, sheet, form, section, cell_concept}
  REQUIRED_WHEN[]     conditions under which the field is required
  VALIDATION_RULE     sanity check (range / pattern)
  NORMALIZATION_RULE  canonicalization applied to raw evidence
  SECTION             UI group: IDENTITY | RATINGS | ELECTRICAL | MOTOR_FAN |
                      REFRIGERATION | MEASUREMENTS | OTHER_VISIBLE_DATA

PHOTO_TYPE_SCHEMAS: expected-field catalogs per photo/object class. Absent
fields on a photo are marked ABSENT/NOT_VISIBLE, never invented.

Every report value keeps a source classification (SOURCE_CLASSES); rated data
(PHOTO_OCR/PHOTO_VLM/PHOTO_CONFIRMED/MANUFACTURER_DOCUMENT) is never blended
with measured field data (TECH_ENTERED/INSTRUMENT_ENTERED).

EQUIPMENT_RECORD_SCHEMA reserves the canonical equipment record extension
points for the future manufacturer-intelligence layer (nomenclature, manuals,
bulletins, recalls, wiring diagrams, product data) so no schema rewrite is
needed later.
"""

from __future__ import annotations

from typing import Any

# --------------------------------------------------------------------------
# Source classes (provenance). Rated data vs measured data never blend.
# --------------------------------------------------------------------------

SOURCE_CLASSES = (
    "PHOTO_OCR",
    "PHOTO_VLM",
    "PHOTO_CONFIRMED",
    "TECH_ENTERED",
    "INSTRUMENT_ENTERED",
    "PLAN_DERIVED",
    "MANUFACTURER_DOCUMENT",
    "CALCULATED",
    "FORMULA",
    "UNKNOWN",
)

RATED_SOURCES = ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED", "MANUFACTURER_DOCUMENT")
MEASURED_SOURCES = ("TECH_ENTERED", "INSTRUMENT_ENTERED", "CALCULATED", "FORMULA")

# --------------------------------------------------------------------------
# UI sections
# --------------------------------------------------------------------------

FIELD_SECTIONS = (
    "IDENTITY",
    "RATINGS",
    "ELECTRICAL",
    "MOTOR_FAN",
    "REFRIGERATION",
    "MEASUREMENTS",
    "OTHER_VISIBLE_DATA",
)

# --------------------------------------------------------------------------
# Workbook destinations (from master_workbook_fields.py scan)
# --------------------------------------------------------------------------

FRM = "Field_Report_Master.xlsm"          # SCS field report master
TAB = "Test and Balance MASTER TEMPLATE 001.xlsx"   # NEBB-style TAB template


def _dest(sheet: str, form: str, section: str, concept: str, workbook: str = FRM) -> dict:
    return {"workbook": workbook, "sheet": sheet, "form": form,
            "section": section, "cell_concept": concept}


EQ_REG = _dest("07_Equipment_Register", "SCS-EQ-001", "EQUIPMENT SCHEDULE", "equipment register row")
AHU = _dest("08_AHU_Furnace", "SCS-AHU-001", "EQUIPMENT IDENTIFICATION", "unit data block")
ODU = _dest("09_Outdoor_Unit_HP", "SCS-ODU-001", "EQUIPMENT IDENTIFICATION", "unit data block")
FAN = _dest("12_Fan_Blower", "SCS-FAN-001", "FAN & DRIVE IDENTIFICATION", "fan/motor data block")
VFD = _dest("33_VFD_Report", "SCS-VFD-001", "VFD NAMEPLATE / SETUP DATA", "nameplate block")
REF = _dest("17_Refrigerant_Diagnostics", "SCS-REF-001", "SYSTEM / TEST CONDITIONS", "refrigerant data block")
ELEC = _dest("18_Electrical_Diagnostics", "SCS-ELEC-001", "SYSTEM / CIRCUIT IDENTIFICATION", "circuit data block")
FLT = _dest("23_Filter_Airflow", "SCS-FLT-001", "FILTER BANK IDENTIFICATION", "filter data block")
CAL = _dest("05_Instrument_Calibration", "SCS-CAL-001", "INSTRUMENT REGISTER", "instrument row")
TAB_AH = _dest("Air Handler", "TAB Air Handler", "MOTOR DATA", "motor row", TAB)
TAB_FAN = _dest("Fan Test  ", "TAB Fan Test", "TEST DATA", "fan row", TAB)
TAB_CAL = _dest("Instrument Calibration 6 ", "TAB Instrument Calibration", "HVAC TAB INSTRUMENTS", "instrument row", TAB)
TAB_VAV = _dest("VAV Data", "TAB VAV Data", "VAV DATA", "box row", TAB)
TAB_PUMP = _dest("Pump Test", "TAB Pump Test", "MOTOR DATA", "motor row", TAB)
TAB_SP = _dest("Static Pressure Profile", "TAB Static Pressure Profile", "STATIC PRESSURE PROFILE", "profile point", TAB)
TAB_DT = _dest("Duct Traverse  ", "TAB Duct Traverse", "DUCT TRAVERSE", "traverse row", TAB)
TAB_TEMP = _dest("Temperature Summary Sheet", "TAB Temperature Summary", "TEMPERATURE SUMMARY", "room row", TAB)
TAB_VENT = _dest("Ventilation Test Sheet", "TAB Ventilation Test", "VENTILATION TEST", "system row", TAB)
TAB_BLDG = _dest("Bldg Press Summary", "TAB Bldg Press Summary", "BUILDING PRESSURIZATION", "system row", TAB)
TAB_COIL = _dest("Cooling Coil Test 31", "TAB Cooling Coil", "COIL DATA", "coil row", TAB)
TAB_HEATPUMP = _dest("Heat Pump Test", "TAB Heat Pump", "UNIT DATA", "unit row", TAB)

# --------------------------------------------------------------------------
# Field definitions
# --------------------------------------------------------------------------
# Each row: FIELD_ID, DISPLAY_NAME, DATA_TYPE, UNIT, APPLIES_TO (photo types),
#           SOURCE_TYPES, DESTINATIONS, REQUIRED_WHEN, VALIDATION, NORMALIZATION, SECTION
# APPLIES_TO / DESTINATIONS use shorthand: set of photo-type ids / dest refs.

NP = "NAMEPLATE"
ALL_NAME_PLATES = (
    "RTU_NAMEPLATE", "AHU_NAMEPLATE", "CONDENSING_UNIT_NAMEPLATE", "HEAT_PUMP_NAMEPLATE",
    "FURNACE_NAMEPLATE", "COMPRESSOR_NAMEPLATE", "MOTOR_NAMEPLATE", "FAN_NAMEPLATE",
    "VFD_NAMEPLATE", NP,
)
ALL_PLATES_AND_EQUIP = ALL_NAME_PLATES + (
    "VAV_CONTROLLER", "VAV_BOX", "THERMOSTAT", "ELECTRICAL_PANEL", "DISCONNECT",
    "STARTER", "CONTACTOR", "TRANSFORMER", "MOTOR", "FILTER", "COIL", "GENERAL_EQUIPMENT",
)
INSTRUMENTS = (
    "AIRFLOW_INSTRUMENT", "MICROMANOMETER", "PRESSURE_READING", "TEMPERATURE_READING",
    "TEMP_RH_READING", "AMP_READING", "VOLTAGE_READING", "RPM_READING", "INSTRUMENT_READING",
)
AIR = ("DUCTWORK", "AIR_DEVICE", "OA_INTAKE", "EXHAUST", "BUILDING_PRESSURE", "TRAVERSE")

_FIELDS: list[tuple] = [
    # ---- IDENTITY ---------------------------------------------------------
    ("photo_type", "Photo type", "ENUM", "",
     ALL_PLATES_AND_EQUIP + INSTRUMENTS + AIR, ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"),
     (EQ_REG, AHU, ODU, FAN, VFD), ("required",),
     "one of catalog photo types", "uppercase canonical", "IDENTITY"),
    ("manufacturer", "Manufacturer", "STRING", "",
     ALL_PLATES_AND_EQUIP + INSTRUMENTS + AIR, ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED", "MANUFACTURER_DOCUMENT"),
     (EQ_REG, AHU, ODU, FAN, VFD, CAL, TAB_AH, TAB_FAN, TAB_HEATPUMP, TAB_PUMP),
     ("required", "when plate/equipment visible"), "known manufacturer list; no cert agencies", "uppercase canonical name", "IDENTITY"),
    ("model", "Model", "STRING", "",
     ALL_PLATES_AND_EQUIP, ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED", "MANUFACTURER_DOCUMENT"),
     (EQ_REG, AHU, ODU, FAN, VFD, CAL, TAB_AH, TAB_FAN, TAB_PUMP),
     ("required", "when plate visible"), "model-token shape; not stopword/electrical", "uppercase, no spaces", "IDENTITY"),
    ("serial", "Serial number", "STRING", "",
     ALL_PLATES_AND_EQUIP, ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED", "MANUFACTURER_DOCUMENT"),
     (EQ_REG, AHU, ODU, FAN, VFD, TAB_AH, TAB_FAN, TAB_PUMP),
     ("required", "when plate visible"), "not electrical spec / address / literal", "uppercase, trim", "IDENTITY"),
    ("part_number", "Part number", "STRING", "",
     ("MOTOR_NAMEPLATE", "FAN_NAMEPLATE", "VFD_NAMEPLATE", "COMPRESSOR_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (FAN, VFD, EQ_REG),
     ("when shown",), "part-like token (P/N, 5-1000)", "uppercase, trim", "IDENTITY"),
    ("bom_number", "BOM number", "STRING", "",
     ("MOTOR_NAMEPLATE", "FAN_NAMEPLATE", "VFD_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (FAN, VFD, EQ_REG),
     ("when shown",), "BOM-prefixed code", "uppercase, trim", "IDENTITY"),
    ("manufacture_date", "Manufacture date", "DATE", "",
     ALL_NAME_PLATES + ("MOTOR", "FILTER", "COIL"), ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"),
     (EQ_REG, AHU, ODU), ("when shown",), "date-like token", "ISO YYYY-MM-DD when resolvable", "IDENTITY"),
    ("country_of_origin", "Country of origin", "STRING", "",
     ALL_NAME_PLATES + ("MOTOR", "VFD_NAMEPLATE"), ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"),
     (EQ_REG,), ("when shown",), "MADE IN + country", "uppercase country name", "IDENTITY"),
    ("approval_codes", "Approval / certification codes", "STRING", "",
     ALL_NAME_PLATES + ("MOTOR",), ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"),
     (EQ_REG, AHU, ODU), ("when shown",), "cUL/UL/CSA/CE/ETL/EAC pattern", "uppercase, keep separators", "OTHER_VISIBLE_DATA"),
    ("equipment_type", "Equipment type", "ENUM", "",
     ALL_PLATES_AND_EQUIP, ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"),
     (EQ_REG, AHU, ODU, FAN, VFD), ("required",), "component != equipment type", "canonical equipment family", "IDENTITY"),
    ("equipment_tag", "Equipment tag", "CODE", "",
     ALL_PLATES_AND_EQUIP + AIR, ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED", "TECH_ENTERED", "PLAN_DERIVED"),
     (EQ_REG, AHU, ODU, FAN, VFD), ("when shown", "or plan-derived"),
     "RTU-1 pattern", "uppercase, normalize dash", "IDENTITY"),
    # ---- RATINGS (capacity / performance) --------------------------------
    ("nominal_tonnage", "Nominal tonnage", "NUMBER", "TON",
     ("RTU_NAMEPLATE", "CONDENSING_UNIT_NAMEPLATE", "HEAT_PUMP_NAMEPLATE", "AHU_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (EQ_REG, ODU, AHU, TAB_HEATPUMP),
     ("when shown",), "0.5-200 TON", "round to 0.25", "RATINGS"),
    ("rated_airflow", "Rated airflow", "NUMBER", "CFM",
     ("RTU_NAMEPLATE", "AHU_NAMEPLATE", "FAN_NAMEPLATE", "FURNACE_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (AHU, FAN, TAB_AH),
     ("when shown",), "100-200000 CFM", "integer", "RATINGS"),
    ("efficiency_rating", "Efficiency rating", "STRING", "",
     ("RTU_NAMEPLATE", "AHU_NAMEPLATE", "CONDENSING_UNIT_NAMEPLATE", "HEAT_PUMP_NAMEPLATE", "FURNACE_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (EQ_REG, AHU, ODU),
     ("when shown",), "SEER/EER/IEER/AFUE pattern", "uppercase, keep value+rating type", "RATINGS"),
    ("heating_type", "Heating type", "ENUM", "",
     ("RTU_NAMEPLATE", "AHU_NAMEPLATE", "FURNACE_NAMEPLATE", "HEAT_PUMP_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (AHU, ODU, EQ_REG),
     ("when shown",), "GAS/ELECTRIC/HEAT PUMP/HYDRO/OTHER", "uppercase", "RATINGS"),
    ("electric_heat_kw", "Electric heat kW", "NUMBER", "KW",
     ("RTU_NAMEPLATE", "AHU_NAMEPLATE", "FURNACE_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (AHU, EQ_REG),
     ("when shown",), "0.5-500 KW", "number", "RATINGS"),
    ("gas_input", "Gas input", "NUMBER", "BTUH",
     ("RTU_NAMEPLATE", "FURNACE_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (AHU, EQ_REG),
     ("when shown",), "10000-5000000 BTUH", "number", "RATINGS"),
    ("gas_output", "Gas output", "NUMBER", "BTUH",
     ("RTU_NAMEPLATE", "FURNACE_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (AHU, EQ_REG),
     ("when shown",), "10000-5000000 BTUH", "number", "RATINGS"),
    ("design_pressures", "Design pressures", "STRING", "PSIG",
     ("RTU_NAMEPLATE", "CONDENSING_UNIT_NAMEPLATE", "HEAT_PUMP_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (ODU, REF, TAB_HEATPUMP),
     ("when shown",), "high/low pressure pattern", "keep pair, uppercase", "REFRIGERATION"),
    # ---- ELECTRICAL -------------------------------------------------------
    ("voltage", "Voltage", "NUMBER", "V",
     ALL_PLATES_AND_EQUIP + INSTRUMENTS, ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED", "MANUFACTURER_DOCUMENT"),
     (EQ_REG, AHU, ODU, FAN, VFD, ELEC, TAB_AH, TAB_FAN, TAB_PUMP),
     ("required", "when electrical rating shown"), "110-600 V typical", "canonical voltage value", "ELECTRICAL"),
    ("phase", "Phase", "NUMBER", "",
     ALL_PLATES_AND_EQUIP + INSTRUMENTS, ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED", "MANUFACTURER_DOCUMENT"),
     (EQ_REG, AHU, ODU, FAN, VFD, ELEC, TAB_AH, TAB_FAN, TAB_PUMP),
     ("required", "when electrical rating shown"), "1 or 3", "integer 1|3", "ELECTRICAL"),
    ("frequency_hz", "Frequency", "NUMBER", "HZ",
     ALL_PLATES_AND_EQUIP + INSTRUMENTS, ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED", "MANUFACTURER_DOCUMENT"),
     (FAN, VFD, ELEC, TAB_AH, TAB_FAN), ("when shown",), "50/60", "integer", "ELECTRICAL"),
    ("fla", "FLA", "NUMBER", "A",
     ("MOTOR_NAMEPLATE", "FAN_NAMEPLATE", "RTU_NAMEPLATE", "AHU_NAMEPLATE", "CONDENSING_UNIT_NAMEPLATE",
      "HEAT_PUMP_NAMEPLATE", "COMPRESSOR_NAMEPLATE", "VFD_NAMEPLATE", "MOTOR", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (FAN, VFD, ELEC, TAB_AH, TAB_FAN, TAB_PUMP),
     ("when shown",), "0.1-1000 A", "decimal", "ELECTRICAL"),
    ("rla", "RLA", "NUMBER", "A",
     ("RTU_NAMEPLATE", "CONDENSING_UNIT_NAMEPLATE", "HEAT_PUMP_NAMEPLATE", "COMPRESSOR_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (ODU, REF, ELEC),
     ("when shown",), "0.1-1000 A", "decimal", "ELECTRICAL"),
    ("lra", "LRA", "NUMBER", "A",
     ("RTU_NAMEPLATE", "CONDENSING_UNIT_NAMEPLATE", "HEAT_PUMP_NAMEPLATE", "COMPRESSOR_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (ODU, REF, ELEC),
     ("when shown",), "1-1000 A", "decimal", "ELECTRICAL"),
    ("amps", "Current rating / amps", "NUMBER", "A",
     ("MOTOR_NAMEPLATE", "FAN_NAMEPLATE", "VFD_NAMEPLATE", "ELECTRICAL_PANEL", "DISCONNECT",
      "STARTER", "CONTACTOR", "TRANSFORMER", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (ELEC, FAN, VFD, TAB_AH, TAB_FAN),
     ("when shown",), "0.1-1000 A", "decimal", "ELECTRICAL"),
    ("mca", "MCA", "NUMBER", "A",
     ("RTU_NAMEPLATE", "AHU_NAMEPLATE", "CONDENSING_UNIT_NAMEPLATE", "HEAT_PUMP_NAMEPLATE", "FURNACE_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (ODU, ELEC, EQ_REG),
     ("when shown",), "1-1000 A", "decimal", "ELECTRICAL"),
    ("mocp", "MOCP", "NUMBER", "A",
     ("RTU_NAMEPLATE", "AHU_NAMEPLATE", "CONDENSING_UNIT_NAMEPLATE", "HEAT_PUMP_NAMEPLATE", "FURNACE_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (ODU, ELEC, EQ_REG),
     ("when shown",), "1-2000 A", "decimal", "ELECTRICAL"),
    ("max_fuse", "Max fuse", "NUMBER", "A",
     ("RTU_NAMEPLATE", "AHU_NAMEPLATE", "CONDENSING_UNIT_NAMEPLATE", "HEAT_PUMP_NAMEPLATE", "FURNACE_NAMEPLATE",
      "ELECTRICAL_PANEL", "DISCONNECT", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (ELEC, ODU),
     ("when shown",), "1-2000 A", "decimal", "ELECTRICAL"),
    ("min_fuse", "Min fuse", "NUMBER", "A",
     ("RTU_NAMEPLATE", "AHU_NAMEPLATE", "CONDENSING_UNIT_NAMEPLATE", "HEAT_PUMP_NAMEPLATE", "FURNACE_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (ELEC, ODU),
     ("when shown",), "1-2000 A", "decimal", "ELECTRICAL"),
    ("capacitor_mfd", "Capacitor rating", "NUMBER", "MFD",
     ("MOTOR_NAMEPLATE", "FAN_NAMEPLATE", "COMPRESSOR_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (ELEC,),
     ("when shown",), "0.5-100 MFD", "decimal", "ELECTRICAL"),
    ("capacitor_voltage", "Capacitor voltage", "NUMBER", "VAC",
     ("MOTOR_NAMEPLATE", "FAN_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (ELEC,),
     ("when shown",), "50-600 VAC", "decimal", "ELECTRICAL"),
    ("transformer_va", "Transformer rating", "NUMBER", "VA",
     ("TRANSFORMER", "ELECTRICAL_PANEL", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (ELEC,),
     ("when shown",), "10-10000 VA", "decimal", "ELECTRICAL"),
    ("wiring_config", "Wiring / lead configuration", "STRING", "",
     ("MOTOR_NAMEPLATE", "FAN_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (TAB_AH, TAB_FAN),
     ("when shown",), "lead count / delta-wye pattern", "uppercase, trim", "OTHER_VISIBLE_DATA"),
    # ---- MOTOR / FAN ------------------------------------------------------
    ("horsepower", "Horsepower", "NUMBER", "HP",
     ("MOTOR_NAMEPLATE", "FAN_NAMEPLATE", "RTU_NAMEPLATE", "AHU_NAMEPLATE", "MOTOR", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (FAN, VFD, TAB_AH, TAB_FAN, TAB_PUMP, EQ_REG),
     ("required", "when motor rating shown"), "0.01-1000 HP", "decimal", "MOTOR_FAN"),
    ("rpm", "RPM", "NUMBER", "RPM",
     ("MOTOR_NAMEPLATE", "FAN_NAMEPLATE", "MOTOR", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (FAN, TAB_AH, TAB_FAN, TAB_PUMP, EQ_REG),
     ("when shown",), "100-10000 RPM", "integer", "MOTOR_FAN"),
    ("rotation", "Rotation", "ENUM", "",
     ("MOTOR_NAMEPLATE", "FAN_NAMEPLATE", "MOTOR", "VFD_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED", "TECH_ENTERED"), (FAN, VFD, TAB_AH, TAB_FAN),
     ("when shown",), "CW/CCW/REV", "uppercase", "MOTOR_FAN"),
    ("service_factor", "Service factor", "NUMBER", "",
     ("MOTOR_NAMEPLATE", "FAN_NAMEPLATE", "MOTOR", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (TAB_AH, TAB_FAN, TAB_PUMP),
     ("when shown",), "0.5-2.5", "decimal 2dp", "MOTOR_FAN"),
    ("insulation_class", "Insulation class", "ENUM", "",
     ("MOTOR_NAMEPLATE", "FAN_NAMEPLATE", "MOTOR", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (TAB_AH, TAB_FAN, TAB_PUMP),
     ("when shown",), "A/B/F/H", "uppercase", "MOTOR_FAN"),
    ("duty", "Duty", "ENUM", "",
     ("MOTOR_NAMEPLATE", "FAN_NAMEPLATE", "MOTOR", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (TAB_AH, TAB_FAN),
     ("when shown",), "CONT/S1/S3 pattern", "uppercase", "MOTOR_FAN"),
    ("frame", "Frame", "CODE", "",
     ("MOTOR_NAMEPLATE", "FAN_NAMEPLATE", "MOTOR", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (TAB_AH, TAB_FAN, TAB_PUMP),
     ("required", "when motor rating shown"), "NEMA frame pattern (56C, 143T...)", "uppercase", "MOTOR_FAN"),
    ("enclosure_type", "Enclosure type", "ENUM", "",
     ("MOTOR_NAMEPLATE", "FAN_NAMEPLATE", "MOTOR", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (TAB_AH, TAB_FAN, TAB_PUMP),
     ("when shown",), "TEFC/ODP/TENV/XP pattern", "uppercase", "MOTOR_FAN"),
    ("bearings", "Bearing information", "STRING", "",
     ("MOTOR_NAMEPLATE", "FAN_NAMEPLATE", "MOTOR", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (TAB_AH, TAB_FAN),
     ("when shown",), "bearing number pattern", "uppercase, trim", "MOTOR_FAN"),
    ("motor_type", "Motor type", "STRING", "",
     ("MOTOR_NAMEPLATE", "FAN_NAMEPLATE", "MOTOR", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (TAB_AH, TAB_FAN),
     ("when shown",), "PSC/ECM/3-phase...", "uppercase", "MOTOR_FAN"),
    ("indoor_fan_motor_hp", "Indoor fan motor HP", "NUMBER", "HP",
     ("RTU_NAMEPLATE", "AHU_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (AHU, TAB_AH),
     ("when shown",), "0.01-100 HP", "decimal", "MOTOR_FAN"),
    ("indoor_fan_motor_fla", "Indoor fan motor FLA", "NUMBER", "A",
     ("RTU_NAMEPLATE", "AHU_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (AHU, TAB_AH),
     ("when shown",), "0.1-100 A", "decimal", "MOTOR_FAN"),
    ("outdoor_fan_motor_hp", "Outdoor fan motor HP", "NUMBER", "HP",
     ("RTU_NAMEPLATE", "CONDENSING_UNIT_NAMEPLATE", "HEAT_PUMP_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (ODU,),
     ("when shown",), "0.01-100 HP", "decimal", "MOTOR_FAN"),
    ("outdoor_fan_motor_fla", "Outdoor fan motor FLA", "NUMBER", "A",
     ("RTU_NAMEPLATE", "CONDENSING_UNIT_NAMEPLATE", "HEAT_PUMP_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (ODU,),
     ("when shown",), "0.1-100 A", "decimal", "MOTOR_FAN"),
    ("belt_sheave", "Belt / sheave data", "STRING", "",
     ("FAN_NAMEPLATE", "FAN", "MOTOR", "PULLEY_SHEAVE", "BELT", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED", "TECH_ENTERED"), (FAN, TAB_AH, TAB_FAN),
     ("when shown",), "belt/sheave code", "uppercase, trim", "MOTOR_FAN"),
    # ---- REFRIGERATION ----------------------------------------------------
    ("refrigerant", "Refrigerant", "ENUM", "",
     ("RTU_NAMEPLATE", "CONDENSING_UNIT_NAMEPLATE", "HEAT_PUMP_NAMEPLATE", "COMPRESSOR_NAMEPLATE",
      "FURNACE_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (EQ_REG, ODU, REF, AHU),
     ("required", "when refrigeration equipment"), "R-410A/454B/32/22/134A/404A/407C", "canonical R-code", "REFRIGERATION"),
    ("factory_charge", "Factory charge", "NUMBER", "LB",
     ("RTU_NAMEPLATE", "CONDENSING_UNIT_NAMEPLATE", "HEAT_PUMP_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (ODU, REF),
     ("when shown",), "0.1-200 LB", "decimal", "REFRIGERATION"),
    ("compressor_count", "Compressor count", "NUMBER", "",
     ("RTU_NAMEPLATE", "CONDENSING_UNIT_NAMEPLATE", "HEAT_PUMP_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (EQ_REG, ODU),
     ("when shown",), "1-8", "integer", "REFRIGERATION"),
    ("compressor_rla", "Compressor RLA", "NUMBER", "A",
     ("RTU_NAMEPLATE", "CONDENSING_UNIT_NAMEPLATE", "HEAT_PUMP_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (ODU, REF, ELEC),
     ("when shown",), "0.1-1000 A", "decimal", "REFRIGERATION"),
    ("compressor_lra", "Compressor LRA", "NUMBER", "A",
     ("RTU_NAMEPLATE", "CONDENSING_UNIT_NAMEPLATE", "HEAT_PUMP_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (ODU, REF, ELEC),
     ("when shown",), "1-1000 A", "decimal", "REFRIGERATION"),
    ("metering_device", "Metering device", "ENUM", "",
     ("RTU_NAMEPLATE", "CONDENSING_UNIT_NAMEPLATE", "HEAT_PUMP_NAMEPLATE", "AHU_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (AHU, ODU, REF),
     ("when shown",), "TXV/EXV/CAP TUBE/ORIFICE", "uppercase", "REFRIGERATION"),
    ("compressor_model", "Compressor model", "STRING", "",
     ("RTU_NAMEPLATE", "CONDENSING_UNIT_NAMEPLATE", "HEAT_PUMP_NAMEPLATE", "COMPRESSOR_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (REF, ELEC, EQ_REG),
     ("when shown",), "compressor plate model", "uppercase, trim", "REFRIGERATION"),
    # ---- MEASUREMENTS (field/test values; never blended with rated) -------
    ("measurement_type", "Measurement type", "ENUM", "",
     INSTRUMENTS, ("PHOTO_VLM", "PHOTO_CONFIRMED", "TECH_ENTERED", "INSTRUMENT_ENTERED"),
     (CAL, TAB_AH, TAB_FAN, TAB_TEMP, TAB_VENT, TAB_BLDG, TAB_DT),
     ("required", "for instrument photos"), "CFM/FPM/IN_WC/PA/TEMP/RH/RPM/AMPS/VOLTS/HZ/ENTHALPY",
     "canonical measurement type", "MEASUREMENTS"),
    ("value", "Value", "NUMBER", "",
     INSTRUMENTS + AIR, ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED", "TECH_ENTERED", "INSTRUMENT_ENTERED"),
     (TAB_AH, TAB_FAN, TAB_TEMP, TAB_VENT, TAB_BLDG, TAB_DT, TAB_SP, TAB_COIL, TAB_PUMP),
     ("required", "when measurement visible"), "preserve exact displayed precision", "preserve raw precision", "MEASUREMENTS"),
    ("unit", "Unit", "ENUM", "",
     INSTRUMENTS + AIR, ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED", "TECH_ENTERED", "INSTRUMENT_ENTERED"),
     (TAB_AH, TAB_FAN, TAB_TEMP, TAB_VENT, TAB_BLDG, TAB_DT),
     ("required", "when measurement visible"), "CFM/FPM/IN_WC/PA/F/RH/%/A/V/Hz", "canonical unit", "MEASUREMENTS"),
    ("channel", "Channel / probe", "STRING", "",
     INSTRUMENTS, ("PHOTO_VLM", "PHOTO_CONFIRMED", "TECH_ENTERED", "INSTRUMENT_ENTERED"),
     (CAL, TAB_DT), ("when identifiable",), "probe/channel id", "trim", "MEASUREMENTS"),
    ("timestamp_visible", "Timestamp (display)", "DATE", "",
     INSTRUMENTS, ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (TAB_TEMP, TAB_AH),
     ("when shown",), "time/date on display", "ISO when resolvable", "MEASUREMENTS"),
    ("instrument_type", "Instrument type", "ENUM", "",
     INSTRUMENTS, ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (CAL, TAB_CAL),
     ("required", "for instrument photos"), "tachometer/manometer/meter/psychrometer...", "uppercase", "MEASUREMENTS"),
    ("instrument_make", "Instrument make", "STRING", "",
     INSTRUMENTS, ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (CAL, TAB_CAL),
     ("when shown",), "brand on instrument", "uppercase", "MEASUREMENTS"),
    ("instrument_model", "Instrument model", "STRING", "",
     INSTRUMENTS, ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (CAL, TAB_CAL),
     ("when shown",), "model on instrument", "uppercase, trim", "MEASUREMENTS"),
    ("supply_air_cfm", "Supply air CFM", "NUMBER", "CFM",
     ("DUCTWORK", "AIR_DEVICE", "TRAVERSE", "GENERAL_EQUIPMENT"),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED", "TECH_ENTERED", "INSTRUMENT_ENTERED", "CALCULATED"),
     (TAB_AH, TAB_FAN, TAB_DT, TAB_VAV), ("when shown", "or computed"), "100-200000 CFM", "integer", "MEASUREMENTS"),
    ("outside_air_cfm", "Outside air CFM", "NUMBER", "CFM",
     ("DUCTWORK", "OA_INTAKE", "TRAVERSE", "GENERAL_EQUIPMENT"),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED", "TECH_ENTERED", "INSTRUMENT_ENTERED", "CALCULATED"),
     (AHU, TAB_VENT, TAB_BLDG), ("when shown", "or computed"), "100-200000 CFM", "integer", "MEASUREMENTS"),
    ("exhaust_cfm", "Exhaust CFM", "NUMBER", "CFM",
     ("DUCTWORK", "EXHAUST", "GENERAL_EQUIPMENT"),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED", "TECH_ENTERED", "INSTRUMENT_ENTERED", "CALCULATED"),
     (TAB_VENT, TAB_BLDG), ("when shown", "or computed"), "100-200000 CFM", "integer", "MEASUREMENTS"),
    ("air_velocity_fpm", "Air velocity", "NUMBER", "FPM",
     ("DUCTWORK", "AIR_DEVICE", "TRAVERSE", "GENERAL_EQUIPMENT"),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED", "TECH_ENTERED", "INSTRUMENT_ENTERED"),
     (TAB_DT, FLT), ("when shown",), "0-20000 FPM", "integer", "MEASUREMENTS"),
    ("static_pressure", "Static pressure", "NUMBER", "IN_WC",
     ("DUCTWORK", "BUILDING_PRESSURE", "GENERAL_EQUIPMENT", "AIR_DEVICE"),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED", "TECH_ENTERED", "INSTRUMENT_ENTERED"),
     (AHU, TAB_SP, TAB_BLDG, FAN), ("when shown",), "-20..+20 IN_WC", "decimal", "MEASUREMENTS"),
    ("temperature", "Temperature", "NUMBER", "F",
     ("TEMPERATURE_READING", "TEMP_RH_READING", "INSTRUMENT_READING", "AIR", "GENERAL_EQUIPMENT"),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED", "TECH_ENTERED", "INSTRUMENT_ENTERED"),
     (TAB_TEMP, TAB_AH, TAB_COIL, TAB_SP), ("when shown",), "-40..250 F", "decimal", "MEASUREMENTS"),
    ("rh", "Relative humidity", "NUMBER", "%",
     ("TEMP_RH_READING", "INSTRUMENT_READING", "GENERAL_EQUIPMENT"),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED", "TECH_ENTERED", "INSTRUMENT_ENTERED"),
     (TAB_TEMP, TAB_AH), ("when shown",), "0-100 %", "decimal", "MEASUREMENTS"),
    ("current_a", "Current", "NUMBER", "A",
     ("AMP_READING", "INSTRUMENT_READING", "GENERAL_EQUIPMENT"),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED", "TECH_ENTERED", "INSTRUMENT_ENTERED"),
     (ELEC, FAN, TAB_FAN), ("when shown",), "0.0-1000 A", "decimal", "MEASUREMENTS"),
    ("voltage_a", "Voltage (measured)", "NUMBER", "V",
     ("VOLTAGE_READING", "INSTRUMENT_READING", "GENERAL_EQUIPMENT"),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED", "TECH_ENTERED", "INSTRUMENT_ENTERED"),
     (ELEC, TAB_FAN), ("when shown",), "0-1000 V", "decimal", "MEASUREMENTS"),
    ("rpm_measured", "RPM (measured)", "NUMBER", "RPM",
     ("RPM_READING", "INSTRUMENT_READING", "GENERAL_EQUIPMENT"),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED", "TECH_ENTERED", "INSTRUMENT_ENTERED"),
     (TAB_AH, TAB_FAN, TAB_PUMP), ("when shown",), "0-10000 RPM", "integer", "MEASUREMENTS"),
    ("fan_rpm", "Fan RPM", "NUMBER", "RPM",
     ("DUCTWORK", "GENERAL_EQUIPMENT", "FAN"),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED", "TECH_ENTERED", "INSTRUMENT_ENTERED"),
     (AHU, FAN, TAB_AH, TAB_FAN), ("when shown",), "0-10000 RPM", "integer", "MEASUREMENTS"),
    # ---- VFD / CONTROL ----------------------------------------------------
    ("input_voltage", "Input voltage", "NUMBER", "V",
     ("VFD_NAMEPLATE", "VAV_CONTROLLER", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (VFD,),
     ("when shown",), "110-600 V", "decimal", "ELECTRICAL"),
    ("output_voltage", "Output voltage", "NUMBER", "V",
     ("VFD_NAMEPLATE", NP), ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (VFD,),
     ("when shown",), "110-600 V", "decimal", "ELECTRICAL"),
    ("rated_amps", "Drive rated amps", "NUMBER", "A",
     ("VFD_NAMEPLATE", NP), ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (VFD,),
     ("when shown",), "0.1-1000 A", "decimal", "ELECTRICAL"),
    ("rated_hp", "Drive rated HP", "NUMBER", "HP",
     ("VFD_NAMEPLATE", NP), ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (VFD,),
     ("when shown",), "0.01-1000 HP", "decimal", "MOTOR_FAN"),
    ("min_frequency", "Min frequency", "NUMBER", "HZ",
     ("VFD_NAMEPLATE", NP), ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (VFD,),
     ("when shown",), "0-60 HZ", "decimal", "ELECTRICAL"),
    ("max_frequency", "Max frequency", "NUMBER", "HZ",
     ("VFD_NAMEPLATE", NP), ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (VFD,),
     ("when shown",), "0-600 HZ", "decimal", "ELECTRICAL"),
    ("actual_frequency_hz", "Actual frequency", "NUMBER", "HZ",
     ("VFD_NAMEPLATE", "INSTRUMENT_READING", "GENERAL_EQUIPMENT"),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED", "TECH_ENTERED", "INSTRUMENT_ENTERED"), (VFD,),
     ("when shown",), "0-600 HZ", "decimal", "MEASUREMENTS"),
    ("actual_speed_rpm", "Actual speed", "NUMBER", "RPM",
     ("VFD_NAMEPLATE", "INSTRUMENT_READING", "GENERAL_EQUIPMENT"),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED", "TECH_ENTERED", "INSTRUMENT_ENTERED"), (VFD,),
     ("when shown",), "0-10000 RPM", "decimal", "MEASUREMENTS"),
    ("actual_current", "Actual current", "NUMBER", "A",
     ("VFD_NAMEPLATE", "INSTRUMENT_READING", "GENERAL_EQUIPMENT"),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED", "TECH_ENTERED", "INSTRUMENT_ENTERED"), (VFD,),
     ("when shown",), "0-1000 A", "decimal", "MEASUREMENTS"),
    ("command_source", "Command source", "STRING", "",
     ("VFD_NAMEPLATE", "VAV_CONTROLLER", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (VFD,), ("when shown",),
     "HAND/LOCAL/AUTO/REMOTE/BACnet/4-20mA", "uppercase", "OTHER_VISIBLE_DATA"),
    ("run_status", "Run status", "ENUM", "",
     ("VFD_NAMEPLATE", "INSTRUMENT_READING"),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED", "TECH_ENTERED"), (VFD,),
     ("when shown",), "RUN/STOP/FAULT", "uppercase", "MEASUREMENTS"),
    ("fault_code", "Fault code", "STRING", "",
     ("VFD_NAMEPLATE", "INSTRUMENT_READING"),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED", "TECH_ENTERED"), (VFD,),
     ("when shown",), "drive fault code", "uppercase, trim", "MEASUREMENTS"),
    # ---- FILTER / COIL ----------------------------------------------------
    ("filter_type", "Filter type / MERV", "STRING", "",
     ("FILTER", "RTU_NAMEPLATE", "AHU_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (FLT, AHU, EQ_REG),
     ("when shown",), "MERV/pleat type pattern", "uppercase", "RATINGS"),
    ("filter_size", "Filter size / quantity", "STRING", "",
     ("FILTER", "RTU_NAMEPLATE", "AHU_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (FLT, AHU),
     ("when shown",), "size pattern (e.g. 20x20x2)", "uppercase", "RATINGS"),
    ("coil_rows", "Coil rows", "NUMBER", "",
     ("COIL", "AHU_NAMEPLATE", NP), ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"),
     (TAB_COIL, AHU), ("when shown",), "1-12", "integer", "RATINGS"),
    ("coil_fins_per_inch", "Coil fins per inch", "NUMBER", "FPI",
     ("COIL", "AHU_NAMEPLATE", NP), ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"),
     (TAB_COIL, AHU), ("when shown",), "4-20", "integer", "RATINGS"),
    ("size", "Size", "STRING", "",
     ("VAV_BOX", "FILTER", "COIL", NP), ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"),
     (TAB_VAV, FLT, AHU), ("when shown",), "size pattern (e.g. 10x16, 20x20x2)", "uppercase, trim", "RATINGS"),
    # ---- ELECTRICAL (VFD input/output) -------------------------------------
    ("input_phase", "VFD input phase", "NUMBER", "",
     ("VFD_NAMEPLATE",), ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"),
     (VFD, ELEC), ("when shown",), "1 or 3", "integer 1|3", "ELECTRICAL"),
    ("input_hz", "VFD input frequency", "NUMBER", "HZ",
     ("VFD_NAMEPLATE",), ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"),
     (VFD,), ("when shown",), "50/60", "integer", "ELECTRICAL"),
    ("output_phase", "VFD output phase", "NUMBER", "",
     ("VFD_NAMEPLATE",), ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"),
     (VFD, ELEC), ("when shown",), "1 or 3", "integer 1|3", "ELECTRICAL"),
    ("output_hz", "VFD output frequency", "NUMBER", "HZ",
     ("VFD_NAMEPLATE",), ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"),
     (VFD,), ("when shown",), "0-400", "integer", "ELECTRICAL"),
    ("mode", "VFD operating mode", "ENUM", "",
     ("VFD_NAMEPLATE", "VAV_CONTROLLER", NP), ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED", "TECH_ENTERED"),
     (VFD,), ("when shown",), "HAND/OFF/AUTO/RUN pattern", "uppercase", "OTHER_VISIBLE_DATA"),
    # ---- MOTOR / FAN -------------------------------------------------------
    ("motor_rpm", "Motor RPM", "NUMBER", "RPM",
     ("RTU_NAMEPLATE", "CONDENSING_UNIT_NAMEPLATE", "HEAT_PUMP_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (FAN, VFD, EQ_REG),
     ("when shown",), "100-10000 RPM", "integer", "MOTOR_FAN"),
    ("motor_rotation", "Motor rotation", "ENUM", "",
     ("RTU_NAMEPLATE", "CONDENSING_UNIT_NAMEPLATE", "HEAT_PUMP_NAMEPLATE", NP),
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED"), (FAN, TAB_AH, TAB_FAN),
     ("when shown",), "CW/CCW/REV", "uppercase", "MOTOR_FAN"),
    # ---- OTHER VISIBLE DATA ------------------------------------------------
    ("visible_text", "Visible text (other)", "STRING", "",
     ALL_PLATES_AND_EQUIP + INSTRUMENTS + AIR,
     ("PHOTO_OCR", "PHOTO_VLM", "PHOTO_CONFIRMED", "TECH_ENTERED"),
     (AHU, ODU, FAN, VFD, REF), ("when other text exists",), "raw readable text", "preserve raw", "OTHER_VISIBLE_DATA"),
    ("notes", "Notes", "STRING", "",
     ALL_PLATES_AND_EQUIP + INSTRUMENTS + AIR,
     ("TECH_ENTERED", "PHOTO_CONFIRMED"), (), ("when needed",), "free text", "preserve", "OTHER_VISIBLE_DATA"),
]

FIELD_CATALOG_V1: dict[str, dict] = {}
for (fid, name, dtype, unit, applies, sources, dests, req, val, norm, section) in _FIELDS:
    FIELD_CATALOG_V1[fid] = {
        "FIELD_ID": fid,
        "DISPLAY_NAME": name,
        "DATA_TYPE": dtype,
        "UNIT": unit,
        "APPLIES_TO": sorted(applies),
        "SOURCE_TYPES": sorted(sources),
        "DESTINATION_SHEETS": dests,
        "REQUIRED_WHEN": list(req),
        "VALIDATION_RULE": val,
        "NORMALIZATION_RULE": norm,
        "SECTION": section,
    }

FIELD_SECTIONS_ORDER = FIELD_SECTIONS

# --------------------------------------------------------------------------
# Photo / equipment type schemas (expected-field catalogs)
# --------------------------------------------------------------------------

_ID = ["photo_type", "manufacturer", "model", "serial", "equipment_type", "equipment_tag"]
_MOTOR_CORE = ["part_number", "bom_number", "horsepower", "voltage", "phase", "frequency_hz",
               "fla", "rpm", "rotation", "service_factor", "frame", "insulation_class", "duty",
               "enclosure_type", "capacitor_mfd", "capacitor_voltage", "bearings", "wiring_config",
               "manufacture_date", "country_of_origin", "approval_codes"]
_RTU_EXTRA = ["nominal_tonnage", "refrigerant", "factory_charge", "mca", "mocp", "max_fuse",
              "min_fuse", "compressor_count", "compressor_rla", "compressor_lra",
              "indoor_fan_motor_hp", "indoor_fan_motor_fla", "outdoor_fan_motor_hp",
              "outdoor_fan_motor_fla", "motor_rpm", "motor_rotation", "heating_type",
              "electric_heat_kw", "gas_input", "gas_output", "design_pressures", "rated_airflow",
              "efficiency_rating", "metering_device", "compressor_model", "filter_type",
              "filter_size", "visible_text"]
_MEAS = ["measurement_type", "value", "unit", "channel", "timestamp_visible",
         "instrument_type", "instrument_make", "instrument_model", "visible_text"]

PHOTO_TYPE_SCHEMAS: dict[str, list[str]] = {
    "RTU_NAMEPLATE": _ID + _RTU_EXTRA + ["visible_text", "notes"],
    "AHU_NAMEPLATE": _ID + ["nominal_tonnage", "rated_airflow", "refrigerant", "mca", "mocp",
                            "max_fuse", "min_fuse", "indoor_fan_motor_hp", "indoor_fan_motor_fla",
                            "heating_type", "electric_heat_kw", "gas_input", "gas_output",
                            "design_pressures", "efficiency_rating", "metering_device",
                            "filter_type", "filter_size", "coil_rows", "coil_fins_per_inch",
                            "visible_text", "notes"],
    "CONDENSING_UNIT_NAMEPLATE": _ID + _RTU_EXTRA + ["visible_text", "notes"],
    "HEAT_PUMP_NAMEPLATE": _ID + _RTU_EXTRA + ["visible_text", "notes"],
    "FURNACE_NAMEPLATE": _ID + ["nominal_tonnage", "rated_airflow", "heating_type",
                                "electric_heat_kw", "gas_input", "gas_output", "voltage",
                                "phase", "frequency_hz", "mca", "mocp", "max_fuse", "min_fuse",
                                "indoor_fan_motor_hp", "indoor_fan_motor_fla", "filter_type",
                                "filter_size", "visible_text", "notes"],
    "COMPRESSOR_NAMEPLATE": _ID + ["compressor_model", "voltage", "phase", "frequency_hz",
                                   "rla", "lra", "amps", "horsepower", "rpm", "rotation",
                                   "refrigerant", "design_pressures", "manufacture_date",
                                   "country_of_origin", "approval_codes", "visible_text", "notes"],
    "MOTOR_NAMEPLATE": _ID + _MOTOR_CORE + ["motor_type", "visible_text", "notes"],
    "FAN_NAMEPLATE": _ID + _MOTOR_CORE + ["motor_type", "rated_airflow", "rpm", "belt_sheave",
                                          "visible_text", "notes"],
    "VFD_NAMEPLATE": _ID + ["input_voltage", "input_phase", "input_hz", "output_voltage",
                            "output_phase", "output_hz", "rated_amps", "rated_hp",
                            "min_frequency", "max_frequency", "actual_frequency_hz",
                            "actual_speed_rpm", "actual_current", "command_source", "run_status",
                            "fault_code", "mode", "rotation", "visible_text", "notes"],
    "VAV_CONTROLLER": ["manufacturer", "model", "serial", "equipment_tag", "input_voltage",
                       "voltage", "phase", "command_source", "visible_text", "notes"],
    "VAV_BOX": ["manufacturer", "model", "serial", "equipment_tag", "size", "rated_airflow",
                "visible_text", "notes"],
    "THERMOSTAT": ["manufacturer", "model", "serial", "equipment_tag", "temperature", "rh",
                   "visible_text", "notes"],
    "ELECTRICAL_PANEL": ["manufacturer", "model", "serial", "equipment_tag", "voltage", "phase",
                         "amps", "mca", "mocp", "max_fuse", "min_fuse", "transformer_va",
                         "visible_text", "notes"],
    "DISCONNECT": ["manufacturer", "model", "serial", "equipment_tag", "voltage", "phase",
                   "amps", "max_fuse", "min_fuse", "visible_text", "notes"],
    "STARTER": ["manufacturer", "model", "serial", "equipment_tag", "voltage", "phase", "amps",
                "mca", "mocp", "horsepower", "visible_text", "notes"],
    "CONTACTOR": ["manufacturer", "model", "serial", "voltage", "phase", "amps", "horsepower",
                  "visible_text", "notes"],
    "TRANSFORMER": ["manufacturer", "model", "serial", "voltage", "phase", "transformer_va",
                    "visible_text", "notes"],
    "MOTOR": ["manufacturer", "model", "serial", "equipment_tag", "part_number", "horsepower",
              "voltage", "phase", "frequency_hz", "fla", "rpm", "rotation", "service_factor",
              "frame", "insulation_class", "duty", "enclosure_type", "bearings", "visible_text",
              "notes"],
    "PULLEY_SHEAVE": ["manufacturer", "model", "equipment_tag", "belt_sheave", "visible_text",
                      "notes"],
    "BELT": ["manufacturer", "model", "equipment_tag", "belt_sheave", "visible_text", "notes"],
    "FILTER": ["manufacturer", "model", "equipment_tag", "filter_type", "filter_size",
               "visible_text", "notes"],
    "COIL": ["manufacturer", "model", "serial", "equipment_tag", "coil_rows",
             "coil_fins_per_inch", "rated_airflow", "visible_text", "notes"],
    "AIRFLOW_INSTRUMENT": ["instrument_type", "instrument_make", "instrument_model",
                           "measurement_type", "value", "unit", "channel", "visible_text",
                           "notes"],
    "MICROMANOMETER": ["instrument_type", "instrument_make", "instrument_model",
                       "measurement_type", "value", "unit", "channel", "visible_text", "notes"],
    "PRESSURE_READING": ["measurement_type", "value", "unit", "channel", "static_pressure",
                         "instrument_type", "visible_text", "notes"],
    "TEMPERATURE_READING": ["measurement_type", "value", "unit", "channel", "temperature",
                            "visible_text", "notes"],
    "TEMP_RH_READING": ["measurement_type", "value", "unit", "channel", "temperature", "rh",
                        "visible_text", "notes"],
    "AMP_READING": ["measurement_type", "value", "unit", "channel", "current_a", "voltage_a",
                    "visible_text", "notes"],
    "VOLTAGE_READING": ["measurement_type", "value", "unit", "channel", "voltage_a",
                        "visible_text", "notes"],
    "RPM_READING": ["measurement_type", "value", "unit", "channel", "rpm_measured",
                    "visible_text", "notes"],
    "DUCTWORK": ["equipment_tag", "supply_air_cfm", "outside_air_cfm", "exhaust_cfm",
                 "air_velocity_fpm", "static_pressure", "fan_rpm", "visible_text", "notes"],
    "AIR_DEVICE": ["equipment_tag", "supply_air_cfm", "air_velocity_fpm", "static_pressure",
                   "visible_text", "notes"],
    "OA_INTAKE": ["equipment_tag", "outside_air_cfm", "air_velocity_fpm", "static_pressure",
                  "visible_text", "notes"],
    "EXHAUST": ["equipment_tag", "exhaust_cfm", "air_velocity_fpm", "static_pressure",
                "visible_text", "notes"],
    "BUILDING_PRESSURE": ["equipment_tag", "static_pressure", "supply_air_cfm", "exhaust_cfm",
                          "visible_text", "notes"],
    "TRAVERSE": ["equipment_tag", "air_velocity_fpm", "supply_air_cfm", "static_pressure",
                 "measurement_type", "value", "unit", "visible_text", "notes"],
    "GENERAL_EQUIPMENT": _ID + ["visible_text", "notes"],
    "NAMEPLATE": _ID + _RTU_EXTRA + _MOTOR_CORE + ["visible_text", "notes"],
    "INSTRUMENT_READING": _MEAS + ["temperature", "rh", "current_a", "voltage_a", "rpm_measured",
                                   "fan_rpm", "static_pressure", "air_velocity_fpm", "notes"],
    "EQUIPMENT": _ID + ["visible_text", "notes"],
    "SYSTEM_STATIC": ["measurement_type", "value", "unit", "static_pressure", "visible_text",
                      "notes"],
    "OTHER": ["visible_text", "notes"],
}

# --------------------------------------------------------------------------
# Canonical photo-type resolution: VLM class + equipment family -> schema
# --------------------------------------------------------------------------

_EQUIP_TO_SCHEMA = {
    "RTU": "RTU_NAMEPLATE",
    "AHU": "AHU_NAMEPLATE",
    "FCU": "AHU_NAMEPLATE",
    "CONDENSING UNIT / OUTDOOR UNIT": "CONDENSING_UNIT_NAMEPLATE",
    "OUTDOOR UNIT": "CONDENSING_UNIT_NAMEPLATE",
    "HEAT PUMP": "HEAT_PUMP_NAMEPLATE",
    "FURNACE": "FURNACE_NAMEPLATE",
    "COMPRESSOR": "COMPRESSOR_NAMEPLATE",
    "MOTOR": "MOTOR_NAMEPLATE",
    "FAN": "FAN_NAMEPLATE",
    "VFD": "VFD_NAMEPLATE",
    "VAV": "VAV_BOX",
    "THERMOSTAT": "THERMOSTAT",
    "DISCONNECT": "DISCONNECT",
}


def canonical_photo_type(candidate_class: str | None,
                         equipment_type: str | None = None) -> str:
    """Resolve the VLM class + equipment family to a catalog photo-type schema."""
    cls = (candidate_class or "").upper().strip()
    equip = (equipment_type or "").upper()

    def family_schema(fam: str) -> str | None:
        for key, schema in _EQUIP_TO_SCHEMA.items():
            if key in fam:
                return schema
        return None

    if cls == "NAMEPLATE":
        return family_schema(equip) or "NAMEPLATE"
    if cls in ("INSTRUMENT_READING", "TEMP_RH_READING"):
        return cls
    if cls == "EQUIPMENT":
        return family_schema(equip) or "EQUIPMENT"
    for schema in PHOTO_TYPE_SCHEMAS:
        if cls == schema or cls.replace(" ", "").replace("/", "") == schema.replace("_", ""):
            return schema
    mapped = family_schema(cls)
    if mapped:
        return mapped
    return "OTHER"


# --------------------------------------------------------------------------
# Coverage report (MASTER_FIELDS_DISCOVERED / ... / FIELDS_TECHNICIAN_OBSERVED)
# --------------------------------------------------------------------------

# Field IDs that only exist in the report as technician/measured entries
TECH_ONLY_FIELDS = {
    "supply_air_cfm", "outside_air_cfm", "exhaust_cfm", "air_velocity_fpm",
    "static_pressure", "temperature", "rh", "current_a", "voltage_a", "rpm_measured",
    "fan_rpm", "actual_frequency_hz", "actual_speed_rpm", "actual_current",
    "run_status", "fault_code", "channel", "timestamp_visible", "notes",
}
# Field IDs produced by formulas/calculation (never photographed)
CALCULATED_FIELDS = {
    "supply_air_cfm", "outside_air_cfm", "exhaust_cfm", "air_velocity_fpm",
}
# Field IDs that typically come from drawings/plans rather than photos
PLAN_DERIVED_FIELDS = {"equipment_tag", "equipment_type"}


def report_field_coverage() -> dict:
    """Coverage of the catalog against the master workbooks."""
    master = set(FIELD_CATALOG_V1)
    vision_extractable = {
        fid for fid, f in FIELD_CATALOG_V1.items()
        if "PHOTO_OCR" in f["SOURCE_TYPES"] or "PHOTO_VLM" in f["SOURCE_TYPES"]
    }
    form_only = master - vision_extractable - CALCULATED_FIELDS - TECH_ONLY_FIELDS
    return {
        "MASTER_FIELDS_DISCOVERED": len(master),
        "FIELDS_VISION_EXTRACTABLE": len(vision_extractable),
        "FIELDS_FORM_ONLY": len(form_only),
        "FIELDS_CALCULATED": len(CALCULATED_FIELDS),
        "FIELDS_PLAN_DERIVED": len(PLAN_DERIVED_FIELDS),
        "FIELDS_TECHNICIAN_OBSERVED": len(TECH_ONLY_FIELDS),
        "PHOTO_TYPE_SCHEMAS": len(PHOTO_TYPE_SCHEMAS),
        "SOURCE_CLASSES": len(SOURCE_CLASSES),
        "SECTION_BREAKDOWN": {
            section: sum(1 for f in FIELD_CATALOG_V1.values() if f["SECTION"] == section)
            for section in FIELD_SECTIONS
        },
        "FORM_ONLY_FIELDS": sorted(form_only),
        "CALCULATED_FIELDS": sorted(CALCULATED_FIELDS),
        "PLAN_DERIVED_FIELDS": sorted(PLAN_DERIVED_FIELDS),
        "TECHNICIAN_OBSERVED_FIELDS": sorted(TECH_ONLY_FIELDS),
    }


def schema_fields(photo_type: str) -> list[str]:
    return list(PHOTO_TYPE_SCHEMAS.get(photo_type, PHOTO_TYPE_SCHEMAS["OTHER"]))


def section_of(field_id: str) -> str:
    return FIELD_CATALOG_V1.get(field_id, {}).get("SECTION", "OTHER_VISIBLE_DATA")


def field_def(field_id: str) -> dict:
    return FIELD_CATALOG_V1.get(field_id, {})


# --------------------------------------------------------------------------
# Canonical equipment record (future manufacturer-intelligence extension)
# --------------------------------------------------------------------------

EQUIPMENT_RECORD_SCHEMA = {
    "identity": ["manufacturer", "model", "serial", "part_number", "bom_number",
                 "equipment_type", "equipment_tag", "manufacture_date", "country_of_origin"],
    "ratings": ["nominal_tonnage", "voltage", "phase", "frequency_hz", "horsepower",
                "fla", "rla", "lra", "mca", "mocp", "refrigerant", "factory_charge"],
    "manufacturer_intelligence": {
        "model_nomenclature": {"url": None, "decoder": None, "decoded_options": []},
        "serial_nomenclature": {"url": None, "decoder": None, "decoded": None},
        "equipment_family": None,
        "documents": {
            "manuals": [],
            "service_bulletins": [],
            "technical_bulletins": [],
            "recalls": [],
            "wiring_diagrams": [],
            "product_data": [],
            "parts_breakdown": [],
        },
    },
    "source_trace": {"per_field_source": {}, "attachments": []},
}