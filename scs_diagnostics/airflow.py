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
