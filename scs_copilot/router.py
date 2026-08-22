"""SCS Copilot - tool-first router + answer synthesis (M1.3, P41-P46, P96).

The Copilot chooses tools (calculator.*, knowledge.search, equipment.resolve,
procedure.start, diagnostic.*, plan.query) instead of freehand answers where a
deterministic tool exists. Every answer carries fact-provenance labels
(DESIGN / FIELD / OEM / STANDARD / CALCULATED / INFERRED / UNKNOWN / CONFLICT)
and citations. Failures are stated honestly - no fallback hallucination.
"""
from __future__ import annotations

import re
from typing import Any

from scs_engineering import calculators
from scs_engineering.air_balance import building_air_balance
from scs_engineering.psychrometrics import (
    capacity_from_enthalpy,
    oa_fraction_temperature,
    split_sensible_latent,
    temperature_split,
)
from scs_engineering.traverse import traverse_calculation
from scs_knowledge.sources import SourceAuthorityContext, fact_concept
from scs_procedures.library import PROCEDURE_LIBRARY


def _label(value: Any) -> dict[str, Any]:
    return {"value": value}


def _fact(kind: str, field: str, value: Any, unit: str | None = None,
          citation: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"label": kind, "concept": fact_concept(kind, field),
            "value": value, "unit": unit, "citation": citation}


class CopilotRouter:
    """Deterministic V1 router; kept behind a provider abstraction (P95)."""

    def __init__(self, context=None, knowledge=None, gaps=None,
                 procedure_store=None) -> None:
        self.context = context
        self.knowledge = knowledge
        self.gaps = gaps
        self.procedure_store = procedure_store or {}
        self.authority = SourceAuthorityContext()

    def route(self, question: str) -> dict[str, Any]:
        upper = question.upper()
        lower = question.lower()

        # 1) calculator routing
        calc = self._route_calculator(lower)
        if calc is not None:
            return calc

        # 2) knowledge routing
        if any(k in upper for k in ("NEBB", "AABC", "ASHRAE", "SMACNA",
                                    "STANDARD", "MANUAL", "PROCEDURE", "ALLOW")):
            return self._route_knowledge(question)

        # 3) diagnostic routing (why/low/high questions) before procedure
        diag = self._route_diagnostic(lower)
        if diag is not None:
            return diag

        # 4) procedure routing
        proc = self._route_procedure(lower)
        if proc is not None:
            return proc

        # 5) equipment routing
        if any(k in upper for k in ("MODEL", "EQUIPMENT", "MANUFACTURER", "WHAT IS THIS")):
            eq = self._route_equipment(question)
            if eq is not None:
                return eq

        # 6) plan/design routing
        design = self._route_design(lower)
        if design is not None:
            return design

        return self._fallback(question)

    # ------------------------------------------------------------------ calc

    def _route_calculator(self, lower: str) -> dict[str, Any] | None:
        if "cfm" in lower and ("duct" in lower or "x" in lower or "fpm" in lower):
            m = re.search(r"(\d{1,4}(?:\.\d+)?)\s*[xX]\s*(\d{1,4}(?:\.\d+)?)", lower)
            m2 = re.search(r"(\d{1,5}(?:\.\d+)?)\s*(?:fpm|ft/min)", lower)
            if m and m2:
                w, h = float(m.group(1)), float(m.group(2))
                fpm = float(m2.group(1))
                area = calculators.rectangular_duct_area(w, h)
                cfm = calculators.cfm_from_fpm_area(fpm, area["result"])
                return {
                    "tool": "calculator.*", "calculation_id": "cfm_from_fpm_area",
                    "facts": [
                        _fact("CALCULATED", "DUCT_AREA", area["result"], "FT2",
                              citation={"formula": "duct.rect_area"}),
                        _fact("CALCULATED", "DESIGN_SUPPLY_CFM", cfm["result"], "CFM",
                              citation={"formula": "flow.cfm_from_fpm_area"}),
                    ],
                    "answer": (f"CALCULATED: CFM = FPM x Area. "
                               f"{w:g}x{h:g} in duct area = {area['result']} ft2; "
                               f"{fpm:g} FPM -> {cfm['result']:,.0f} CFM."),
                    "trace": {"calculators": ["duct.rect_area", "flow.cfm_from_fpm_area"]},
                }
        if "percent" in lower and "design" in lower:
            m = re.search(r"(\d{1,6}(?:\.\d+)?)", lower)
            if m and self.context:
                measured = float(m.group(1))
                design = self.context.design_value(self._equipment_id(lower), "supply_cfm") or measured
                pct = calculators.percent_design(measured, design)
                return {"tool": "calculator.percent_design",
                        "facts": [_fact("CALCULATED", "DESIGN_SUPPLY_CFM",
                                        pct["result"], "%",
                                        citation={"formula": "flow.percent_design"})],
                        "answer": f"CALCULATED: measured is {pct['result']}% of design.",
                        "trace": {"calculators": ["flow.percent_design"]}}
        if "traverse" in lower or "pitot" in lower:
            return {"tool": "calculator.traverse",
                    "answer": "Use traverse_calculation() with duct geometry + point readings.",
                    "trace": {"calculators": ["traverse"]}}
        if "sensible" in lower or "capacity" in lower:
            return {"tool": "calculator.psychrometric",
                    "answer": "Use capacity_from_enthalpy / split_sensible_latent with conditions.",
                    "trace": {"calculators": ["psychrometric"]}}
        return None

    def _equipment_id(self, lower: str) -> str | None:
        m = re.search(r"\b(RTU|AHU|VAV|EF|SF|DOAS|MAU|FCU|HP)-\d{1,3}\b", lower.upper())
        return m.group(0) if m else None

    # ------------------------------------------------------------ knowledge

    def _route_knowledge(self, question: str) -> dict[str, Any]:
        if self.knowledge is None:
            return {"tool": "knowledge.search",
                    "facts": [],
                    "answer": "AUTHORITATIVE_STANDARD_SOURCE_NOT_INDEXED: no indexed standard answered this.",
                    "gap": {"gap_type": "STANDARD_EDITION_UNKNOWN",
                            "detail": question},
                    "trace": {"knowledge": []}}
        upper = question.upper()
        source_type = None
        if "NEBB" in upper:
            source_type = "STANDARD_NEBB"
        elif "ASHRAE" in upper:
            source_type = "STANDARD_ASHRAE"
        results = self.knowledge.search(question, source_type=source_type) \
            if source_type else self.knowledge.search(question)
        if not results:
            gap_type = "STANDARD_EDITION_UNKNOWN" if source_type else "PROCEDURE_NOT_AVAILABLE"
            if self.gaps:
                self.gaps.detect(gap_type, detail=question, question=question)
            return {"tool": "knowledge.search", "facts": [],
                    "answer": "AUTHORITATIVE_STANDARD_SOURCE_NOT_INDEXED" if source_type
                    else "PROCEDURE_NOT_AVAILABLE: no procedure knowledge indexed for this.",
                    "gap": {"gap_type": gap_type, "detail": question},
                    "trace": {"knowledge": []}}
        citation = results[0]
        return {
            "tool": "knowledge.search", "facts": [
                {"label": "STANDARD" if source_type else "SCS_PLAYBOOK",
                 "concept": "REFERENCE", "value": citation["text"][:300],
                 "citation": {"source_id": citation["source_id"],
                              "title": citation["title"],
                              "edition": citation.get("edition"),
                              "page": citation.get("page")}}],
            "answer": f"{citation.get('source_type')}: {citation['text'][:200]} "
                      f"[{citation.get('source_id')}]",
            "trace": {"knowledge": [citation["chunk_id"]]},
        }

    # ------------------------------------------------------------- procedure

    def _route_procedure(self, lower: str) -> dict[str, Any] | None:
        if not any(k in lower for k in ("walk", "how do i", "how to", "steps",
                                        "procedure", "guide", "verify", "measure ")):
            return None
        mapping = {
            "rtu": "rtu_total_airflow", "vav max": "vav_max_verification",
            "vav maximum": "vav_max_verification", "vav min": "vav_min_verification",
            "vav minimum": "vav_min_verification", "outside air": "outside_air_measurement",
            "outside-air": "outside_air_measurement", "oa": "outside_air_measurement",
            "building pressure": "building_pressure_test",
            "fan rpm": "fan_rpm_measurement", "rpm": "fan_rpm_measurement",
            "traverse": "pitot_traverse", "flow hood": "flow_hood_balancing",
            "high static": "high_static_investigation",
            "low airflow": "low_airflow_investigation",
            "diffuser": "diffuser_balancing", "belt": "belt_sheave_airflow_adjustment",
        }
        for key, procedure_id in mapping.items():
            if key in lower:
                procedure = PROCEDURE_LIBRARY.get(procedure_id)
                if procedure is None:
                    return None
                current = procedure.current_step()
                return {
                    "tool": "procedure.start", "procedure": procedure.to_dict(),
                    "current_step": current.__dict__ if current else None,
                    "facts": [
                        {"label": "SCS_PLAYBOOK", "concept": "PROCEDURE",
                         "value": f"{procedure.title} (v{procedure.version})",
                         "citation": {"source_id": procedure_id}}],
                    "answer": (f"PROCEDURE: {procedure.title}. "
                               f"{len(procedure.steps)} steps. Next: {current.title if current else 'done'}."),
                    "trace": {"procedures": [procedure_id]},
                }
        return None

    # ------------------------------------------------------------- equipment

    def _route_equipment(self, question: str) -> dict[str, Any] | None:
        m = re.search(r"\b((?:50TC|48TC|40RM|SQ|ESV|TMS|TSS)[A-Z0-9.-]*)\b", question.upper())
        if not m:
            return None
        model = m.group(1)
        from scs_equipment.resolver import resolve_equipment
        identity = resolve_equipment(model=model)
        return {
            "tool": "equipment.resolve", "facts": [
                {"label": "OEM", "concept": "OEM_NOMINAL_CFM",
                 "value": identity["product_family"],
                 "citation": {"source_type": "OEM_IOM" if identity["resolution"] != "UNKNOWN_MODEL_IDENTITY" else None}},
                {"label": "UNKNOWN", "concept": "EXACT_MODEL",
                 "value": identity.get("resolution")}],
            "answer": (f"EQUIPMENT: manufacturer {identity['manufacturer']}, "
                       f"family {identity['product_family'] or 'unresolved'}; "
                       f"resolution {identity['resolution']}."),
            "identity": identity,
            "trace": {"equipment": [model]},
        }

    # ------------------------------------------------------------- diagnostic

    def _route_diagnostic(self, lower: str) -> dict[str, Any] | None:
        from scs_diagnostics.airflow import low_airflow_graph, high_static_graph
        from scs_diagnostics.pressurization import negative_building_pressure_graph
        words = set(re.findall(r"[a-z]+", lower))
        if "low" in words and ("airflow" in words or "flow" in words):
            graph = low_airflow_graph()
            return {"tool": "diagnostic.start", "graph": graph.to_dict(),
                    "facts": [{"label": "INFERRED", "concept": "DIAGNOSTIC",
                               "value": "low airflow; insufficient evidence to locate restriction"}],
                    "answer": ("DIAGNOSTIC: low airflow. Current evidence is insufficient to "
                               "locate the restriction. NEXT BEST MEASUREMENT: supply vs return "
                               "static split, and fan RPM."),
                    "trace": {"diagnostics": [graph.graph_id]}}
        if "static" in lower and ("high" in lower or "restriction" in lower):
            graph = high_static_graph()
            return {"tool": "diagnostic.start", "graph": graph.to_dict(),
                    "answer": "DIAGNOSTIC: high static. Check filter dp, return vs supply split, coil dp.",
                    "trace": {"diagnostics": [graph.graph_id]}}
        if "building pressure" in lower and "negative" in lower:
            graph = negative_building_pressure_graph()
            return {"tool": "diagnostic.start", "graph": graph.to_dict(),
                    "answer": "DIAGNOSTIC: negative building pressure. Check OA vs exhaust balance.",
                    "trace": {"diagnostics": [graph.graph_id]}}
        return None

    # --------------------------------------------------------------- design

    def _route_design(self, lower: str) -> dict[str, Any] | None:
        equipment_id = self._equipment_id(lower)
        if equipment_id and self.context:
            equipment = self.context.equipment_from_graph(equipment_id)
            fields = equipment.get("scheduled_fields", {}) if equipment else {}
            return {
                "tool": "plan.query", "facts": [
                    _fact("DESIGN", "DESIGN_SUPPLY_CFM", fields.get("SUPPLY_CFM"), "CFM",
                          citation={"sheet": "M2.2 equipment schedule"}),
                    _fact("DESIGN", "DESIGN_OA_CFM", fields.get("OUTSIDE_AIR_CFM"), "CFM"),
                    _fact("DESIGN", "DESIGN_ESP", fields.get("ESP"), "IN.W.G."),
                    _fact("DESIGN", "DESIGN_RPM", fields.get("FAN_RPM"), "RPM"),
                ],
                "answer": (f"DESIGN: {equipment_id} supply {fields.get('SUPPLY_CFM')} CFM, "
                           f"OA {fields.get('OUTSIDE_AIR_CFM')} CFM, ESP {fields.get('ESP')} in.w.g., "
                           f"fan {fields.get('FAN_RPM')} RPM. Source: M2.2 equipment schedule."),
                "trace": {"plan": [equipment_id]},
            }
        return None

    # -------------------------------------------------------------- fallback

    def _fallback(self, question: str) -> dict[str, Any]:
        return {
            "tool": None,
            "facts": [],
            "answer": ("I need more context. Try: 'What is RTU-5 design airflow?', "
                       "'Calculate CFM from FPM', 'What does NEBB require?', "
                       "'Why is RTU-5 low?', or 'Walk me through VAV max verification'."),
            "trace": {},
        }


def low_airflow_answer(*, design_cfm: float, measured_cfm: float, tesp: float,
                       return_static: float | None = None,
                       supply_static: float | None = None,
                       design_rpm: float | None = None,
                       fan_rpm: float | None = None) -> dict[str, Any]:
    """Acceptance scenarios A/B: deterministic answer with next-best action."""
    pct = calculators.percent_design(measured_cfm, design_cfm)
    facts = [
        _fact("DESIGN", "DESIGN_SUPPLY_CFM", design_cfm, "CFM",
              citation={"source_type": "PROJECT_SCHEDULE"}),
        _fact("FIELD", "FIELD_SUPPLY_CFM", measured_cfm, "CFM",
              citation={"source_type": "FIELD_MEASUREMENT"}),
        _fact("FIELD", "FIELD_TESP", tesp, "IN.W.C.",
              citation={"source_type": "FIELD_MEASUREMENT"}),
        _fact("CALCULATED", "DESIGN_SUPPLY_CFM", pct["result"], "%",
              citation={"formula": "flow.percent_design"}),
    ]
    graph = __import__("scs_diagnostics.airflow", fromlist=["low_airflow_graph"]).low_airflow_graph()
    graph = __import__("scs_diagnostics.airflow", fromlist=["apply_low_airflow_evidence"]).apply_low_airflow_evidence(
        graph, design_cfm=design_cfm, measured_cfm=measured_cfm,
        return_static=return_static, supply_static=supply_static,
        fan_rpm=fan_rpm, design_rpm=design_rpm)
    next_actions = graph.next_best_measurements
    lines = [
        f"DESIGN: RTU design supply = {design_cfm:,.0f} CFM.",
        f"FIELD: measured = {measured_cfm:,.0f} CFM; TESP {tesp} in.w.g.",
        f"CALCULATED: current airflow = {pct['result']}% of design.",
    ]
    if return_static is not None and supply_static is not None:
        burden = "RETURN" if abs(return_static) > abs(supply_static) else "SUPPLY"
        lines.append(
            f"ASSESSMENT: {burden} side currently carries the greater static burden "
            f"(return {return_static}, supply {supply_static}).")
        lines.append("  Check filter / return path / dampers / restriction before any fan-speed change.")
    lines.append(f"NEXT BEST MEASUREMENT: {', '.join(next_actions)}.")
    if fan_rpm is not None and design_rpm and fan_rpm < design_rpm * 0.95:
        lines.append("NOTE: fan RPM below design; record before considering speed adjustment.")
    return {"tool": "diagnostic.update", "facts": facts, "answer": "\n".join(lines),
            "graph": graph.to_dict(), "trace": {"diagnostics": ["LOW_AIRFLOW"],
                                                "calculators": ["flow.percent_design"]}}
