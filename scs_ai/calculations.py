from __future__ import annotations

from typing import Any

_CALCULATION_SCHEMAS: dict[str, dict[str, Any]] = {
    "cfm_from_velocity_area": {
        "formula": "CFM = velocity (ft/min) × area (ft²)",
        "inputs": {"velocity_fpm": "number > 0", "area_sqft": "number > 0"},
    },
    "velocity_from_cfm_area": {
        "formula": "Velocity (ft/min) = CFM ÷ area (ft²)",
        "inputs": {"cfm": "number > 0", "area_sqft": "number > 0"},
    },
    "cfm_from_sensible_heat": {
        "formula": "CFM = sensible heat (BTU/h) ÷ (1.08 × ΔT °F)",
        "inputs": {"sensible_btuh": "number > 0", "delta_t_f": "number > 0"},
    },
    "traverse_cfm": {
        "formula": "CFM = average traverse velocity (ft/min) × area (ft²)",
        "inputs": {"readings_fpm": "list of numbers ≥ 0", "area_sqft": "number > 0"},
    },
    "total_static_pressure": {
        "formula": "Total static pressure (in. w.c.) = Σ component drops",
        "inputs": {"drops_inwc": "list of numbers ≥ 0"},
    },
    "pressure_convert": {
        "formula": "1 in. w.c. = 248.84 Pa",
        "inputs": {"value": "number ≥ 0", "from_unit": "'inwc' or 'pa'"},
    },
}

_PA_PER_INWC = 248.84


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    return float(value)


def _positive(value: Any, name: str) -> float:
    number = _number(value, name)
    if number <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return number


def _nonnegative_list(value: Any, name: str) -> list[float]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name} must be a non-empty list")
    numbers: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError(f"{name} must contain only numbers")
        if item < 0:
            raise ValueError(f"{name} must contain only values ≥ 0")
        numbers.append(float(item))
    return numbers


def _cfm_from_velocity_area(inputs: dict[str, Any]) -> dict[str, Any]:
    velocity = _positive(inputs.get("velocity_fpm"), "velocity_fpm")
    area = _positive(inputs.get("area_sqft"), "area_sqft")
    cfm = velocity * area
    return {"cfm": round(cfm, 2), "velocity_fpm": velocity, "area_sqft": area}


def _velocity_from_cfm_area(inputs: dict[str, Any]) -> dict[str, Any]:
    cfm = _positive(inputs.get("cfm"), "cfm")
    area = _positive(inputs.get("area_sqft"), "area_sqft")
    velocity = cfm / area
    return {"velocity_fpm": round(velocity, 2), "cfm": cfm, "area_sqft": area}


def _cfm_from_sensible_heat(inputs: dict[str, Any]) -> dict[str, Any]:
    btuh = _positive(inputs.get("sensible_btuh"), "sensible_btuh")
    delta_t = _positive(inputs.get("delta_t_f"), "delta_t_f")
    cfm = btuh / (1.08 * delta_t)
    return {"cfm": round(cfm, 2), "sensible_btuh": btuh, "delta_t_f": delta_t}


def _traverse_cfm(inputs: dict[str, Any]) -> dict[str, Any]:
    readings = _nonnegative_list(inputs.get("readings_fpm"), "readings_fpm")
    area = _positive(inputs.get("area_sqft"), "area_sqft")
    average = sum(readings) / len(readings)
    return {
        "cfm": round(average * area, 2),
        "average_velocity_fpm": round(average, 2),
        "readings_count": len(readings),
        "area_sqft": area,
    }


def _total_static_pressure(inputs: dict[str, Any]) -> dict[str, Any]:
    drops = _nonnegative_list(inputs.get("drops_inwc"), "drops_inwc")
    return {"total_inwc": round(sum(drops), 3), "component_count": len(drops)}


def _pressure_convert(inputs: dict[str, Any]) -> dict[str, Any]:
    value = _number(inputs.get("value"), "value")
    if value < 0:
        raise ValueError("value must be ≥ 0")
    unit = str(inputs.get("from_unit") or "").strip().casefold()
    if unit == "inwc":
        return {"inwc": value, "pa": round(value * _PA_PER_INWC, 2), "from_unit": "inwc"}
    if unit == "pa":
        return {"inwc": round(value / _PA_PER_INWC, 3), "pa": value, "from_unit": "pa"}
    raise ValueError("from_unit must be 'inwc' or 'pa'")


_HANDLERS = {
    "cfm_from_velocity_area": _cfm_from_velocity_area,
    "velocity_from_cfm_area": _velocity_from_cfm_area,
    "cfm_from_sensible_heat": _cfm_from_sensible_heat,
    "traverse_cfm": _traverse_cfm,
    "total_static_pressure": _total_static_pressure,
    "pressure_convert": _pressure_convert,
}


def schema() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "formula": spec["formula"],
            "inputs": spec["inputs"],
        }
        for name, spec in _CALCULATION_SCHEMAS.items()
    ]


def calculate(calculation: str, inputs: dict[str, Any]) -> dict[str, Any]:
    """Deterministic HVAC/TAB calculation. Never invents inputs or sources."""
    handler = _HANDLERS.get(calculation)
    if handler is None:
        return {
            "ok": False,
            "calculation": calculation,
            "errors": [f"unknown calculation '{calculation}'"],
            "result": None,
        }
    if not isinstance(inputs, dict):
        return {
            "ok": False,
            "calculation": calculation,
            "errors": ["inputs must be an object"],
            "result": None,
        }
    try:
        result = handler(dict(inputs))
    except ValueError as error:
        return {
            "ok": False,
            "calculation": calculation,
            "errors": [str(error)],
            "result": None,
        }
    return {
        "ok": True,
        "calculation": calculation,
        "formula": _CALCULATION_SCHEMAS[calculation]["formula"],
        "result": result,
        "errors": [],
    }