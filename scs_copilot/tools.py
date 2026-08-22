"""Server-side tool registry for the agent loop (M1.4, P0-P7, H2).

The reasoning model may REQUEST a tool; the server validates the tool name,
schema, argument types, job scope and side-effect class before execution. The
model cannot invent tools or raise its own permissions. Deterministic
calculators remain authoritative for numerics.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from scs_engineering.calculators import CALCULATORS, run_calculator
from scs_knowledge.sources import SourceAuthorityContext


class ToolRegistry:
    def __init__(self, context=None, knowledge=None, gaps=None,
                 procedures=None, diagnostics=None, instruments=None,
                 resolver=None) -> None:
        self.context = context
        self.knowledge = knowledge
        self.gaps = gaps
        self.procedures = procedures or {}
        self.diagnostics = diagnostics or {}
        self.instruments = instruments or {}
        self.resolver = resolver
        self.authority = SourceAuthorityContext()
        self._executed: list[dict[str, Any]] = []

    # ---- tool schemas (server-defined) -------------------------------------

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "plan.query",
                "description": "Query design facts for an equipment tag from the mechanical plan graph.",
                "parameters": {"type": "object", "properties": {"equipment_id": {"type": "string"}},
                               "required": ["equipment_id"]}}},
            {"type": "function", "function": {"name": "job.readings",
                "description": "List recorded field readings (as-found/intermediate/final).",
                "parameters": {"type": "object", "properties": {}}}},
            {"type": "function", "function": {"name": "job.missing",
                "description": "What is still missing before leaving site, from the job scope.",
                "parameters": {"type": "object", "properties": {}}}},
            {"type": "function", "function": {"name": "job.photos",
                "description": "List job photos/evidence.", "parameters": {"type": "object", "properties": {}}}},
            {"type": "function", "function": {"name": "calculator.run",
                "description": "Run a deterministic engineering calculator.",
                "parameters": {"type": "object", "properties": {
                    "name": {"type": "string", "enum": sorted(CALCULATORS)},
                    "inputs": {"type": "object"}}, "required": ["name"]}}},
            {"type": "function", "function": {"name": "knowledge.search",
                "description": "Search the private knowledge library.",
                "parameters": {"type": "object", "properties": {
                    "query": {"type": "string"}, "source_type": {"type": "string"}},
                    "required": ["query"]}}},
            {"type": "function", "function": {"name": "knowledge.fetch",
                "description": "Fetch a knowledge source by id.",
                "parameters": {"type": "object", "properties": {"source_id": {"type": "string"}},
                               "required": ["source_id"]}}},
            {"type": "function", "function": {"name": "equipment.resolve",
                "description": "Conservatively resolve equipment identity.",
                "parameters": {"type": "object", "properties": {"model": {"type": "string"}}}}},
            {"type": "function", "function": {"name": "instrument.lookup",
                "description": "Look up a registered instrument profile.",
                "parameters": {"type": "object", "properties": {"model": {"type": "string"},
                                                               "capability": {"type": "string"}}}}},
            {"type": "function", "function": {"name": "procedure.start",
                "description": "Start a structured TAB procedure.",
                "parameters": {"type": "object", "properties": {"procedure_id": {"type": "string"}},
                               "required": ["procedure_id"]}}},
            {"type": "function", "function": {"name": "procedure.update",
                "description": "Advance a procedure step.",
                "parameters": {"type": "object", "properties": {
                    "procedure_id": {"type": "string"}, "step_id": {"type": "string"},
                    "state": {"type": "string"}}, "required": ["procedure_id", "step_id", "state"]}}},
            {"type": "function", "function": {"name": "diagnostic.start",
                "description": "Start a diagnostic graph.",
                "parameters": {"type": "object", "properties": {"graph_id": {"type": "string"}},
                               "required": ["graph_id"]}}},
            {"type": "function", "function": {"name": "diagnostic.update",
                "description": "Record an observation into the active diagnostic.",
                "parameters": {"type": "object", "properties": {
                    "graph_id": {"type": "string"}, "key": {"type": "string"},
                    "value": {"type": ["number", "string"]}}, "required": ["graph_id", "key"]}}},
            {"type": "function", "function": {"name": "report.status",
                "description": "Report generation/validation status.",
                "parameters": {"type": "object", "properties": {}}}},
        ]

    # ---- validation + execution --------------------------------------------

    def validate(self, name: str, arguments: Any) -> str | None:
        names = {s["function"]["name"] for s in self.schemas()}
        if name not in names:
            return f"unknown tool: {name}"
        if name.startswith("calculator."):
            pass
        if not isinstance(arguments, dict):
            return "arguments must be an object"
        return None

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        error = self.validate(name, arguments)
        if error:
            return {"ok": False, "tool": name, "error": error,
                    "side_effect": "none"}
        handler: Callable[[dict[str, Any]], dict[str, Any]] = getattr(
            self, "_exec_" + name.replace(".", "_"), None)
        if handler is None:
            return {"ok": False, "tool": name, "error": "no server handler"}
        result = handler(arguments or {})
        self._executed.append({"tool": name, "arguments": arguments,
                               "ok": result.get("ok", True)})
        return result

    # ---- tool handlers ------------------------------------------------------

    def _exec_plan_query(self, args):
        equipment_id = args.get("equipment_id")
        if self.context is None or not equipment_id:
            return {"ok": False, "tool": "plan.query", "error": "missing equipment_id or job context"}
        equipment = self.context.equipment_from_graph(equipment_id)
        if equipment is None:
            return {"ok": True, "tool": "plan.query", "data": {"equipment_id": equipment_id,
                    "design": None, "note": "not found in plan graph"}}
        fields = equipment.get("scheduled_fields", {})
        return {"ok": True, "tool": "plan.query", "data": {
            "equipment_id": equipment_id, "design": fields,
            "source": equipment.get("source")}}

    def _exec_job_readings(self, args):
        readings = (self.context.readings if self.context else {})
        return {"ok": True, "tool": "job.readings", "data": readings}

    def _exec_job_missing(self, args):
        if self.context is None:
            return {"ok": True, "tool": "job.missing", "data": []}
        from scs_reports.plan_scope import ready_to_leave_graph
        graph = self.context.graph
        record = self.context.job
        if graph is None or record is None:
            return {"ok": True, "tool": "job.missing", "data": []}
        report = ready_to_leave_graph(graph, record)
        return {"ok": True, "tool": "job.missing", "data": report}

    def _exec_job_photos(self, args):
        return {"ok": True, "tool": "job.photos",
                "data": [p for p in (self.context.photos if self.context else [])]}

    def _exec_calculator_run(self, args):
        result = run_calculator(args.get("name", ""), **(args.get("inputs") or {}))
        return {"ok": result.get("computable", False) is not False,
                "tool": "calculator.run", "data": result}

    def _exec_knowledge_search(self, args):
        if self.knowledge is None:
            return {"ok": True, "tool": "knowledge.search", "data": [],
                    "note": "knowledge library not configured"}
        results = self.knowledge.search(args.get("query", ""),
                                        source_type=args.get("source_type"))
        return {"ok": True, "tool": "knowledge.search", "data": results}

    def _exec_knowledge_fetch(self, args):
        if self.knowledge is None:
            return {"ok": False, "tool": "knowledge.fetch", "error": "no library"}
        source = self.knowledge.get_source(args.get("source_id", ""))
        return {"ok": source is not None, "tool": "knowledge.fetch",
                "data": source.to_dict() if source else None}

    def _exec_equipment_resolve(self, args):
        from scs_equipment.resolver import resolve_equipment
        identity = resolve_equipment(model=args.get("model"))
        return {"ok": True, "tool": "equipment.resolve", "data": identity}

    def _exec_instrument_lookup(self, args):
        matches = []
        for profile in self.instruments.values():
            model = args.get("model")
            capability = args.get("capability")
            if model and model.lower() in profile.get("model", "").lower():
                matches.append(profile)
            elif capability and capability.lower() in profile.get("capabilities", "").lower():
                matches.append(profile)
        if not matches and self.gaps:
            self.gaps.detect("INSTRUMENT_MANUAL_MISSING",
                             detail=args.get("model") or args.get("capability") or "")
        return {"ok": True, "tool": "instrument.lookup",
                "data": matches or [],
                "note": "INSTRUMENT_MANUAL_MISSING" if not matches else None}

    def _exec_procedure_start(self, args):
        procedure = self.procedures.get(args.get("procedure_id"))
        if procedure is None:
            return {"ok": False, "tool": "procedure.start",
                    "error": f"procedure {args.get('procedure_id')} not available"}
        return {"ok": True, "tool": "procedure.start", "data": procedure.to_dict()}

    def _exec_procedure_update(self, args):
        procedure = self.procedures.get(args.get("procedure_id"))
        if procedure is None:
            return {"ok": False, "tool": "procedure.update", "error": "unknown procedure"}
        step = next((s for s in procedure.steps if s.step_id == args.get("step_id")), None)
        if step is None:
            return {"ok": False, "tool": "procedure.update", "error": "unknown step"}
        step.set_state(args.get("state", "COMPLETE"))
        return {"ok": True, "tool": "procedure.update",
                "data": {"step": step.step_id, "state": step.state,
                         "next": procedure.current_step().step_id
                         if procedure.current_step() else None}}

    def _exec_diagnostic_start(self, args):
        graph = self.diagnostics.get(args.get("graph_id"))
        if graph is None:
            return {"ok": False, "tool": "diagnostic.start", "error": "unknown graph"}
        return {"ok": True, "tool": "diagnostic.start", "data": graph.to_dict()}

    def _exec_diagnostic_update(self, args):
        graph = self.diagnostics.get(args.get("graph_id"))
        if graph is None:
            return {"ok": False, "tool": "diagnostic.update", "error": "unknown graph"}
        graph.record_observation(args.get("key"), args.get("value"), "field")
        return {"ok": True, "tool": "diagnostic.update", "data": graph.to_dict()}

    def _exec_report_status(self, args):
        return {"ok": True, "tool": "report.status", "data": self.context.report_state
                if self.context else {}}
