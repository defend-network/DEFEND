"""SCS TAB master workbook catalog.

Owner-approved PRIMARY masters (immutable; verified SHA-256 in
C:\\SCS_DATA\\masters\\audit.json / masters.sha256.json):
- Field_Report_Master.xlsm           -> canonical FIELD REPORT structure
  (cover, certification, exec summary, instrument calibration, equipment
  register, per-equipment test sheets, static pressure profile, air
  distribution, duct traverse, photo log, final closeout).
- Test and Balance MASTER TEMPLATE 001.xlsx -> canonical TAB TEST DATA
  sheets (traverse summary + point grids, VAV data, building pressurization
  summary, fan/AHU/coil/heat-pump test sheets).

PLANNER SOURCE POLICY: generated reports compose from BOTH masters above;
the legacy workbooks below remain cataloged for provenance only
(quality_reference=False) and are never used as composition sources.

Masters are IMMUTABLE: generated reports copy from these files and never
write to them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class MasterSheet:
    workbook: str
    sheet: str
    purpose: str
    equipment_type: str
    repeatability: str
    required_fields: tuple[str, ...] = ()
    optional_fields: tuple[str, ...] = ()
    formula_cells: tuple[str, ...] = ()
    merged_cell_count: int = 0
    print_orientation: str | None = None


@dataclass(frozen=True)
class MasterWorkbook:
    filename: str
    source_path: str
    description: str
    quality_reference: bool
    sheets: tuple[MasterSheet, ...] = ()


MASTER_WORKBOOKS: tuple[MasterWorkbook, ...] = (
    MasterWorkbook(
        filename="Field_Report_Master.xlsm",
        source_path=(
            r"C:\Users\thoma\OneDrive\Documents\SunshineClimateSolutions"
            r"\MasterWorkbooks\Field_Report_Master.xlsm"
        ),
        description=(
            "Owner-approved PRIMARY field report master (SCS-branded, "
            "numbered report sheets 01-33). Canonical for cover, certification, "
            "executive summary, instrument calibration, equipment register, "
            "per-equipment test sheets, static pressure profile, air "
            "distribution, duct traverse, photo log, deficiencies and final "
            "closeout. Contains VBA (xl/vbaProject.bin); composer reads it "
            "with keep_vba=False and never executes macros."
        ),
        quality_reference=True,
        sheets=(
            MasterSheet(
                "Field_Report_Master.xlsm", "02_Cover",
                "Report cover (date/client/site/job/contractor/type/prepared)",
                "general", "once",
                required_fields=("report_date", "project_client", "service_site",
                                 "job_po_wo", "hiring_contractor"),
                merged_cell_count=0,
            ),
            MasterSheet(
                "Field_Report_Master.xlsm", "03_Executive_Summary",
                "Executive summary, KPI results and priority recommendations",
                "general", "once",
                required_fields=("overall_result", "systems_tested"),
                merged_cell_count=0,
            ),
            MasterSheet(
                "Field_Report_Master.xlsm", "04_Certification",
                "Certification & report acceptance", "general", "once",
                required_fields=("certification_statement", "signatures"),
                merged_cell_count=0,
            ),
            MasterSheet(
                "Field_Report_Master.xlsm", "05_Instrument_Calibration",
                "Instrument register with calibration due-date formulas",
                "general", "once",
                required_fields=("instrument_id", "last_calibration", "due_date"),
                formula_cells=("K16", "L16", "K17", "L17", "K18", "L18"),
                merged_cell_count=0,
            ),
            MasterSheet(
                "Field_Report_Master.xlsm", "06_Abbreviations",
                "Terminology glossary (3 paired columns)", "general", "once",
                merged_cell_count=0,
            ),
            MasterSheet(
                "Field_Report_Master.xlsm", "07_Equipment_Register",
                "Project equipment register (row-per-unit: id/type/area/"
                "manufacturer/model/serial/capacity/voltage/refrigerant)",
                "general", "row per equipment instance",
                required_fields=("equipment_id", "type", "manufacturer"),
                optional_fields=("model", "serial", "area_served"),
                merged_cell_count=0,
            ),
            MasterSheet(
                "Field_Report_Master.xlsm", "12_Fan_Blower",
                "Fan / blower / motor test sheet (performance + drive "
                "inspection + sign-off)", "FAN", "whole sheet per fan instance",
                required_fields=("fan_unit_id", "fan_type", "manufacturer",
                                 "model", "airflow_cfm", "fan_rpm"),
                optional_fields=("voltage", "amps_l1", "amps_l2", "amps_l3",
                                 "motor_rpm", "motor_hp_bhp", "power_factor",
                                 "rotation", "tesp", "vfd_frequency"),
                formula_cells=("D18", "D19", "D20", "D21", "D22", "D23",
                               "D24", "D25", "J18", "J19", "J20", "J21",
                               "J22", "J23", "J24", "J25"),
                merged_cell_count=0,
            ),
            MasterSheet(
                "Field_Report_Master.xlsm", "19_Static_Pressure_Profile",
                "Static pressure profile points (A..I) with calculated "
                "pressure-drop summary", "AHU", "whole sheet per system",
                required_fields=("system_unit", "design_airflow", "points"),
                formula_cells=("C30", "C31", "C32", "C33", "C34", "C35", "C36"),
                merged_cell_count=0,
            ),
            MasterSheet(
                "Field_Report_Master.xlsm", "20_Air_Distribution",
                "Air distribution / outlet balance table (design/prelim/final "
                "FPM+CFM per device)", "general", "row block per device",
                required_fields=("area_served", "device_id", "final_cfm"),
                formula_cells=("L17", "M17"),
                merged_cell_count=0,
            ),
            MasterSheet(
                "Field_Report_Master.xlsm", "22_Duct_Traverse",
                "Duct velocity traverse report (10-point grid + design/test "
                "block)", "traverse", "whole sheet per traverse",
                required_fields=("system_unit", "location_zone", "points",
                                 "duct_size"),
                formula_cells=(),
                merged_cell_count=0,
            ),
            MasterSheet(
                "Field_Report_Master.xlsm", "31_Photo_Log",
                "Photo evidence register (photo id/date/equipment/view/"
                "description/file ref)", "general", "row per photo",
                required_fields=("photo_id", "description"),
                merged_cell_count=0,
            ),
            MasterSheet(
                "Field_Report_Master.xlsm", "32_Final_Closeout",
                "Final closeout status + required documents matrix + open "
                "items", "general", "once",
                required_fields=("overall_result", "systems_complete"),
                merged_cell_count=0,
            ),
            MasterSheet(
                "Field_Report_Master.xlsm", "33_VFD_Report",
                "VFD setup / specs report (nameplate + functional test + "
                "sign-off)", "VFD", "whole sheet per VFD instance",
                required_fields=("vfd_drive_id", "equipment_served",
                                 "vfd_manufacturer"),
                optional_fields=("input_voltage", "output_voltage",
                                 "drive_hp_kw", "min_frequency",
                                 "max_frequency", "command_source",
                                 "motor_voltage", "motor_fla", "amps_l1",
                                 "amps_l2", "amps_l3", "motor_rotation"),
                formula_cells=("D18", "D19", "D20", "D21", "D22", "D23",
                               "D24", "D25", "J18", "J19", "J20", "J21",
                               "J22", "J23", "I23", "I24"),
                merged_cell_count=0,
            ),
        ),
    ),
    MasterWorkbook(
        filename="Test and Balance MASTER TEMPLATE 001.xlsx",
        source_path=(
            r"C:\Users\thoma\OneDrive\Documents\SunshineClimateSolutions"
            r"\Test and Balance MASTER TEMPLATE 001.xlsx"
        ),
        description=(
            "Owner-approved PRIMARY TAB test-data master: industry-standard "
            "balancing test sheets (traverse summary + point grids, VAV data, "
            "building pressurization summary, fan/AHU/coil/heat-pump/chiller "
            "test sheets). No macros. Used for all TAB test-data sections."
        ),
        quality_reference=True,
        sheets=(
            MasterSheet(
                "Test and Balance MASTER TEMPLATE 001.xlsx", "Duct Traverse Summary SP",
                "Traverse summary grid (design/prelim/final CFM + SP)",
                "traverse", "row block 11..32 per traverse",
                required_fields=("duct_location", "instrument", "duct_size",
                                 "area_sqft", "design_fpm", "final_fpm"),
                formula_cells=("I11", "K11", "I12", "K12"),
                merged_cell_count=0,
                print_orientation="portrait",
            ),
            MasterSheet(
                "Test and Balance MASTER TEMPLATE 001.xlsx", "Duct Traverse ",
                "Per-traverse 10-point FPM grid + design/test block",
                "traverse", "row block 11..17 per traverse",
                required_fields=("system", "location", "points", "duct_size"),
                merged_cell_count=0,
                print_orientation="portrait",
            ),
            MasterSheet(
                "Test and Balance MASTER TEMPLATE 001.xlsx", "VAV Data",
                "VAV balance grid (address/box/size/correction/design CFM/"
                "test CFM)", "VAV", "row block 11..43 per VAV instance",
                required_fields=("box_number", "design_min", "design_max"),
                optional_fields=("address_number", "size", "correction_factor",
                                 "final_min", "final_max", "notes"),
                merged_cell_count=0,
                print_orientation="portrait",
            ),
            MasterSheet(
                "Test and Balance MASTER TEMPLATE 001.xlsx", "Bldg Press Summary",
                "Building pressurization summary (outside air / exhaust "
                "design + test CFM per system)", "RTU",
                "row block 12..35 per system",
                required_fields=("system", "outside_air_cfm", "exhaust_cfm"),
                merged_cell_count=0,
                print_orientation="portrait",
            ),
        ),
    ),
    MasterWorkbook(
        filename="SCS-CrunchFitness.xlsx",
        source_path=r"CRUNCH_FITNESS_LAKELAND.xlsx",
        description=(
            "LEGACY (provenance only; no longer a composition source). "
            "Complete real-world SCS TAB package (8 RTUs + building pressure). "
            "Superseded by Field_Report_Master.xlsm + Test and Balance MASTER "
            "TEMPLATE 001.xlsx per owner directive."
        ),
        quality_reference=False,
        sheets=(
            MasterSheet(
                "SCS-CrunchFitness.xlsx", "02_Cover", "Report cover", "general",
                "once",
                required_fields=("report_date", "project_client", "service_site"),
                merged_cell_count=18,
            ),
            MasterSheet(
                "SCS-CrunchFitness.xlsx", "03_Executive_Summary",
                "Executive summary & recommendations", "general", "once",
                required_fields=(
                    "overall_result", "systems_tested", "finding_rows",
                ),
                merged_cell_count=58,
            ),
            MasterSheet(
                "SCS-CrunchFitness.xlsx", "04_Certification",
                "Certification & report acceptance", "general", "once",
                required_fields=("certification_statement", "signatures"),
                merged_cell_count=41,
            ),
            MasterSheet(
                "SCS-CrunchFitness.xlsx", "RTU_Data_Tags_Units",
                "RTU nameplate & data tags (column-per-unit table)",
                "RTU", "column block B..H per unit",
                required_fields=(
                    "equipment_id", "manufacturer", "model", "serial", "unit_type",
                    "area_served", "refrigerant",
                ),
                optional_fields=(
                    "nominal_tons", "cooling_capacity", "heat_type",
                    "heat_capacity", "factory_charge", "manufacture_date",
                    "voltage", "phase", "frequency", "mca", "mocp", "rla", "lra",
                    "compressor", "metering_device", "supply_fan", "outdoor_fan",
                ),
                formula_cells=(),
                merged_cell_count=42,
            ),
            MasterSheet(
                "SCS-CrunchFitness.xlsx", "Building_Pressurization",
                "Building pressurization & airflow balance (row-per-device)",
                "RTU", "row block 17..26 per device",
                required_fields=(
                    "air_function", "design_cfm", "final_cfm", "measurement_method",
                    "status",
                ),
                optional_fields=(
                    "area_served", "as_found_cfm", "size", "avg_velocity_fpm",
                    "damper_control", "notes",
                ),
                formula_cells=(
                    "G17", "G18", "G19", "G20", "G21", "G22", "G23", "G24",
                    "G25", "G26",
                ),
                merged_cell_count=46,
            ),
        ),
    ),
    MasterWorkbook(
        filename="SCS-Gatorade-Report.xlsm",
        source_path=r"GatoradeWarehouse\GatoradeWarehoueReport.xlsm",
        description=(
            "LEGACY (provenance only; no longer a composition source). "
            "SCS-branded fan/blower/VFD/closeout package (SF-06, EF-08). "
            "Superseded by Field_Report_Master.xlsm per owner directive."
        ),
        quality_reference=False,
        sheets=(
            MasterSheet(
                "SCS-Gatorade-Report.xlsm", "02_Cover",
                "Report cover with job/PO/report-type block", "general", "once",
                required_fields=("report_date", "project_client", "service_site",
                                 "hiring_contractor", "prepared_by"),
                merged_cell_count=18,
            ),
            MasterSheet(
                "SCS-Gatorade-Report.xlsm", "04_Certification",
                "Certification & report acceptance", "general", "once",
                required_fields=("certification_statement", "signatures"),
                merged_cell_count=39,
            ),
            MasterSheet(
                "SCS-Gatorade-Report.xlsm", "06_Abbreviations",
                "Terminology glossary (3 paired columns)", "general", "once",
                merged_cell_count=1,
            ),
            MasterSheet(
                "SCS-Gatorade-Report.xlsm", "12_Fan_Blower (SF)",
                "Fan / blower / motor test report (per-fan sheet)", "FAN",
                "whole sheet per fan instance",
                required_fields=(
                    "fan_unit_id", "fan_type", "manufacturer", "model",
                    "airflow_cfm", "fan_rpm", "voltage", "amps",
                ),
                optional_fields=(
                    "tesp", "vfd_frequency", "damper_position",
                    "sound_vibration", "belt_sheave", "motor_data",
                ),
                formula_cells=("J18", "J19", "J20", "J21", "J22"),
                merged_cell_count=50,
            ),
            MasterSheet(
                "SCS-Gatorade-Report.xlsm", "12_Fan_Blower (EF)",
                "Fan / blower / motor test report, exhaust variant", "FAN",
                "whole sheet per fan instance",
                formula_cells=("J18", "J19", "J20", "J21", "J22", "J23"),
                merged_cell_count=50,
            ),
            MasterSheet(
                "SCS-Gatorade-Report.xlsm", "33_VFD_Report(SF)",
                "VFD setup / specs report (per-drive sheet)", "VFD",
                "whole sheet per VFD instance",
                required_fields=(
                    "vfd_id", "equipment_served", "vfd_manufacturer",
                    "input_voltage", "output_voltage", "drive_hp",
                ),
                optional_fields=(
                    "min_frequency", "max_frequency", "command_source",
                    "motor_voltage", "motor_fla", "amps", "average_amps",
                ),
                formula_cells=(
                    "D18", "D19", "D21", "D22", "D23", "J18", "J19", "J20",
                    "J21", "J22", "J23", "I23", "I24",
                ),
                merged_cell_count=48,
            ),
            MasterSheet(
                "SCS-Gatorade-Report.xlsm", "32_Final_Closeout",
                "Final report closeout & acceptance matrix", "general", "once",
                required_fields=("overall_result", "systems_complete"),
                optional_fields=("open_items", "closeout_documents"),
                merged_cell_count=48,
            ),
        ),
    ),
    MasterWorkbook(
        filename="SCS-LakePanasoffkee-Traverse.xlsx",
        source_path=r"Lake Panasoffkee Elementary\Lake Panasoffkee Elementary.xlsx",
        description=(
            "LEGACY (provenance only; no longer a composition source). "
            "Real duct traverse work (OAU-1/OAU-2). Superseded by Test and "
            "Balance MASTER TEMPLATE 001.xlsx per owner directive."
        ),
        quality_reference=False,
        sheets=(
            MasterSheet(
                "SCS-LakePanasoffkee-Traverse.xlsx", "Duct Traverse Summary SP",
                "Traverse summary grid (design/prelim/final CFM)", "traverse",
                "row block 11..32 per traverse",
                required_fields=(
                    "duct_location", "instrument", "duct_size", "area_sqft",
                    "design_fpm", "final_fpm",
                ),
                formula_cells=("I11", "K11", "I12", "K12"),
                merged_cell_count=20,
                print_orientation="portrait",
            ),
            MasterSheet(
                "SCS-LakePanasoffkee-Traverse.xlsx", "Duct Traverse ",
                "Per-traverse 10-point FPM grid + design/test block",
                "traverse", "row block 8..26 per traverse",
                required_fields=("system", "location", "points", "duct_size"),
                merged_cell_count=34,
                print_orientation="portrait",
            ),
        ),
    ),
    MasterWorkbook(
        filename="SCS-Roland-VAV.xlsx",
        source_path=r"Roland Magnet K-8\Roland Magnet K-8.xlsx",
        description=(
            "LEGACY (provenance only; no longer a composition source). "
            "Real VAV balancing grid. Superseded by Test and Balance MASTER "
            "TEMPLATE 001.xlsx per owner directive."
        ),
        quality_reference=False,
        sheets=(
            MasterSheet(
                "SCS-Roland-VAV.xlsx", "VAV Data",
                "VAV min/max CFM grid", "VAV",
                "row block 11..43 per VAV instance",
                required_fields=("box_number", "design_min", "design_max"),
                optional_fields=(
                    "address_number", "size", "correction_factor",
                    "prelim_min", "prelim_max", "final_min", "final_max", "notes",
                ),
                merged_cell_count=12,
                print_orientation="portrait",
            ),
        ),
    ),
    MasterWorkbook(
        filename="SCS-BP-RTU-Data-Only.xlsx",
        source_path=r"SCS_Building_Pressurization_and_8_RTU_Data_Only.xlsx",
        description=(
            "LEGACY data-only variant (empty values). Not a composition "
            "source; superseded by the owner-approved masters."
        ),
        quality_reference=False,
        sheets=(
            MasterSheet(
                "SCS-BP-RTU-Data-Only.xlsx", "34_Building_Pressurization",
                "Building pressurization (empty)", "RTU",
                "row block per device", merged_cell_count=51,
            ),
            MasterSheet(
                "SCS-BP-RTU-Data-Only.xlsx", "35_RTU_Nameplate_Data",
                "RTU nameplate (empty)", "RTU",
                "column block per unit", merged_cell_count=23,
            ),
        ),
    ),
)


def master_path(masters_dir: Path, filename: str) -> Path:
    return masters_dir / filename


def find_sheet(filename: str, sheet: str) -> MasterSheet | None:
    for workbook in MASTER_WORKBOOKS:
        if workbook.filename != filename:
            continue
        for candidate in workbook.sheets:
            if candidate.sheet == sheet:
                return candidate
    return None