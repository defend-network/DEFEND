"""SCS V1 TAB procedure library (M1.3, P22).

High-quality V1 procedures for the core TAB tasks. Every step carries
provenance; nothing is claimed as NEBB-specific unless an indexed standard
cites it (standard_citations stay explicit).
"""
from __future__ import annotations

from .models import ProcedureStep, SCSProcedure


def _steps(items: list[tuple[str, str, str]]) -> list[ProcedureStep]:
    return [ProcedureStep(step_id=sid, title=title, instruction=text,
                          provenance=prov) for sid, title, prov, text in [
        (sid, title, prov, text) for sid, title, prov, text in items
    ]]


def build_library() -> dict[str, SCSProcedure]:
    library: dict[str, SCSProcedure] = {}

    library["rtu_total_airflow"] = SCSProcedure(
        procedure_id="rtu_total_airflow", version="1.0",
        title="RTU total airflow verification",
        scope="Verify supply fan total airflow at a rooftop unit",
        equipment_classes=["RTU", "AHU"], system_types=["SUPPLY_AIR"],
        applicable_instruments=["micromanometer", "pitot", "velgrid"],
        required_inputs=["design_cfm", "duct_geometry"], required_preconditions=[
            "unit operating in full cooling/continuous fan mode",
            "filters and coils clean for baseline",
            "VFD at documented operating point (or 100% for belt units)"],
        required_readings=["traverse_fpm", "duct_dimensions", "fan_rpm", "tesp"],
        optional_readings=["supply_static", "return_static", "oa_cfm"],
        steps=_steps([
            ("s1", "Confirm operating mode", "Verify unit mode (cooling/heating/fan-only) and record. Provenance: SCS_PRACTICE", "SCS_PRACTICE"),
            ("s2", "Locate traverse plane", "Choose a straight duct section >= 5 diameters upstream / 2 downstream. Provenance: NEBB balance practice", "STANDARD_REQUIREMENT"),
            ("s3", "Measure duct geometry", "Record duct width x height (or diameter).", "SCS_PRACTICE"),
            ("s4", "Perform traverse", "Take a full velocity traverse (or VelGrid matrix) and record point values.", "STANDARD_REQUIREMENT"),
            ("s5", "Record fan speed", "Tachometer RPM; if VFD, record drive frequency + setpoint.", "SCS_PRACTICE"),
            ("s6", "Record static pressures", "Supply + return static to build TESP.", "SCS_PRACTICE"),
            ("s7", "Calculate airflow", "CFM = mean FPM x area (deterministic calculator).", "SCS_PRACTICE"),
            ("s8", "Compare to design", "Percent design; flag <90% or >110% for investigation.", "SCS_PRACTICE"),
        ]),
        decision_points=["airflow below 90% design?", "TESP high relative to OEM allowable?"],
        stop_conditions=["measurement unstable (flutter) - recheck traverse location",
                         "system in unoccupied/DCV mode that changes airflow"],
        safety_notes=["lock out rotating equipment before probing", "use only rated tubing/probes"],
        common_failure_modes=["bad traverse location", "duct dimension error", "mode/DCV changing airflow"],
        report_fields=["system_id", "fan_rpm", "tesp", "traverse_mean_fpm", "area", "airflow_cfm", "percent_design"],
        standard_citations=["NEBB TAB procedural standards (when indexed)"],
    )

    library["pitot_traverse"] = SCSProcedure(
        procedure_id="pitot_traverse", version="1.0",
        title="Pitot traverse",
        scope="Velocity traverse of a duct with a Pitot tube",
        equipment_classes=["DUCT"], system_types=["SUPPLY_AIR", "RETURN_AIR", "EXHAUST_AIR"],
        applicable_instruments=["pitot", "micromanometer"],
        required_inputs=["duct_geometry"], required_readings=["velocity_pressure_points"],
        steps=_steps([
            ("s1", "Check duct access", "Confirm enough straight duct and access points.", "SCS_PRACTICE"),
            ("s2", "Zero the micromanometer", "Zero with probe out of the airstream.", "SCS_PRACTICE"),
            ("s3", "Take points", "Record velocity pressure at each traverse point; orient Pitot into flow.", "STANDARD_REQUIREMENT"),
            ("s4", "Validate points", "Flag non-positive / wildly off points (state reason).", "SCS_PRACTICE"),
            ("s5", "Compute", "Mean VP -> velocity (4005 factor) -> CFM.", "SCS_PRACTICE"),
        ]),
        standard_citations=["NEBB/ASHRAE traverse point methodology (when indexed)"],
    )

    library["vav_max_verification"] = SCSProcedure(
        procedure_id="vav_max_verification", version="1.0",
        title="VAV maximum airflow verification",
        scope="Verify a VAV box reaches its design maximum",
        equipment_classes=["VAV"], system_types=["SUPPLY_AIR"],
        applicable_instruments=["micromanometer", "vav_controller"],
        required_inputs=["design_max_cfm", "box_k_factor_or_flow_sensor"],
        required_readings=["box_vp_or_flow", "upstream_static"],
        steps=_steps([
            ("s1", "Force box to max", "Command the box to full open / maximum cooling.", "SCS_PRACTICE"),
            ("s2", "Read flow", "Record controller flow and/or measured velocity pressure at the sensor.", "SCS_PRACTICE"),
            ("s3", "Compute CFM", "Use the controller/box K-factor formula (CFM = K sqrt(VP)); no universal constant.", "SCS_PRACTICE"),
            ("s4", "Compare to max", "Percent of design max; flag if not reached.", "SCS_PRACTICE"),
            ("s5", "Check pickup pressure", "Confirm upstream static sufficient for the box's required pickup.", "OEM_REQUIREMENT"),
        ]),
        oem_citations=["controller/box OEM IOM (when indexed)"],
    )

    library["vav_min_verification"] = SCSProcedure(
        procedure_id="vav_min_verification", version="1.0",
        title="VAV minimum airflow verification",
        scope="Verify a VAV box maintains its design minimum",
        equipment_classes=["VAV"], system_types=["SUPPLY_AIR"],
        applicable_instruments=["micromanometer", "vav_controller"],
        required_inputs=["design_min_cfm", "box_k_factor_or_flow_sensor"],
        required_readings=["box_vp_or_flow"],
        steps=_steps([
            ("s1", "Force box to min", "Command the box to minimum (closed position).", "SCS_PRACTICE"),
            ("s2", "Read flow", "Record controller flow / velocity pressure.", "SCS_PRACTICE"),
            ("s3", "Compute + compare", "Percent of design min.", "SCS_PRACTICE"),
        ]),
        oem_citations=["controller/box OEM IOM (when indexed)"],
    )

    library["outside_air_measurement"] = SCSProcedure(
        procedure_id="outside_air_measurement", version="1.0",
        title="Outside-air measurement",
        scope="Measure outdoor air intake airflow",
        equipment_classes=["RTU", "AHU", "DOAS", "MAU"],
        system_types=["OUTSIDE_AIR"], applicable_instruments=["velgrid", "pitot", "micromanometer"],
        required_inputs=["oa_duct_or_hood_geometry"],
        required_readings=["oa_velocity", "oa_temperature", "ra_temperature", "ma_temperature"],
        steps=_steps([
            ("s1", "Stabilize OA", "Set OA damper to documented minimum position.", "SCS_PRACTICE"),
            ("s2", "Measure OA velocity", "Traverse or VelGrid across the OA intake.", "STANDARD_REQUIREMENT"),
            ("s3", "Compute OA CFM", "Mean velocity x area.", "SCS_PRACTICE"),
            ("s4", "Cross-check by temperature", "OA fraction = (Tra-Tma)/(Tra-Toa) when valid.", "SCS_PRACTICE"),
            ("s5", "Compare to design", "OA design CFM / percent.", "SCS_PRACTICE"),
        ]),
    )

    library["building_pressure_test"] = SCSProcedure(
        procedure_id="building_pressure_test", version="1.0",
        title="Building pressure test",
        scope="Measure and evaluate building pressurization",
        equipment_classes=["RTU", "AHU", "EF"], system_types=["BUILDING_PRESSURE"],
        applicable_instruments=["micromanometer"],
        required_readings=["building_to_outdoor_pressure"],
        optional_readings=["supply_cfm", "return_cfm", "oa_cfm", "exhaust_cfm"],
        steps=_steps([
            ("s1", "Choose reference", "Outdoor reference away from wind/leaks; stable door condition.", "SCS_PRACTICE"),
            ("s2", "Zero instrument", "Zero at the reference.", "SCS_PRACTICE"),
            ("s3", "Measure building pressure", "Record sign (positive/negative) and magnitude.", "STANDARD_REQUIREMENT"),
            ("s4", "Gather flows if scope", "Supply/return/OA/exhaust totals for balance context.", "SCS_PRACTICE"),
            ("s5", "Assess", "Compare to design intent; do not over-infer from flows alone.", "SCS_PRACTICE"),
        ]),
    )

    library["fan_rpm_measurement"] = SCSProcedure(
        procedure_id="fan_rpm_measurement", version="1.0",
        title="Fan RPM measurement",
        scope="Measure fan / motor speed",
        equipment_classes=["FAN", "RTU", "AHU"], system_types=["SUPPLY_AIR", "EXHAUST_AIR"],
        applicable_instruments=["tachometer"],
        required_readings=["fan_rpm"],
        steps=_steps([
            ("s1", "Safe access", "Use safe line-of-sight to the shaft or reflective target.", "SCS_PRACTICE"),
            ("s2", "Measure RPM", "Record fan RPM (and motor RPM for belt units).", "SCS_PRACTICE"),
            ("s3", "Record VFD frequency", "If VFD-driven, record drive frequency/setpoint.", "SCS_PRACTICE"),
            ("s4", "Compare to design", "Scheduled RPM vs measured.", "SCS_PRACTICE"),
        ]),
    )

    library["vfd_airflow_adjustment"] = SCSProcedure(
        procedure_id="vfd_airflow_adjustment", version="1.0",
        title="VFD airflow adjustment",
        scope="Adjust VFD speed to achieve design airflow",
        equipment_classes=["FAN", "RTU", "AHU"], system_types=["SUPPLY_AIR"],
        applicable_instruments=["micromanometer", "tachometer"],
        required_readings=["airflow", "fan_rpm", "tesp"],
        required_inputs=["design_cfm", "oem_allowable_range"],
        steps=_steps([
            ("s1", "Confirm limits", "Verify the proposed frequency stays within OEM/VFD allowable range.", "OEM_REQUIREMENT"),
            ("s2", "Adjust speed", "Change frequency in small steps.", "SCS_PRACTICE"),
            ("s3", "Re-measure", "Traverse again; re-check fan RPM + motor current.", "SCS_PRACTICE"),
            ("s4", "Verify", "Percent design + TESP vs allowable.", "SCS_PRACTICE"),
        ]),
        oem_citations=["OEM fan/VFD IOM (when indexed)"],
        stop_conditions=["motor current approaching nameplate", "TESP beyond OEM allowable"],
    )

    library["high_static_investigation"] = SCSProcedure(
        procedure_id="high_static_investigation", version="1.0",
        title="High-static investigation",
        scope="Find and confirm the cause of high system static",
        equipment_classes=["RTU", "AHU", "FAN"], system_types=["SUPPLY_AIR", "RETURN_AIR"],
        applicable_instruments=["micromanometer", "static_probe"],
        required_readings=["tesp", "supply_static", "return_static"],
        optional_readings=["filter_dp", "coil_dp", "fan_rpm"],
        steps=_steps([
            ("s1", "Build TESP", "Measure supply + return static.", "SCS_PRACTICE"),
            ("s2", "Split location", "Return vs supply side static burden.", "SCS_PRACTICE"),
            ("s3", "Component delta-P", "Filter / coil / damper pressure drops where accessible.", "SCS_PRACTICE"),
            ("s4", "Compare to allowable", "Percent of OEM allowable static.", "OEM_REQUIREMENT"),
        ]),
    )

    library["low_airflow_investigation"] = SCSProcedure(
        procedure_id="low_airflow_investigation", version="1.0",
        title="Low-airflow investigation",
        scope="Diagnose a system delivering below-design airflow",
        equipment_classes=["RTU", "AHU", "FAN"], system_types=["SUPPLY_AIR"],
        applicable_instruments=["micromanometer", "tachometer"],
        required_readings=["airflow", "fan_rpm", "tesp"],
        optional_readings=["filter_dp", "coil_dp", "oa_damper_position"],
        steps=_steps([
            ("s1", "Confirm measurement quality", "Traverse location/geometry/zero correct before diagnosing.", "SCS_PRACTICE"),
            ("s2", "Record RPM", "Fan speed vs design (low RPM is a common cause).", "SCS_PRACTICE"),
            ("s3", "Static split", "Return vs supply burden.", "SCS_PRACTICE"),
            ("s4", "Component checks", "Filters/coils/dampers/duct restrictions.", "SCS_PRACTICE"),
            ("s5", "Assess", "Do not blind-increase speed; identify the restriction.", "SCS_PRACTICE"),
        ]),
    )

    library["diffuser_balancing"] = SCSProcedure(
        procedure_id="diffuser_balancing", version="1.0",
        title="Supply diffuser balancing",
        scope="Balance a supply outlet to its design airflow",
        equipment_classes=["AIR_DEVICE"], system_types=["SUPPLY_AIR"],
        applicable_instruments=["flow_hood", "rotating_vane"],
        required_inputs=["design_cfm"],
        required_readings=["as_found_cfm", "final_cfm"],
        steps=_steps([
            ("s1", "Hood setup", "Firm hood seal; level; no leaks.", "SCS_PRACTICE"),
            ("s2", "As-found reading", "Record as-found CFM before adjustment.", "SCS_PRACTICE"),
            ("s3", "Adjust damper", "Set balancing damper/cone to target.", "SCS_PRACTICE"),
            ("s4", "Final reading", "Record final CFM; confirm within tolerance.", "SCS_PRACTICE"),
        ]),
    )

    library["flow_hood_balancing"] = SCSProcedure(
        procedure_id="flow_hood_balancing", version="1.0",
        title="Flow-hood balancing",
        scope="Balance outlets with a flow hood",
        equipment_classes=["AIR_DEVICE"], system_types=["SUPPLY_AIR", "RETURN_AIR", "EXHAUST_AIR"],
        applicable_instruments=["flow_hood"],
        required_inputs=["design_cfm"],
        required_readings=["as_found_cfm", "final_cfm"],
        steps=_steps([
            ("s1", "Select correct hood", "Hood sized to the outlet; face area matches.", "SCS_PRACTICE"),
            ("s2", "Zero/verify hood", "Zero before use; check hood factor.", "INSTRUMENT_MANUAL"),
            ("s3", "Measure as-found", "Sealed, level hood; record.", "SCS_PRACTICE"),
            ("s4", "Adjust + final", "Adjust damper; re-measure to final.", "SCS_PRACTICE"),
        ]),
        standard_citations=["NEBB balance procedure (when indexed)"],
    )

    library["return_grille_balancing"] = SCSProcedure(
        procedure_id="return_grille_balancing", version="1.0",
        title="Return grille balancing",
        scope="Balance a return grille to design",
        equipment_classes=["AIR_DEVICE"], system_types=["RETURN_AIR"],
        applicable_instruments=["flow_hood"],
        required_readings=["as_found_cfm", "final_cfm"],
        steps=_steps([
            ("s1", "Hood setup", "Full seal around grille.", "SCS_PRACTICE"),
            ("s2", "As-found", "Record.", "SCS_PRACTICE"),
            ("s3", "Adjust + final", "Record final.", "SCS_PRACTICE"),
        ]),
    )

    library["exhaust_grille_balancing"] = SCSProcedure(
        procedure_id="exhaust_grille_balancing", version="1.0",
        title="Exhaust grille balancing",
        scope="Balance an exhaust grille to design",
        equipment_classes=["AIR_DEVICE"], system_types=["EXHAUST_AIR"],
        applicable_instruments=["flow_hood"],
        required_readings=["as_found_cfm", "final_cfm"],
        steps=_steps([
            ("s1", "Hood setup", "Seal around grille.", "SCS_PRACTICE"),
            ("s2", "As-found", "Record.", "SCS_PRACTICE"),
            ("s3", "Adjust + final", "Record final.", "SCS_PRACTICE"),
        ]),
    )

    library["belt_sheave_airflow_adjustment"] = SCSProcedure(
        procedure_id="belt_sheave_airflow_adjustment", version="1.0",
        title="Belt / sheave airflow adjustment",
        scope="Adjust fan speed via sheave change",
        equipment_classes=["FAN", "AHU"], system_types=["SUPPLY_AIR", "EXHAUST_AIR"],
        applicable_instruments=["tachometer", "micromanometer"],
        required_readings=["airflow", "fan_rpm", "motor_rpm"],
        required_inputs=["design_cfm", "motor_oem_limits"],
        steps=_steps([
            ("s1", "Confirm limits", "Motor nameplate + OEM fan limits.", "OEM_REQUIREMENT"),
            ("s2", "Adjust sheave", "Make small pitch change.", "SCS_PRACTICE"),
            ("s3", "Re-measure", "RPM + airflow; verify motor amps.", "SCS_PRACTICE"),
        ]),
        oem_citations=["OEM fan IOM (when indexed)"],
    )

    return library


PROCEDURE_LIBRARY = build_library()
