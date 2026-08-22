"""Pressurization + air-balance diagnostics (M1.3, P28/P30).

NEGATIVE_BUILDING_PRESSURE / POSITIVE_BUILDING_PRESSURE / HIGH_HUMIDITY /
LOW_COOLING_CAPACITY / LOW_TEMP_SPLIT diagnostic graphs + a next-best-
measurement ranker (P29) shared across diagnostics.
"""
from __future__ import annotations

from typing import Any

from .graph import DiagnosticCause, DiagnosticGraph


def negative_building_pressure_graph() -> DiagnosticGraph:
    return DiagnosticGraph(
        graph_id="NEGATIVE_BUILDING_PRESSURE", symptom="building pressure negative",
        causes=[
            DiagnosticCause("exhaust_gt_makeup", "exhaust/relief exceeds outside-air makeup",
                            required_measurements=["exhaust_cfm", "oa_cfm", "supply_cfm", "return_cfm"]),
            DiagnosticCause("oa_damper_closed", "outside-air damper closed or minimum too low",
                            required_measurements=["oa_damper_position", "oa_cfm"]),
            DiagnosticCause("makeup_shortage", "no/insufficient dedicated makeup",
                            required_measurements=["supply_vs_exhaust_balance"]),
            DiagnosticCause("measurement_quality", "reference/wind/leak error",
                            required_measurements=["verify_reference"]),
        ],
        decision_splits=["is exhaust > makeup?", "is OA damper at minimum?"],
        next_best_measurements=["oa_cfm", "exhaust_total", "supply_total", "return_total"],
    )


def positive_building_pressure_graph() -> DiagnosticGraph:
    return DiagnosticGraph(
        graph_id="POSITIVE_BUILDING_PRESSURE", symptom="building pressure positive",
        causes=[
            DiagnosticCause("supply_exceeds_return", "supply exceeds return/exhaust path",
                            required_measurements=["supply_cfm", "return_cfm"]),
            DiagnosticCause("relief_inadequate", "relief air path inadequate",
                            required_measurements=["relief_cfm"]),
            DiagnosticCause("oa_excess", "excess outside air"),
        ],
        next_best_measurements=["supply_total", "return_total", "relief_cfm"],
    )


def high_humidity_graph() -> DiagnosticGraph:
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


def low_cooling_capacity_graph() -> DiagnosticGraph:
    return DiagnosticGraph(
        graph_id="LOW_COOLING_CAPACITY", symptom="cooling capacity below expectation",
        causes=[
            DiagnosticCause("airflow_low", "low coil airflow",
                            required_measurements=["coil_cfm"]),
            DiagnosticCause("refrigerant", "refrigerant charge/performance",
                            required_measurements=["saturated_temps", "superheat", "subcooling"]),
            DiagnosticCause("coil_airside", "coil fouling / bypass",
                            required_measurements=["coil_dp", "dT"]),
            DiagnosticCause("oa_load", "excess outside-air load"),
        ],
        next_best_measurements=["coil_cfm", "enter_lv_temp", "leave_temp", "charge_indicators"],
    )


def low_temp_split_graph() -> DiagnosticGraph:
    return DiagnosticGraph(
        graph_id="LOW_TEMPERATURE_SPLIT", symptom="supply/return temperature split low",
        causes=[
            DiagnosticCause("low_airflow_or_bypass", "airflow too low or coil bypass"),
            DiagnosticCause("capacity_shortfall", "unit capacity below load"),
            DiagnosticCause("economizer_mixing", "economizer/OA mixing raising supply temp"),
            DiagnosticCause("sensor_error", "temperature sensor error"),
        ],
        next_best_measurements=["coil_cfm", "mixed_air_temp", "supply_temp", "return_temp"],
    )


# ---------------------------------------------------------------------------
# Next-best-measurement ranking (P29)
# ---------------------------------------------------------------------------

_MEASUREMENT_VALUE = {
    "supply_static": 8, "return_static": 8, "fan_rpm": 9, "vfd_frequency": 7,
    "filter_dp": 6, "coil_dp": 6, "tesp": 8, "oa_cfm": 8, "exhaust_cfm": 7,
    "supply_cfm": 7, "return_cfm": 6, "relief_cfm": 5, "upstream_static": 6,
    "oa_damper_position": 5, "enter_lv_temp": 5, "leave_temp": 5,
}


def rank_next_best_measurements(graph: DiagnosticGraph,
                                known: set[str] | None = None) -> list[str]:
    """Rank required measurements by expected information gained, minus known."""
    known = known or set()
    scored: dict[str, int] = {}
    for cause in graph.unresolved_causes():
        for measurement in cause.required_measurements:
            if measurement in known:
                continue
            scored[measurement] = scored.get(measurement, 0) + _MEASUREMENT_VALUE.get(
                measurement, 5)
    for measurement in graph.next_best_measurements:
        if measurement in known:
            continue
        scored[measurement] = scored.get(measurement, 0) + _MEASUREMENT_VALUE.get(
            measurement, 5)
    ordered = sorted(scored.items(), key=lambda kv: -kv[1])
    return [m for m, _s in ordered]
