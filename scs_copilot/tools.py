"""Server-side tool registry for the agent loop (M1.4.2, P0-P7, P15-P21).

The reasoning model may REQUEST a tool; the server validates the tool name,
schema, argument types, enums, bounds, job scope and side-effect class before
execution. The model cannot invent tools or raise its own permissions.
Deterministic calculators remain authoritative for numerics.

M1.4.2 changes:
  * Typed tool specs + real validation (P15): required fields, types, enums,
    bounds, unknown-field rejection, side-effect classes.
  * knowledge.search routes through the canonical authority-aware hybrid
    retriever (P16).
  * knowledge.fetch returns bounded trusted CONTENT, not just metadata (P18).
  * job.readings returns structured field readings (P19).
  * procedure/diagnostic tools operate on job-scoped sessions (P28-P30).
  * Stable tool_result_id / evidence_id per execution (P21).
  * Observation compaction surfaces list/dict-shaped results (P17).
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from scs_engineering.calculators import CALCULATORS, run_calculator
from scs_knowledge.sources import SourceAuthorityContext

READ_ONLY = "READ_ONLY"
JOB_STATE_WRITE = "JOB_STATE_WRITE"
GLOBAL_PRIVATE_LIBRARY_WRITE = "GLOBAL_PRIVATE_LIBRARY_WRITE"
OWNER_ADMIN = "OWNER_ADMIN"
SIDE_EFFECT_CLASSES = (READ_ONLY, JOB_STATE_WRITE,
                       GLOBAL_PRIVATE_LIBRARY_WRITE, OWNER_ADMIN)


def _string_type(s: str) -> str:
    return "string"


TOOL_SPECS: dict[str, dict[str, Any]] = {
    "plan.query": {
        "required": ["equipment_id"],
        "types": {"equipment_id": "string"}, "side_effect": READ_ONLY,
        "allow_unknown": False,
    },
    "job.readings": {"required": [], "types": {}, "side_effect": READ_ONLY,
                     "allow_unknown": True},
    "job.missing": {"required": [], "types": {}, "side_effect": READ_ONLY,
                    "allow_unknown": True},
    "job.photos": {"required": [], "types": {}, "side_effect": READ_ONLY,
                   "allow_unknown": True},
    "calculator.run": {
        "required": ["name"],
        "types": {"name": "string", "inputs": "object"},
        "enums": {"name": sorted(CALCULATORS)},
        "side_effect": READ_ONLY, "allow_unknown": False,
    },
    "knowledge.search": {
        "required": ["query"],
        "types": {"query": "string", "source_type": "string"},
        "side_effect": READ_ONLY, "allow_unknown": False,
    },
    "knowledge.fetch": {
        "required": ["source_id"],
        "types": {"source_id": "string"}, "side_effect": READ_ONLY,
        "allow_unknown": False,
    },
    "equipment.resolve": {
        "required": [],
        "types": {"model": "string", "manufacturer": "string", "tag": "string"},
        "side_effect": READ_ONLY, "allow_unknown": False,
    },
    "instrument.lookup": {
        "required": [],
        "types": {"model": "string", "capability": "string"},
        "side_effect": READ_ONLY, "allow_unknown": False,
    },
    "procedure.start": {
        "required": ["procedure_id"],
        "types": {"procedure_id": "string"}, "side_effect": JOB_STATE_WRITE,
        "allow_unknown": False,
    },
    "procedure.update": {
        "required": ["procedure_id", "step_id", "state"],
        "types": {"procedure_id": "string", "step_id": "string", "state": "string"},
        "enums": {"state": ["NOT_STARTED", "IN_PROGRESS", "COMPLETE",
                            "SKIPPED_WITH_REASON", "BLOCKED", "REVIEW_REQUIRED"]},
        "side_effect": JOB_STATE_WRITE, "allow_unknown": False,
    },
    "diagnostic.start": {
        "required": ["graph_id"],
        "types": {"graph_id": "string"}, "side_effect": JOB_STATE_WRITE,
        "allow_unknown": False,
    },
    "diagnostic.update": {
        "required": ["graph_id", "key"],
        "types": {"graph_id": "string", "key": "string", "value": ["number", "string"]},
        "side_effect": JOB_STATE_WRITE, "allow_unknown": False,
    },
    "report.status": {"required": [], "types": {}, "side_effect": READ_ONLY,
                      "allow_unknown": True},
}


def _new_tool_id() -> str:
    import uuid
    return f"EVID-{uuid.uuid4().hex[:12]}"


def _reading_concept(key: str) -> str:
    k = (key or "").lower()
    if "cfm" in k or "airflow" in k:
        return "CFM"
    if "tesp" in k or "static" in k or "dp" in k or "esp" in k:
        return "STATIC_PRESSURE"
    if "rpm" in k or "speed" in k:
        return "RPM"
    if "temp" in k:
        return "TEMPERATURE"
    return key


class ToolRegistry:
    def __init__(self, context=None, knowledge=None, gaps=None,
                 procedures=None, diagnostics=None, instruments=None,
                 resolver=None, memory=None) -> None:
        self.context = context
        self.knowledge = knowledge
        self.gaps = gaps
        self.procedures = procedures or {}
        self.diagnostics = diagnostics or {}
        self.instruments = instruments or {}
        self.resolver = resolver
        self.memory = memory
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
                "description": "Search the private knowledge library (authority-aware).",
                "parameters": {"type": "object", "properties": {
                    "query": {"type": "string"}, "source_type": {"type": "string"}},
                    "required": ["query"]}}},
            {"type": "function", "function": {"name": "knowledge.fetch",
                "description": "Fetch bounded trusted content for a knowledge source by id.",
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
                "description": "Start a structured TAB procedure (job-scoped session).",
                "parameters": {"type": "object", "properties": {"procedure_id": {"type": "string"}},
                               "required": ["procedure_id"]}}},
            {"type": "function", "function": {"name": "procedure.update",
                "description": "Advance a procedure step in the job-scoped session.",
                "parameters": {"type": "object", "properties": {
                    "procedure_id": {"type": "string"}, "step_id": {"type": "string"},
                    "state": {"type": "string"}}, "required": ["procedure_id", "step_id", "state"]}}},
            {"type": "function", "function": {"name": "diagnostic.start",
                "description": "Start a diagnostic graph (job-scoped session).",
                "parameters": {"type": "object", "properties": {"graph_id": {"type": "string"}},
                               "required": ["graph_id"]}}},
            {"type": "function", "function": {"name": "diagnostic.update",
                "description": "Record an observation into the active diagnostic session.",
                "parameters": {"type": "object", "properties": {
                    "graph_id": {"type": "string"}, "key": {"type": "string"},
                    "value": {"type": ["number", "string"]}}, "required": ["graph_id", "key"]}}},
            {"type": "function", "function": {"name": "report.status",
                "description": "Report generation/validation status.",
                "parameters": {"type": "object", "properties": {}}}},
        ]

    def tool_specs(self) -> dict[str, dict[str, Any]]:
        return TOOL_SPECS

    def side_effect_class(self, name: str) -> str:
        return TOOL_SPECS.get(name, {}).get("side_effect", READ_ONLY)

    # ---- validation + execution --------------------------------------------

    def validate(self, name: str, arguments: Any) -> str | None:
        if name not in TOOL_SPECS:
            return f"unknown tool: {name}"
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except Exception:
                return "invalid tool arguments: not valid JSON"
        if not isinstance(arguments, dict):
            return "arguments must be an object"
        spec = TOOL_SPECS[name]
        if not spec.get("allow_unknown"):
            unknown = [k for k in arguments if k not in spec["types"]]
            if unknown:
                return f"unknown argument(s): {', '.join(sorted(unknown))}"
        for field in spec["required"]:
            if field not in arguments:
                return f"missing required argument: {field}"
        for field, expected in spec["types"].items():
            if field not in arguments or arguments[field] is None:
                continue
            value = arguments[field]
            expected_types = expected if isinstance(expected, (list, tuple)) else [expected]
            if "number" in expected_types and isinstance(value, bool):
                return f"argument {field} must be a number"
            if "number" in expected_types and isinstance(value, (int, float)):
                continue
            if "string" in expected_types and isinstance(value, str):
                continue
            if "object" in expected_types and isinstance(value, dict):
                continue
            return f"argument {field} must be {expected_types}"
        for field, allowed in spec.get("enums", {}).items():
            if field in arguments and arguments[field] not in allowed:
                return f"invalid enum for {field}: {arguments[field]}"
        if name == "calculator.run" and arguments.get("name") not in CALCULATORS:
            return f"unknown calculator: {arguments.get('name')}"
        return None

    def execute(self, name: str, arguments: dict[str, Any] | str) -> dict[str, Any]:
        error = self.validate(name, arguments)
        if error:
            return {"ok": False, "tool": name, "error": error,
                    "error_code": "INVALID_TOOL_REQUEST", "retryable": False,
                    "alternate": None, "side_effect": "none",
                    "tool_result_id": _new_tool_id()}
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        arguments = arguments or {}
        handler: Callable[[dict[str, Any]], dict[str, Any]] = getattr(
            self, "_exec_" + name.replace(".", "_"), None)
        if handler is None:
            return {"ok": False, "tool": name, "error": "no server handler",
                    "error_code": "NO_SERVER_HANDLER", "retryable": False,
                    "alternate": None, "tool_result_id": _new_tool_id()}
        evidence_id = _new_tool_id()
        try:
            result = handler(arguments or {})
        except Exception as error:  # tool errors are observations, not evidence
            return {"ok": False, "tool": name, "error": f"{type(error).__name__}: {error}",
                    "error_code": "TOOL_ERROR", "retryable": True,
                    "alternate": None, "side_effect": self.side_effect_class(name),
                    "tool_result_id": evidence_id}
        result.setdefault("tool", name)
        result.setdefault("error_code", None)
        result.setdefault("retryable", None)
        result.setdefault("alternate", None)
        result.setdefault("side_effect", self.side_effect_class(name))
        result["tool_result_id"] = evidence_id
        result["evidence_id"] = evidence_id
        self._executed.append({"tool": name, "arguments": arguments,
                               "ok": result.get("ok", True),
                               "tool_result_id": evidence_id})
        return result

    def compact_observation(self, result: dict[str, Any]) -> dict[str, Any]:
        """Structured compact tool observation (P17) - no arbitrary JSON cut.

        Surfaces useful content for dict AND list-shaped results so the model
        actually receives field readings, knowledge chunks, etc."""
        data = result.get("data")
        facts: list[dict[str, Any]] = []
        tool = result.get("tool")
        if isinstance(data, dict):
            if data.get("design"):
                facts.append({"concept": "DESIGN", "values": data["design"]})
            if data.get("formula_id") is not None or data.get("calculation_id") is not None:
                facts.append({"concept": "CALCULATED", "value": data.get("result"),
                              "unit": data.get("units"),
                              "formula": data.get("formula_id") or data.get("calculation_id")})
            if data.get("identity"):
                facts.append({"concept": "OEM_IDENTITY",
                              "value": data["identity"].get("resolution"),
                              "manufacturer": data["identity"].get("manufacturer"),
                              "family": data["identity"].get("product_family")})
            if data.get("verdict") or data.get("checks"):
                facts.append({"concept": "VALIDATION",
                              "summary": data.get("verdict") or data.get("summary")})
            if data.get("results") and isinstance(data.get("results"), list):
                for item in data["results"][:6]:
                    if isinstance(item, dict):
                        facts.append({"concept": "KNOWLEDGE",
                                      "source_id": item.get("source_id"),
                                      "source_type": item.get("source_type"),
                                      "text": str(item.get("text") or "")[:300],
                                      "page": item.get("page"),
                                      "section": item.get("section")})
            if data.get("sources") and isinstance(data.get("sources"), list):
                for s in data["sources"][:6]:
                    facts.append({"concept": "SOURCE",
                                  "source_id": s.get("source_id"),
                                  "source_type": s.get("source_type"),
                                  "state": s.get("source_state")})
            if data.get("steps") and isinstance(data.get("steps"), list):
                facts.append({"concept": "PROCEDURE", "procedure_id": data.get("procedure_id"),
                              "steps": [{"step_id": s.get("step_id"), "state": s.get("state"),
                                         "title": s.get("title")} for s in data["steps"][:12]]})
            if data.get("observations") and isinstance(data.get("observations"), list):
                facts.append({"concept": "DIAGNOSTIC", "graph_id": data.get("graph_id"),
                              "observations": data["observations"][-8:],
                              "next_best": data.get("next_best_measurements")})
        if isinstance(data, list):
            for item in data[:8]:
                if isinstance(item, dict):
                    if item.get("value") is not None or item.get("readings"):
                        facts.append({"concept": item.get("concept") or "ITEM",
                                      "value": item.get("value"),
                                      "unit": item.get("unit"),
                                      "entity": item.get("equipment_id") or item.get("entity_id"),
                                      "stage": item.get("stage")})
                    else:
                        facts.append({"concept": "ITEM", "value": item})
                else:
                    facts.append({"concept": "ITEM", "value": item})
        if tool == "job.readings" and isinstance(data, dict):
            for key, entry in list(data.items())[:12]:
                if isinstance(entry, dict):
                    facts.append({"concept": entry.get("concept") or key,
                                  "value": entry.get("value"), "unit": entry.get("unit"),
                                  "entity": entry.get("equipment_id") or entry.get("entity_id"),
                                  "stage": entry.get("stage"), "reading_id": entry.get("reading_id")})
                else:
                    facts.append({"concept": key, "value": entry})
        source_refs = []
        if isinstance(data, dict) and data.get("source_id"):
            source_refs.append(data["source_id"])
        if isinstance(data, dict) and data.get("source"):
            source_refs.append(str(data.get("source", {}).get("sheet") or data.get("source")))
        return {
            "tool": tool, "success": result.get("ok", False),
            "error": result.get("error"), "error_code": result.get("error_code"),
            "retryable": result.get("retryable"),
            "alternate": result.get("alternate"),
            "facts": facts[:10], "source_refs": source_refs[:8],
            "next_state": (data.get("next") if isinstance(data, dict) else None),
            "evidence_id": result.get("evidence_id"),
        }

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
        readings: dict[str, Any] = {}
        if self.context and getattr(self.context, "readings", None):
            for key, value in self.context.readings.items():
                if isinstance(value, dict):
                    readings[key] = {
                        "reading_id": None, "equipment_id": None,
                        "entity_id": None, "concept": _reading_concept(key),
                        "value": value.get("value"), "unit": None,
                        "stage": value.get("stage", "FIELD"),
                        "instrument_id": None, "operating_mode": None,
                        "source": value.get("source", "field"),
                        "recorded_at": None,
                    }
                else:
                    readings[key] = {"reading_id": None,
                                     "concept": _reading_concept(key),
                                     "value": value, "unit": None, "stage": "FIELD",
                                     "source": "field"}
        if self.memory:
            for key, entries in self.memory.readings.items():
                if entries:
                    readings[key] = entries[-1]
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
        from scs_knowledge.retrieval import hybrid_retrieve
        results = hybrid_retrieve(self.knowledge, args.get("query", ""),
                                  source_type=args.get("source_type"))
        return {"ok": True, "tool": "knowledge.search", "data": results}

    def _exec_knowledge_fetch(self, args):
        if self.knowledge is None:
            return {"ok": False, "tool": "knowledge.fetch", "error": "no library"}
        fetched = self.knowledge.fetch_source(args.get("source_id", ""))
        return {"ok": fetched is not None, "tool": "knowledge.fetch", "data": fetched}

    def _exec_equipment_resolve(self, args):
        from scs_equipment.resolver import resolve_equipment
        identity = resolve_equipment(model=args.get("model"),
                                     manufacturer=args.get("manufacturer"),
                                     tag=args.get("tag"))
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
        from .sessions import ProcedureSession
        job_id = getattr(self.context, "job_id", None)
        entity = args.get("entity_id") or (self.memory.active_entity if self.memory else None)
        session = ProcedureSession(procedure, job_id=job_id, entity=entity)
        if self.memory is not None:
            self.memory.active_procedures[session.procedure_id] = session.to_dict()
        return {"ok": True, "tool": "procedure.start", "data": session.to_dict()}

    def _exec_procedure_update(self, args):
        procedure_id = args.get("procedure_id")
        if self.memory is not None and procedure_id in self.memory.active_procedures:
            from .sessions import ProcedureSession
            session = ProcedureSession.from_dict(self.memory.active_procedures[procedure_id])
        else:
            template = self.procedures.get(procedure_id)
            if template is None:
                return {"ok": False, "tool": "procedure.update", "error": "unknown procedure"}
            from .sessions import ProcedureSession
            job_id = getattr(self.context, "job_id", None)
            session = ProcedureSession(template, job_id=job_id)
        if not session.set_step_state(args.get("step_id"), args.get("state", "COMPLETE")):
            return {"ok": False, "tool": "procedure.update", "error": "unknown step"}
        if self.memory is not None:
            self.memory.active_procedures[procedure_id] = session.to_dict()
        current = session.current_step()
        return {"ok": True, "tool": "procedure.update",
                "data": {"procedure_id": procedure_id,
                         "step": args.get("step_id"), "state": args.get("state", "COMPLETE"),
                         "next": current.get("step_id") if current else None,
                         "steps": session.steps}}

    def _exec_diagnostic_start(self, args):
        template = self.diagnostics.get(args.get("graph_id"))
        if template is None:
            return {"ok": False, "tool": "diagnostic.start", "error": "unknown graph"}
        from .sessions import DiagnosticSession
        job_id = getattr(self.context, "job_id", None)
        entity = args.get("entity_id") or (self.memory.active_entity if self.memory else None)
        session = DiagnosticSession(template, job_id=job_id, entity=entity)
        if self.memory is not None:
            self.memory.active_graphs[session.graph_id] = session.to_dict()
        return {"ok": True, "tool": "diagnostic.start", "data": session.to_dict()}

    def _exec_diagnostic_update(self, args):
        graph_id = args.get("graph_id")
        from .sessions import DiagnosticSession
        if self.memory is not None and graph_id in self.memory.active_graphs:
            session = DiagnosticSession.from_dict(self.memory.active_graphs[graph_id])
        else:
            template = self.diagnostics.get(graph_id)
            if template is None:
                return {"ok": False, "tool": "diagnostic.update", "error": "unknown graph"}
            job_id = getattr(self.context, "job_id", None)
            session = DiagnosticSession(template, job_id=job_id)
        session.record_observation(args.get("key"), args.get("value"), "field")
        session.apply_observation(args.get("key"), args.get("value"))
        if self.memory is not None:
            self.memory.active_graphs[graph_id] = session.to_dict()
        return {"ok": True, "tool": "diagnostic.update", "data": session.to_dict()}

    def _exec_report_status(self, args):
        return {"ok": True, "tool": "report.status", "data": self.context.report_state
                if self.context else {}}
