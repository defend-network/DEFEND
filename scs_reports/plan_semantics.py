"""Plan semantics orchestration (M1.2).

Turns indexed documents (native + optional raster OCR words) into a
MechanicalPlanGraph: sheets, legend/symbols, exhaustive schedules, equipment,
systems, air devices, dampers, controls, ducts, rooms, notes, keynotes,
references, relationships, design totals and conflicts. Every fact carries
provenance; missing context stays explicit; nothing is hallucinated.

graph -> DesignBasis keeps the existing preengineer/report pipeline unchanged.
"""
from __future__ import annotations

import re
from typing import Any

from . import plans
from . import plan_packet as pk
from .plan_entities import (
    control_from_tag,
    damper_from_tag,
    duct_from_size_callout,
    equipment_from_schedule,
    note_entity,
    reference_entity,
    room_entity,
)
from .plan_graph import MechanicalPlanGraph
from .plan_schedules import schedules_from_words
from .plan_symbols import PlanSymbolDictionary, extract_legend

_DAMPER_TAG_RE = re.compile(r"^(BD|VD|MD|FD|SD|SMD|FSD|CD|BKD)-?\d{1,3}$")
_CONTROL_TAG_RE = re.compile(r"^(T|TS|DS|RH|CO2|SP|DP|DSD|OCC|ACT|VFD)-?\d{1,3}$")
_KEYNOTE_RE = re.compile(r"^\d{1,2}$")


def _page_words(doc: plans.PlanDocument, page: plans.PlanPage,
                raster_words: dict[int, list[plans.Word]] | None) -> list[plans.Word]:
    if page.words:
        return page.words
    if raster_words and page.page_number in raster_words:
        return raster_words[page.page_number]
    return []


def _keynotes_from_notes_page(page: plans.PlanPage) -> dict[str, str]:
    """Numbered notes -> keynote map (e.g. '12' -> 'Provide manual balancing...')."""
    keynotes: dict[str, str] = {}
    lines = [ln.strip() for ln in page.text.splitlines() if ln.strip()]
    for line in lines:
        match = re.match(r"^(\d{1,2})[.)]\s+(.+)", line)
        if match:
            keynotes[match.group(1)] = match.group(2)
    return keynotes


def _references_in_text(text: str) -> list[str]:
    return [f"{a}/{b.upper()}" for a, b in
            pk.DETAIL_REF_RE.findall(text)]


def build_graph(
    documents: list[plans.PlanDocument],
    *,
    packet: pk.PlanPacket | None = None,
    raster_words: dict[int, list[plans.Word]] | None = None,
) -> MechanicalPlanGraph:
    packet = packet or pk.build_packet(documents)
    graph = MechanicalPlanGraph(packet=packet.to_dict())
    graph.sheets = [s.to_dict() for s in packet.sheets]
    graph.missing_context = pk.classify_missing_context(packet)

    # legend + symbol dictionary
    legend_sheets = [page for doc in documents for page in doc.pages
                     if page.page_type in ("MECHANICAL_LEGEND", "AIR_DEVICE_PLAN")
                     and "LEGEND" in (page.text.upper() or "")]
    legend_dict: PlanSymbolDictionary | None = None
    for page in legend_sheets:
        legend = extract_legend(page)
        graph.legends.append(legend.to_dict())
        for label, entry in legend.entries.items():
            graph.symbols.append(entry.to_dict())
        if legend_dict is None or legend.supplied:
            legend_dict = legend

    schedule_types: dict[str, dict[str, str]] = {}
    schedule_cfm: dict[str, float] = {}
    schedule_size: dict[str, str] = {}
    equipment_rows: list[dict[str, Any]] = []
    for doc in documents:
        for page in doc.pages:
            words = _page_words(doc, page, raster_words)
            if not words:
                continue
            if page.page_type in (
                "AIR_DEVICE_SCHEDULE", "EQUIPMENT_SCHEDULE", "VAV_SCHEDULE",
                "FAN_SCHEDULE", "RTU_SCHEDULE", "AHU_SCHEDULE",
            ):
                for raw in schedules_from_words(words, sheet=page.sheet_number,
                                                page=page.page_number):
                    graph.schedules.append(raw.to_dict())
                    for row in raw.rows:
                        tag = next((v.get("raw_text") for k, v in row.cells.items()
                                    if plans._norm_header(k) in ("tag",) or
                                    "tag" == k.lower()), "") or ""
                        tag = tag.upper()
                        if not tag:
                            continue
                        cell_text = {k: v.get("raw_text") for k, v in row.cells.items()}
                        if "AIR_DEVICE_SCHEDULE" in raw.kind:
                            schedule_types[tag] = cell_text
                            cfm = plans._num(cell_text.get("DESIGN_CFM"))
                            if cfm is not None:
                                schedule_cfm[tag] = cfm
                            size = (cell_text.get("NECK_SIZE")
                                    or cell_text.get("SIZE")
                                    or cell_text.get("FACE_SIZE"))
                            if size:
                                schedule_size[tag] = size
                        elif tag.startswith(("RTU", "AHU", "FAN", "FCU", "VAV", "DOAS", "EF", "SF")):
                            equipment = equipment_from_schedule(
                                cell_text, sheet=page.sheet_number, page=page.page_number)
                            if equipment:
                                equipment_rows.append(equipment)
            elif page.page_type == "MECHANICAL_GENERAL_NOTES":
                keynotes = _keynotes_from_notes_page(page)
                for note_id, text in keynotes.items():
                    note = note_entity(f"{page.sheet_number}K{note_id}", text,
                                       sheet=page.sheet_number, page=page.page_number)
                    graph.notes.append(note)
                    for ref in _references_in_text(text):
                        present = any(
                            s.sheet_number and s.sheet_number.upper() == ref.split("/")[-1].upper()
                            for s in packet.sheets)
                        graph.references.append(reference_entity(
                            ref, source_text=text, sheet=page.sheet_number,
                            page=page.page_number, present=present))
                # general notes not part of keynote list
                for line in [ln.strip() for ln in page.text.splitlines() if ln.strip()]:
                    match = re.match(r"^(\d{1,2})[.)]\s+(.+)", line)
                    if not match:
                        continue
                    text = match.group(2)
                    if f"{page.sheet_number}K{match.group(1)}" not in {n["id"] for n in graph.notes}:
                        graph.notes.append(note_entity(
                            f"{page.sheet_number}N{match.group(1)}", text,
                            sheet=page.sheet_number, page=page.page_number))

    graph.equipment = equipment_rows

    # plan pages: air devices, dampers, controls, ducts, rooms, keynotes
    air_devices: list[dict[str, Any]] = []
    dampers: list[dict[str, Any]] = []
    controls: list[dict[str, Any]] = []
    duct_segments: list[dict[str, Any]] = []
    rooms: dict[str, dict[str, Any]] = {}
    keynote_plan_locations: dict[str, list[dict[str, Any]]] = {}
    for doc in documents:
        for page in doc.pages:
            if page.page_type not in ("MECHANICAL_PLAN", "HVAC_PLAN", "DUCT_PLAN",
                                      "AIR_DEVICE_PLAN", "UNKNOWN"):
                continue
            words = _page_words(doc, page, raster_words)
            if not words:
                continue
            text_upper = " ".join(w.text for w in words).upper()
            if "LEGEND" in text_upper:
                continue  # legend page is not a plan-instance page
            pagedict = plans.PlanPage(page_number=page.page_number,
                                      sheet_number=page.sheet_number,
                                      sheet_title=None, page_type="PLAN",
                                      confidence=0.0, width=page.width,
                                      height=page.height,
                                      text=" ".join(w.text for w in words),
                                      words=words)
            for device in plans.extract_plan_devices(pagedict):
                type_tag = device.get("schedule_type")
                cfm, size, _mapped, method = plans.resolve_instance_design(
                    device, schedule_types, schedule_cfm, schedule_size)
                device["design_cfm"] = cfm
                device["size"] = size
                device["type"] = (schedule_types.get(type_tag, {}).get("type")
                                  if type_tag else None)
                device["source"]["extraction_method"] = "PLAN_EXTRACTED"
                device["kind"] = "air_device"
                device["id"] = device["device_id"]
                air_devices.append(device)
                room = device.get("room")
                if room:
                    entry = rooms.setdefault(room.upper(),
                                             room_entity(room, sheet=page.sheet_number,
                                                         page=page.page_number))
            for w in words:
                prefix_match = _DAMPER_TAG_RE.match(w.text.upper())
                if prefix_match:
                    dampers.append(damper_from_tag(
                        w.text, sheet=page.sheet_number, page=page.page_number,
                        dictionary=legend_dict, bbox=w.bbox()))
                    continue
                control = control_from_tag(
                    w.text, sheet=page.sheet_number, page=page.page_number,
                    dictionary=legend_dict, bbox=w.bbox())
                if control:
                    controls.append(control)
                    continue
                if _KEYNOTE_RE.match(w.text.strip()):
                    keynote_plan_locations.setdefault(w.text.strip(), []).append(
                        {"sheet": page.sheet_number, "page": page.page_number,
                         "bbox": list(w.bbox())})
                duct = duct_from_size_callout(
                    w.text, sheet=page.sheet_number, page=page.page_number,
                    bbox=w.bbox())
                if duct:
                    duct_segments.append(duct)

    graph.air_devices = air_devices
    graph.dampers = dampers
    graph.controls = controls
    graph.duct_segments = duct_segments
    graph.rooms = list(rooms.values())

    # keynote association (P23): match plan keynote markers to the keynote list
    keynotes_by_sheet: dict[str, dict[str, str]] = {}
    for doc in documents:
        for page in doc.pages:
            if page.page_type == "MECHANICAL_GENERAL_NOTES":
                keynotes_by_sheet[page.sheet_number or ""] = _keynotes_from_notes_page(page)
    for num, locations in keynote_plan_locations.items():
        text = next((kt.get(num, "") for kt in keynotes_by_sheet.values() if num in kt), "")
        if text:
            note_id = f"K{num}"
            note = note_entity(note_id, text, sheet=locations[0]["sheet"],
                               page=locations[0]["page"])
            note["plan_locations"] = locations
            if note_id not in {n["id"] for n in graph.notes}:
                graph.notes.append(note)
            # relate the note to devices located on the same sheets
            device_ids = {d["id"] for d in graph.air_devices
                          if d.get("source", {}).get("sheet") in
                          {loc["sheet"] for loc in locations}}
            for device_id in sorted(device_ids):
                graph.relate(note_id, device_id, "HAS_NOTE",
                             evidence=[{"kind": "KEYNOTE_MARKER",
                                        "location": locations[0]}])

    # relationships
    _relate_equipment_rooms(graph)
    _relate_devices_to_rooms(graph)
    _relate_notes_to_entities(graph)

    # systems
    for equipment in graph.equipment:
        graph.systems.append({
            "kind": "system", "id": f"SYS-{equipment['id']}",
            "system_type": "SUPPLY_AIR", "equipment_reference": equipment["id"],
            "devices_served": [
                d["device_id"] for d in graph.air_devices
                if _room_of(d) and _equipment_serves_room(equipment, _room_of(d))
            ],
            "source": equipment.get("source"),
            "confidence": "HIGH",
        })

    # design totals + conflicts
    graph.design_totals = _compute_supply_totals(graph)
    graph.conflicts = _compute_conflicts(graph)

    # plan-packet context review items
    for item in graph.missing_context:
        graph.review_items.append({**item, "review": "PARTIAL_PLAN_CONTEXT"})
    for damper in graph.dampers:
        if damper.get("confidence") == "GENERIC_SYMBOL_INFERENCE":
            graph.review_items.append({
                "kind": "SYMBOL_REVIEW_REQUIRED",
                "entity_id": damper["id"],
                "detail": "symbol identity inferred without project legend",
            })

    graph.validate()
    return graph


def _room_of(device: dict[str, Any]) -> str | None:
    return (device.get("room") or "").upper() or None


def _equipment_serves_room(equipment: dict[str, Any], room: str) -> bool:
    area = " ".join([
        str(equipment.get("scheduled_fields", {}).get("REMARKS") or ""),
        str(equipment.get("equipment_type") or ""),
    ]).upper()
    return room in area


def _relate_equipment_rooms(graph: MechanicalPlanGraph) -> None:
    for equipment in graph.equipment:
        area = str(equipment.get("scheduled_fields", {}).get("REMARKS") or "").upper()
        for room in graph.rooms:
            if room["name"].upper() in area:
                graph.relate(equipment["id"], room["id"], "SERVES",
                             evidence=[{"kind": "SCHEDULE_REMARKS",
                                        "text": area}],
                             source_ref=equipment.get("source"))


def _relate_devices_to_rooms(graph: MechanicalPlanGraph) -> None:
    for device in graph.air_devices:
        room = _room_of(device)
        if room:
            graph.relate(device["id"], room, "LOCATED_IN",
                         evidence=[{"kind": "PLAN_SPATIAL"}])


def _relate_notes_to_entities(graph: MechanicalPlanGraph) -> None:
    entity_ids = {e["id"] for e in graph.equipment + graph.dampers + graph.controls}
    for note in graph.notes:
        text = note.get("literal_text", "").upper()
        for entity_id in entity_ids:
            if re.search(r"\b" + re.escape(entity_id) + r"\b", text):
                graph.relate(note["id"], entity_id, "HAS_NOTE",
                             evidence=[{"kind": "ENTITY_MENTION", "text": text[:80]}])


def _compute_supply_totals(graph: MechanicalPlanGraph) -> list[dict[str, Any]]:
    room_func: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for device in graph.air_devices:
        room = _room_of(device)
        if not room:
            continue
        func = plans._function_of(device)
        room_func.setdefault((room, func), []).append(device)
    totals = []
    for (room, func), devices in sorted(room_func.items()):
        total = sum(d["design_cfm"] for d in devices if d.get("design_cfm"))
        totals.append({
            "scope": room, "function": func,
            "method": "SUM_DEVICE_DESIGN_CFMS",
            "design_total_cfm": total if total else None,
            "device_count": len(devices),
            "source_sheets": sorted({d["source"].get("sheet") for d in devices
                                     if d["source"].get("sheet")}),
        })
    return totals


def _compute_conflicts(graph: MechanicalPlanGraph) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    supply_totals = {t["scope"]: t for t in graph.design_totals
                     if t["function"] == "SUPPLY"}
    for equipment in graph.equipment:
        fields = equipment.get("scheduled_fields", {})
        supply = plans._num(fields.get("SUPPLY_CFM") or fields.get("supply_cfm"))
        remarks = str(fields.get("REMARKS") or "").upper()
        if not supply:
            continue
        match = next((t for scope, t in supply_totals.items() if scope in remarks),
                     None)
        if match and match["design_total_cfm"] is not None:
            diff = match["design_total_cfm"] - supply
            if abs(diff) > 1:
                conflicts.append({
                    "kind": "DESIGN_DOCUMENT_CONFLICT",
                    "detail": (
                        f"{equipment['id']} scheduled supply {supply:.0f} CFM vs "
                        f"sum of devices {match['design_total_cfm']:.0f} CFM "
                        f"({'%.0f' % diff} CFM difference)"),
                    "competing_sources": [
                        {"value": supply, "source": "EQUIPMENT_SCHEDULE"},
                        {"value": match["design_total_cfm"], "source": "AIR_DEVICE_SUM"},
                    ],
                    "source": equipment.get("source"),
                })
    return conflicts


# ---------------------------------------------------------------------------
# Graph -> DesignBasis (single downstream path)
# ---------------------------------------------------------------------------


def graph_to_design_basis(graph: MechanicalPlanGraph) -> dict[str, Any]:
    """Compact report/field-facing representation, derived from the graph."""
    equipment = [
        {
            "tag": e["id"],
            "type": e.get("equipment_type"),
            "manufacturer": e.get("manufacturer"),
            "model": e.get("model"),
            "supply_cfm": plans._num(e.get("scheduled_fields", {}).get("SUPPLY_CFM")),
            "esp": plans._num(e.get("scheduled_fields", {}).get("ESP")),
            "fan_rpm": plans._num(e.get("scheduled_fields", {}).get("FAN_RPM")),
            "motor_hp": plans._num(e.get("scheduled_fields", {}).get("MOTOR_HP")),
            "vfd": e.get("scheduled_fields", {}).get("VFD"),
            "oa_cfm": plans._num(e.get("scheduled_fields", {}).get("OUTSIDE_AIR_CFM")),
            "remarks": e.get("scheduled_fields", {}).get("REMARKS"),
            "source": e.get("source"),
        }
        for e in graph.equipment
    ]
    instances = [
        {
            "device_id": d.get("id") or d["device_id"],
            "room": (d.get("room") or "").title() or None,
            "design_cfm": d.get("design_cfm"),
            "size": d.get("size"),
            "function": plans._function_of(d),
            "source": d.get("source"),
        }
        for d in graph.air_devices
    ]
    return {
        "document": graph.packet.get("document") or {
            "document_id": graph.packet.get("packet_id"),
            "sha256": (graph.packet.get("document_hashes") or [None])[0],
        },
        "schedule_types": {},
        "equipment": equipment,
        "instances": instances,
        "rooms": graph.rooms,
        "design_totals": graph.design_totals,
        "conflicts": graph.conflicts,
        "sheet_classification": [
            {"page": s.get("page_number"), "sheet_number": s.get("sheet_number"),
             "title": s.get("sheet_title"), "type": s.get("page_type"),
             "confidence": s.get("confidence")}
            for s in graph.sheets
        ],
        "system_associations": [
            {"system_id": s.get("equipment_reference"),
             "equipment_reference": s.get("equipment_reference"),
             "devices_served": s.get("devices_served"),
             "confidence": s.get("confidence"),
             "evidence": [{"kind": "GRAPH"}]}
            for s in graph.systems if s.get("equipment_reference")
        ],
        "graph": graph.to_dict(),
    }
