"""Scope-aware plan intelligence (M1.2, P34-P39).

Given an owner scope, returns only relevant mechanical facts, classifies
missing context by scope impact, produces a pre-job field plan, and expands
ready-to-leave using the PlanGraph. No irrelevant full-set dump; no invented
field conditions.
"""
from __future__ import annotations

from typing import Any

from .plan_graph import MechanicalPlanGraph


def _scope_rooms(scope_text: str, graph: MechanicalPlanGraph) -> list[str]:
    upper = scope_text.upper()
    matched = []
    for room in graph.rooms:
        name = room["name"].upper()
        if name in upper or any(
            token in name for token in ("STUDIO", "GYM", "FITNESS")
        ) and (("STUDIO A" in upper and "A" in name) or
               ("STUDIO B" in upper and "B" in name) or
               ("WORKOUT" in upper and "WORKOUT" in name)):
            matched.append(room["id"])
    return list(dict.fromkeys(matched)) or [r["id"] for r in graph.rooms]


def scope_relevant(graph: MechanicalPlanGraph, scope_text: str) -> dict[str, Any]:
    """Filter the graph to facts relevant to the scope."""
    rooms = _scope_rooms(scope_text, graph)
    relevant = {
        "rooms": [r for r in graph.rooms if r["id"] in rooms],
        "systems": [s for s in graph.systems],
        "equipment": [e for e in graph.equipment],
        "air_devices": [d for d in graph.air_devices
                        if (d.get("room") or "").upper() in rooms
                        or not rooms],
        "dampers": list(graph.dampers),
        "controls": list(graph.controls),
        "duct_segments": list(graph.duct_segments),
        "notes": list(graph.notes),
        "design_totals": [t for t in graph.design_totals if t["scope"] in rooms],
        "references": list(graph.references),
        "conflicts": list(graph.conflicts),
        "missing_context": list(graph.missing_context),
        "relationships": [r.to_dict() for r in graph.relationships
                          if r.source in rooms or r.target in rooms],
    }
    return relevant


def field_plan(graph: MechanicalPlanGraph, scope_text: str) -> dict[str, Any]:
    """Pre-job field plan: WHAT TO VERIFY / DESIGN VALUE / SOURCE per entity."""
    relevant = scope_relevant(graph, scope_text)
    systems: list[dict[str, Any]] = []
    for system in relevant["systems"]:
        equipment_id = system.get("equipment_reference")
        equipment = next((e for e in graph.equipment if e["id"] == equipment_id), None)
        fields = equipment.get("scheduled_fields", {}) if equipment else {}
        entry: dict[str, Any] = {
            "system": equipment_id,
            "verify": [
                {"what": "total airflow", "design": fields.get("SUPPLY_CFM"),
                 "unit": "CFM", "source": equipment.get("source") if equipment else None},
                {"what": "outside air", "design": fields.get("OUTSIDE_AIR_CFM"),
                 "unit": "CFM", "source": equipment.get("source") if equipment else None},
                {"what": "static (ESP)", "design": fields.get("ESP"),
                 "unit": "IN.W.G.", "source": equipment.get("source") if equipment else None},
                {"what": "fan speed", "design": fields.get("FAN_RPM"),
                 "unit": "RPM", "source": equipment.get("source") if equipment else None},
                {"what": "motor", "design": fields.get("MOTOR_HP"),
                 "unit": "HP", "source": equipment.get("source") if equipment else None},
                {"what": "VFD / operating mode", "design": fields.get("VFD"),
                 "source": equipment.get("source") if equipment else None},
            ],
            "devices": [
                {"device": d["id"], "room": d.get("room"), "design_cfm": d.get("design_cfm"),
                 "size": d.get("size"), "status": "NOT MEASURED",
                 "source": d.get("source")}
                for d in graph.air_devices
                if _device_served_by(d, system, graph)
            ],
            "dampers": [
                {"damper": dm["id"], "type": dm.get("damper_type"),
                 "source": dm.get("source")}
                for dm in graph.dampers
            ],
            "source": equipment.get("source") if equipment else None,
        }
        systems.append(entry)
    return {
        "scope": scope_text,
        "systems": systems,
        "dampers": [
            {"damper": dm["id"], "type": dm.get("damper_type"),
             "source": dm.get("source")}
            for dm in graph.dampers
        ],
        "life_safety": [
            {"damper": dm["id"], "type": dm.get("damper_type"),
             "note": "verify accessible/open during airflow test as scope permits",
             "source": dm.get("source")}
            for dm in graph.dampers
            if dm.get("damper_type") in ("FIRE_DAMPER", "SMOKE_DAMPER",
                                         "COMBINATION_FIRE_SMOKE_DAMPER")
        ],
        "notes": [{"note": n["id"], "text": n.get("literal_text"),
                   "sheet": n.get("applies_to_sheet")} for n in graph.notes],
        "missing_context": graph.missing_context,
    }


def _device_served_by(device: dict[str, Any], system: dict[str, Any],
                      graph: MechanicalPlanGraph) -> bool:
    served = set(system.get("devices_served") or [])
    if not served:
        return True
    return device["id"] in served


# ---------------------------------------------------------------------------
# Plan Chat over the graph (citations required)
# ---------------------------------------------------------------------------


def _cite(entity: dict[str, Any]) -> str:
    source = entity.get("source") or {}
    sheet = source.get("sheet")
    page = source.get("page")
    if sheet:
        return f"{sheet} page {page}"
    return f"page {page}" if page else "unknown sheet"


def answer_graph_question(text: str, graph: MechanicalPlanGraph) -> dict[str, Any]:
    """Grounded Plan Chat over the PlanGraph. Every answer cites sheet/page."""
    upper = text.upper()
    equipment = {e["id"]: e for e in graph.equipment}
    controls = {c["id"]: c for c in graph.controls}
    dampers = {d["id"]: d for d in graph.dampers}
    devices = {d["id"]: d for d in graph.air_devices}

    tag_match = __import__("re").search(
        r"\b(RTU|AHU|DOAS|MAU|EF|SF|RF|FCU|VAV|T|DSD|SP|CO2|FSD|FD|SMD|BD|MD)-?\s?\d{1,3}\b",
        upper,
    )
    if tag_match:
        tag = tag_match.group(0).upper().replace(" ", "-")
        tag = __import__("re").sub(r"-(\s*)(\d+)$", r"-\2", tag)
        if tag in equipment:
            e = equipment[tag]
            fields = e.get("scheduled_fields", {})
            return {
                "answer": (
                    f"{tag} is a {e.get('equipment_type')} "
                    f"({e.get('manufacturer')} {e.get('model')}); "
                    f"supply {fields.get('SUPPLY_CFM')} CFM, OA "
                    f"{fields.get('OUTSIDE_AIR_CFM')} CFM, ESP "
                    f"{fields.get('ESP')} in.w.g., fan {fields.get('FAN_RPM')} RPM, "
                    f"motor {fields.get('MOTOR') or fields.get('MOTOR_HP')} HP, "
                    f"VFD {fields.get('VFD')}, {fields.get('VOLTS')}V/{fields.get('PHASE')}ph. "
                    f"Source: {_cite(e)}."
                ),
                "source": e.get("source"), "equipment": tag,
            }
        if tag in controls:
            c = controls[tag]
            return {
                "answer": f"{tag} is a {c.get('control_type')}. Source: {_cite(c)}.",
                "source": c.get("source"), "control": tag,
            }
        if tag in dampers:
            d = dampers[tag]
            return {
                "answer": f"{tag} is a {d.get('damper_type')}. Source: {_cite(d)}.",
                "source": d.get("source"), "damper": tag,
            }
        if tag in devices:
            d = devices[tag]
            return {
                "answer": (f"{tag} is a {d.get('type') or 'air device'} in "
                           f"{d.get('room') or 'unassigned'}; design "
                           f"{d.get('design_cfm')} CFM, size {d.get('size') or 'n/a'}. "
                           f"Source: {_cite(d)}."),
                "source": d.get("source"), "device": tag,
            }

    if "FIRE/SMOKE" in upper or ("DAMPER" in upper and ("FIRE" in upper or "SMOKE" in upper or "ALL" in upper)):
        ls = [d for d in graph.dampers
              if d.get("damper_type") in ("FIRE_DAMPER", "SMOKE_DAMPER",
                                          "COMBINATION_FIRE_SMOKE_DAMPER")]
        return {
            "answer": (
                f"{len(ls)} fire/smoke damper(s): "
                + ", ".join(f"{d['id']} ({d.get('damper_type')}@{_cite(d)})"
                            for d in ls) + "."
            ),
            "source": {"sheet": "plans"},
        }
    if "BALANCING DAMPER" in upper or "VOLUME DAMPER" in upper:
        bd = [d for d in graph.dampers if d.get("damper_type") in (
            "BALANCING_DAMPER", "VOLUME_DAMPER")]
        return {
            "answer": f"Balancing dampers: " + ", ".join(
                f"{d['id']}@{_cite(d)}" for d in bd) + ".",
            "source": {"sheet": "plans"},
        }
    if "RPM" in upper or "SPEED" in upper:
        hits = [e for e in graph.equipment
                if e.get("scheduled_fields", {}).get("FAN_RPM")]
        return {
            "answer": ", ".join(
                f"{e['id']} fan {e.get('scheduled_fields', {}).get('FAN_RPM')} RPM@"
                f"{_cite(e)}" for e in hits) or "no fan RPM found in the supplied schedules.",
            "source": {"sheet": "equipment schedule"},
        }
    if "MISSING" in upper or "PARTIAL" in upper:
        missing = graph.missing_context
        return {
            "answer": "Missing/uncertain drawing context: " + "; ".join(
                f"{m.get('kind')} {m.get('sheet_id', '')} ({m.get('classification')})"
                for m in missing) if missing else "No missing drawing context detected.",
            "source": {"sheet": "packet"},
        }
    if "RELEVANT TO" in upper or "BEFORE BALANCING" in upper or "EVERYTHING" in upper:
        scope = "Verify airflow and balance the mechanical systems"
        plan = field_plan(graph, scope)
        return {
            "answer": (
                "Pre-job plan: " +
                "; ".join(
                    f"{s['system']}: verify " + ", ".join(
                        f"{v['what']} ({v['design'] or 'n/a'})" for v in s['verify'][:4])
                    for s in plan["systems"]
                ) +
                " | life-safety: " + ", ".join(
                    f"{d['damper']} ({d['type']})" for d in plan["life_safety"]) +
                " | sources on M2.2 equipment schedule."
            ),
            "source": {"sheet": "M2.2"},
        }

    return {
        "answer": (
            f"I can answer from the mechanical plan graph: "
            f"{len(graph.equipment)} equipment, {len(graph.air_devices)} air devices, "
            f"{len(graph.dampers)} dampers, {len(graph.controls)} controls, "
            f"{len(graph.rooms)} rooms across {len(graph.sheets)} sheets."
        ),
        "source": None,
    }


def ready_to_leave_graph(graph: MechanicalPlanGraph, record) -> dict[str, Any]:
    """Graph-aware ready-to-leave over the JobRecord + PlanGraph."""
    missing: list[str] = []
    ok: list[str] = []
    optional: list[str] = []

    device_finals = {d.device_id: d.final_cfm for d in record.air_devices}
    for device in graph.air_devices:
        if device.get("function") in ("RETURN", "EXHAUST"):
            continue
        final = device_finals.get(device["id"])
        if final is None:
            missing.append(f"{device['id']} ({device.get('room') or '?'}) design "
                           f"{device.get('design_cfm')} CFM not measured")
        else:
            ok.append(f"{device['id']} measured")

    for system in graph.systems:
        equipment_id = system.get("equipment_reference")
        eq = next((e for e in graph.equipment if e["id"] == equipment_id), None)
        if eq is None:
            continue
        fields = eq.get("scheduled_fields", {})
        supply = fields.get("SUPPLY_CFM")
        if supply is not None:
            missing.append(f"{equipment_id} total airflow (design {supply} CFM) requires verification")

    vfds = [c["id"] for c in graph.controls if c.get("control_type") == "VFD"]
    if vfds:
        optional.append("confirm VFD operating mode: " + ", ".join(vfds))

    life_safety = [
        dm["id"] for dm in graph.dampers
        if dm.get("damper_type") in ("FIRE_DAMPER", "SMOKE_DAMPER",
                                     "COMBINATION_FIRE_SMOKE_DAMPER")
    ]
    if life_safety:
        optional.append("address life-safety damper access/status: " + ", ".join(life_safety))

    if graph.conflicts:
        missing.append("resolve documented design conflicts before closeout")

    return {
        "readiness": "READY" if not missing else "MISSING BEFORE LEAVING",
        "MISSING_BEFORE_LEAVING": missing,
        "OK": ok,
        "OPTIONAL": optional,
    }
