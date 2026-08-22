"""Airflow / static diagnostics (M1.3, P28-P31, P29).

Deterministic, evidence-graded diagnostic graphs for LOW_AIRFLOW,
HIGH_STATIC, LOW_STATIC/HIGH_AIRFLOW, UNEQUAL_BRANCH_AIRFLOW, VAV_MAX/MIN,
FAN_SPEED_LIMITED, EXHAUST_UNDERPERFORMING, MEASUREMENT_QUALITY_SUSPECT.

The engine always considers measurement-quality faults first and ranks
NEXT_BEST_MEASUREMENT by information gained - it never jumps to
"increase fan speed" from one suspicious reading.
"""
from __future__ import annotations

from typing import Any

from .graph import DiagnosticCause, DiagnosticGraph


def low_airflow_graph() -> DiagnosticGraph:
    graph = DiagnosticGraph(
        graph_id="LOW_AIRFLOW", symptom="measured airflow below design",
        causes=[
            DiagnosticCause("return_side_restriction",
                            "return-side restriction (filters/duct/damper)",
                            required_measurements=["return_static", "filter_dp"],
                            risk="LOW", source_basis=["SCS TAB practice"]),
            DiagnosticCause("supply_side_restriction",
                            "supply-side restriction (coil/duct/damper)",
                            required_measurements=["supply_static", "coil_dp"],
                            risk="LOW", source_basis=["SCS TAB practice"]),
            DiagnosticCause("low_fan_speed",
                            "fan running below design speed (belt/VFD)",
                            required_measurements=["fan_rpm", "vfd_frequency"],
                            risk="MEDIUM", source_basis=["fan law 1"]),
            DiagnosticCause("measurement_quality",
                            "measurement setup fault (traverse location/geometry/zero)",
                            required_measurements=["verify_traverse_plane",
                                                   "verify_duct_dimensions"],
                            risk="LOW", source_basis=["P31 measurement-quality guard"]),
            DiagnosticCause("filter_load",
                            "loaded/dirty filters",
                            required_measurements=["filter_dp"],
                            risk="LOW"),
        ],
        decision_splits=[
            "measurement quality verified?",
            "fan RPM at design?",
            "return vs supply static burden?",
        ],
        next_best_measurements=["supply_static", "return_static", "fan_rpm"],
    )
    return graph


def apply_low_airflow_evidence(graph: DiagnosticGraph, *, design_cfm: float | None,
                               measured_cfm: float | None, fan_rpm: float | None = None,
                               design_rpm: float | None = None,
                               return_static: float | None = None,
                               supply_static: float | None = None) -> DiagnosticGraph:
    if design_cfm and measured_cfm:
        pct = (measured_cfm / design_cfm) * 100.0
        graph.record_observation("percent_design", round(pct, 1), "calculator")
    if fan_rpm is not None and design_rpm:
        graph.record_observation("fan_rpm", fan_rpm, "field")
        if fan_rpm < design_rpm * 0.95:
            graph.update_cause("low_fan_speed", f"fan RPM {fan_rpm} below design {design_rpm}",
                               True, "field measurement")
        else:
            graph.update_cause("low_fan_speed", f"fan RPM {fan_rpm} at/near design {design_rpm}",
                               False, "field measurement")
    if return_static is not None and supply_static is not None:
        if abs(return_static) > abs(supply_static):
            graph.update_cause("return_side_restriction",
                               f"return static {return_static} exceeds supply {supply_static}",
                               True, "static split")
            graph.update_cause("supply_side_restriction", "supply static is the smaller burden",
                               False, "static split")
            graph.next_best_measurements = [
                "filter_dp", "return_duct/return damper check", "record fan RPM"]
        elif abs(supply_static) > abs(return_static):
            graph.update_cause("supply_side_restriction",
                               f"supply static {supply_static} exceeds return {return_static}",
                               True, "static split")
            graph.update_cause("return_side_restriction", "return static is the smaller burden",
                               False, "static split")
            graph.next_best_measurements = [
                "coil_dp", "supply duct/damper check", "record fan RPM"]
        else:
            graph.next_best_measurements = ["supply_static", "return_static", "fan_rpm"]
    else:
        graph.next_best_measurements = ["supply_static", "return_static", "fan_rpm"]
    return graph


def high_static_graph() -> DiagnosticGraph:
    return DiagnosticGraph(
        graph_id="HIGH_STATIC", symptom="TESP at or above OEM/design allowable",
        causes=[
            DiagnosticCause("filter_load", "loaded filters", required_measurements=["filter_dp"], risk="LOW"),
            DiagnosticCause("return_side_restriction", "return-side obstruction", required_measurements=["return_static"]),
            DiagnosticCause("supply_side_restriction", "supply-side obstruction", required_measurements=["supply_static", "coil_dp"]),
            DiagnosticCause("measurement_quality", "static tap location/zero error", required_measurements=["verify_taps"]),
        ],
        next_best_measurements=["filter_dp", "return_static", "supply_static", "coil_dp"],
    )


def low_static_high_airflow_graph() -> DiagnosticGraph:
    return DiagnosticGraph(
        graph_id="LOW_STATIC_HIGH_AIRFLOW", symptom="low static with airflow above design",
        causes=[
            DiagnosticCause("damper_open", "OA/relief dampers open or bypassing"),
            DiagnosticCause("duct_leak", "supply/return duct leakage"),
            DiagnosticCause("sensor_error", "static sensor or tap error"),
        ],
        next_best_measurements=["verify_damper_positions", "check_duct_leaks", "verify_sensor"],
    )


def vav_not_reaching_max_graph() -> DiagnosticGraph:
    return DiagnosticGraph(
        graph_id="VAV_NOT_REACHING_MAX", symptom="VAV box not reaching design maximum",
        causes=[
            DiagnosticCause("box_stuck_closed", "box/actuator not fully open", required_measurements=["command", "position"]),
            DiagnosticCause("insufficient_upstream_static", "upstream static below required pickup", required_measurements=["upstream_static"]),
            DiagnosticCause("flow_sensor_error", "flow sensor/K-factor incorrect", required_measurements=["measured_vs_controller"]),
            DiagnosticCause("supply_system_capacity", "supply fan/system cannot deliver", required_measurements=["system_traverse"]),
        ],
        next_best_measurements=["command_position", "upstream_static", "controller_flow", "measured_vp"],
    )


def exhaust_underperforming_graph() -> DiagnosticGraph:
    return DiagnosticGraph(
        graph_id="EXHAUST_UNDERPERFORMING", symptom="exhaust airflow below design",
        causes=[
            DiagnosticCause("fan_speed", "exhaust fan speed low"),
            DiagnosticCause("restriction", "exhaust duct/damper restriction"),
            DiagnosticCause("makeup_air", "inadequate makeup air limiting exhaust"),
            DiagnosticCause("hood_bypass", "hood/relief bypass or damper closed"),
        ],
        next_best_measurements=["fan_rpm", "exhaust_static", "makeup_air_flow"],
    )


def vav_not_reaching_min_graph() -> DiagnosticGraph:
    return DiagnosticGraph(
        graph_id="VAV_NOT_REACHING_MIN", symptom="VAV box not maintaining minimum",
        causes=[
            DiagnosticCause("box_stuck", "box cannot close / leaky"),
            DiagnosticCause("upstream_static_high", "excess upstream static"),
            DiagnosticCause("flow_sensor_error", "flow sensor/K-factor error"),
        ],
        next_best_measurements=["command_position", "measured_vs_controller", "upstream_static"],
    )


def low_oa_graph() -> DiagnosticGraph:
    return DiagnosticGraph(
        graph_id="LOW_OUTSIDE_AIR", symptom="outside air below design",
        causes=[
            DiagnosticCause("oa_damper_closed", "OA damper closed/minimum too low",
                            required_measurements=["oa_damper_position"]),
            DiagnosticCause("oa_path_restricted", "OA intake/duct restricted",
                            required_measurements=["oa_velocity"]),
            DiagnosticCause("economizer_override", "control/economizer overriding OA"),
            DiagnosticCause("measurement_quality", "OA measurement error",
                            required_measurements=["verify_oa_traverse"]),
        ],
        next_best_measurements=["oa_damper_position", "oa_velocity", "oa_temp"],
    )


def high_oa_graph() -> DiagnosticGraph:
    return DiagnosticGraph(
        graph_id="HIGH_OUTSIDE_AIR", symptom="outside air above design",
        causes=[
            DiagnosticCause("oa_damper_open", "OA damper open/excessive"),
            DiagnosticCause("relief_inadequate", "relief path inadequate"),
            DiagnosticCause("economizer_always", "economizer stuck/always economizing"),
        ],
        next_best_measurements=["oa_damper_position", "relief_cfm", "economizer_state"],
    )


def humidity_graph() -> DiagnosticGraph:
    return DiagnosticGraph(
        graph_id="HIGH_HUMIDITY_POOR_DEHUMID", symptom="high humidity / poor dehumidification",
        causes=[
            DiagnosticCause("oa_imbalance", "excess humid outside air / unbalanced OA",
                            required_measurements=["oa_cfm", "oa_enthalpy"]),
            DiagnosticCause("coil_shortfall", "cooling coil not removing latent load",
                            required_measurements=["coil_dp", "sensible_capacity", "latent_capacity"]),
            DiagnosticCause("sensor_error", "RH sensor calibration"),
        ],
        next_best_measurements=["oa_cfm", "oa_wb", "ra_wb", "coil_conditions"],
    )


def belt_slip_graph() -> DiagnosticGraph:
    return DiagnosticGraph(
        graph_id="BELT_SLIP", symptom="fan RPM below motor RPM (belt-driven)",
        causes=[
            DiagnosticCause("belt_tension", "loose/worn belt slipping",
                            required_measurements=["fan_rpm", "motor_rpm", "belt_condition"]),
            DiagnosticCause("sheave_mismatch", "sheave diameter mismatch",
                            required_measurements=["sheave_diameters"]),
            DiagnosticCause("load_over", "fan load exceeds drive capacity",
                            required_measurements=["motor_amps"]),
            DiagnosticCause("measurement_quality", "tachometer method error",
                            required_measurements=["verify_rpm_method"]),
        ],
        next_best_measurements=["fan_rpm", "motor_rpm", "belt_tension_check"],
    )


def dirty_filter_graph() -> DiagnosticGraph:
    return DiagnosticGraph(
        graph_id="DIRTY_FILTER_OR_RETURN_RESTRICTION", symptom="high return static / low airflow",
        causes=[
            DiagnosticCause("filter_load", "loaded/dirty filters",
                            required_measurements=["filter_dp"]),
            DiagnosticCause("return_restriction", "return duct/damper obstruction",
                            required_measurements=["return_static"]),
            DiagnosticCause("coil_restriction", "coil fouling restricting air",
                            required_measurements=["coil_dp"]),
            DiagnosticCause("measurement_quality", "static tap error",
                            required_measurements=["verify_taps"]),
        ],
        next_best_measurements=["filter_dp", "return_static", "coil_dp"],
    )


def duct_restriction_graph() -> DiagnosticGraph:
    return DiagnosticGraph(
        graph_id="DUCT_RESTRICTION", symptom="local airflow shortfall downstream",
        causes=[
            DiagnosticCause("duct_obstruction", "duct obstruction/collapse",
                            required_measurements=["local_static", "visual"]),
            DiagnosticCause("damper_closed", "balancing damper closed/restricted",
                            required_measurements=["damper_position"]),
            DiagnosticCause("branch_imbalance", "upstream branch imbalance",
                            required_measurements=["branch_flow_comparison"]),
        ],
        next_best_measurements=["local_static", "damper_position", "branch_flows"],
    )


def sensor_error_graph() -> DiagnosticGraph:
    return DiagnosticGraph(
        graph_id="SENSOR_ERROR", symptom="reading inconsistent with system behavior",
        causes=[
            DiagnosticCause("sensor_calibration", "sensor out of calibration",
                            required_measurements=["calibration_check"]),
            DiagnosticCause("sensor_location", "sensor in wrong location",
                            required_measurements=["verify_sensor_placement"]),
            DiagnosticCause("wiring", "wiring/connection issue",
                            required_measurements=["signal_check"]),
        ],
        next_best_measurements=["calibration_check", "verify_placement", "signal_check"],
    )


def control_mode_error_graph() -> DiagnosticGraph:
    return DiagnosticGraph(
        graph_id="CONTROL_MODE_ERROR", symptom="system operating in unexpected mode",
        causes=[
            DiagnosticCause("mode_schedule", "schedule/occupancy mode wrong",
                            required_measurements=["current_mode", "schedule"]),
            DiagnosticCause("dcv_active", "DCV/CO2 overriding airflow",
                            required_measurements=["oa_damper_position", "co2"]),
            DiagnosticCause("economizer", "economizer/control action wrong",
                            required_measurements=["dry_bulb", "enthalpy", "damper_position"]),
            DiagnosticCause("setpoint", "setpoint misconfiguration",
                            required_measurements=["setpoint_check"]),
        ],
        next_best_measurements=["current_mode", "setpoint_check", "oa_damper_position"],
    )


def economizer_error_graph() -> DiagnosticGraph:
    return DiagnosticGraph(
        graph_id="ECONOMIZER_ERROR", symptom="economizer not economizing / OA too high",
        causes=[
            DiagnosticCause("sensor_fault", "OA/RA sensor fault",
                            required_measurements=["oa_db", "ra_db", "enthalpy"]),
            DiagnosticCause("damper_fault", "OA/return damper not modulating",
                            required_measurements=["damper_position", "actuator"]),
            DiagnosticCause("logic", "economizer logic/setpoints wrong",
                            required_measurements=["changeover_setpoint"]),
            DiagnosticCause("mixed_air", "mixed-air control issue",
                            required_measurements=["mixed_air_temp"]),
        ],
        next_best_measurements=["oa_db", "ra_db", "damper_position"],
    )


def fan_rotation_graph() -> DiagnosticGraph:
    return DiagnosticGraph(
        graph_id="INCORRECT_FAN_ROTATION", symptom="fan rotation suspect (reversed/wrong phase)",
        causes=[
            DiagnosticCause("rotation_reversed", "fan wheel rotating backward",
                            required_measurements=["rotation_check", "airflow_direction"]),
            DiagnosticCause("phase_wiring", "3-phase wiring order",
                            required_measurements=["phase_check"]),
            DiagnosticCause("vfd_reverse", "VFD direction setting",
                            required_measurements=["vfd_direction"]),
        ],
        next_best_measurements=["rotation_check", "airflow_direction"],
    )


def vav_pickup_calibration_graph() -> DiagnosticGraph:
    return DiagnosticGraph(
        graph_id="VAV_PICKUP_CALIBRATION", symptom="VAV flow reading vs actual discrepancy",
        causes=[
            DiagnosticCause("k_factor", "K-factor wrong for box/controller",
                            required_measurements=["measured_vs_controller"]),
            DiagnosticCause("pickup_tap", "pickup tap/velocity sensor issue",
                            required_measurements=["vp_check"]),
            DiagnosticCause("upstream_static", "insufficient pickup pressure",
                            required_measurements=["upstream_static"]),
        ],
        next_best_measurements=["measured_vs_controller", "vp_check", "upstream_static"],
    )


def before_after_update(graph: DiagnosticGraph, *, before_value: Any,
                        after_value: Any, measurement: str,
                        improved: bool) -> DiagnosticGraph:
    """P44: before/after adjustment updates diagnostic state with the
    calculated effect - never overwrites the historical reading."""
    graph.record_observation(f"{measurement}_before", before_value, "field")
    graph.record_observation(f"{measurement}_after", after_value, "field")
    for cause in graph.unresolved_causes():
        if measurement in cause.required_measurements:
            basis = f"{measurement} changed {before_value} -> {after_value}"
            graph.update_cause(cause.cause_id, basis,
                               supports=improved, basis="before/after evidence")
    return graph
