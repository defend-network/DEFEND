"""Server-authoritative job-scoped copilot service (M1.5, P9-P12).

The browser sends `{job_id, message}` only. The server owns job truth: it loads
the JobRecord, mechanical plan graph, durable conversation memory, design basis,
knowledge authority, procedures and diagnostics, then runs the trust-hardened
agent loop and returns a structured answer contract.

This is the canonical field-copilot entry point shared by the HTTP server and
the SCS API surface.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scs_copilot.agent import run_agent
from scs_copilot.context import SCSJobContext
from scs_copilot.memory import JobConversationMemory, JobMemoryStore
from scs_copilot.providers import build_copilot_provider
from scs_copilot.router import CopilotRouter
from scs_copilot.tools import ToolRegistry
from scs_diagnostics import airflow as diag_airflow
from scs_diagnostics import pressurization as diag_pressure
from scs_equipment.instruments import InstrumentRegistry
from scs_knowledge import resolve_knowledge_root
from scs_knowledge.gaps_lessons import (
    KnowledgeGapLog, OemResearchStore, SCSWeaknessRegistry)
from scs_knowledge.registry import SCSKnowledgeLibrary
from scs_procedures.library import PROCEDURE_LIBRARY
from scs_reports.completeness import evaluate
from scs_reports.plan_graph import MechanicalPlanGraph, Relationship
from scs_reports.schema import JobRecord
from scs_reports.store import JobStore, ReportPaths


def build_diagnostics() -> dict[str, Any]:
    return {
        "LOW_AIRFLOW": diag_airflow.low_airflow_graph(),
        "HIGH_STATIC": diag_airflow.high_static_graph(),
        "NEGATIVE_BUILDING_PRESSURE": diag_pressure.negative_building_pressure_graph(),
        "POSITIVE_BUILDING_PRESSURE": diag_pressure.positive_building_pressure_graph(),
        "BELT_SLIP": diag_airflow.belt_slip_graph(),
        "DIRTY_FILTER_OR_RETURN_RESTRICTION": diag_airflow.dirty_filter_graph(),
        "DUCT_RESTRICTION": diag_airflow.duct_restriction_graph(),
        "SENSOR_ERROR": diag_airflow.sensor_error_graph(),
        "CONTROL_MODE_ERROR": diag_airflow.control_mode_error_graph(),
        "ECONOMIZER_ERROR": diag_airflow.economizer_error_graph(),
        "INCORRECT_FAN_ROTATION": diag_airflow.fan_rotation_graph(),
        "LOW_OUTSIDE_AIR": diag_airflow.low_oa_graph(),
        "HIGH_OUTSIDE_AIR": diag_airflow.high_oa_graph(),
        "VAV_PICKUP_CALIBRATION": diag_airflow.vav_pickup_calibration_graph(),
    }


@dataclass
class FieldJobRuntime:
    """Loads the persisted field-copilot state for one job."""

    paths: ReportPaths
    store: JobStore

    @classmethod
    def from_workspace(cls, workspace: Path) -> "FieldJobRuntime":
        paths = ReportPaths(workspace).ensure()
        return cls(paths=paths, store=JobStore(paths))

    def load_job(self, job_id: str) -> JobRecord:
        return self.store.load(job_id)

    def load_graph(self, job_id: str) -> MechanicalPlanGraph | None:
        path = self.paths.job_dir(job_id) / "plan_graph.json"
        if not path.exists():
            return None
        import json
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        graph = MechanicalPlanGraph(packet={})
        for key, value in payload.items():
            if key == "relationships":
                graph.relationships = [
                    Relationship(r["source"], r["target"], r["rel_type"],
                                  r.get("evidence", []), r.get("confidence", "HIGH"),
                                  r.get("source_ref")) for r in value]
            elif key != "packet":
                setattr(graph, key, value)
        return graph

    def load_basis(self, job_id: str) -> dict[str, Any]:
        path = self.paths.job_dir(job_id) / "plan_basis.json"
        if not path.exists():
            return {}
        import json
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            return {}

    def memory_store(self, job_id: str) -> JobMemoryStore:
        return JobMemoryStore(self.paths.job_subdir(job_id, "memory"))

    def knowledge_dir(self) -> Path:
        return resolve_knowledge_root(self.paths.root)


def _seed_memory_from_job(memory: JobConversationMemory, record: JobRecord) -> None:
    for device in getattr(record, "air_devices", []) or []:
        device_id = getattr(device, "device_id", None)
        if not device_id:
            continue
        if getattr(device, "as_found_cfm", None) is not None:
            memory.record_reading(f"{device_id}:cfm", device.as_found_cfm,
                                  stage="AS_FOUND", equipment_id=device_id,
                                  source="job_record",
                                  source_key=f"JOB_RECORD:{device_id}:CFM:AS_FOUND",
                                  recorded_at="SOURCE_TIMESTAMP_UNKNOWN")
        if getattr(device, "final_cfm", None) is not None:
            memory.record_reading(f"{device_id}:cfm", device.final_cfm,
                                  stage="FINAL", equipment_id=device_id,
                                  source="job_record",
                                  source_key=f"JOB_RECORD:{device_id}:CFM:FINAL",
                                  recorded_at="SOURCE_TIMESTAMP_UNKNOWN")


def build_job_truth_packet(record: JobRecord, graph: MechanicalPlanGraph | None,
                           memory: JobConversationMemory | None,
                           knowledge: SCSKnowledgeLibrary | None) -> dict[str, Any]:
    """Server-authoritative job truth packet (P9). UNKNOWN stays UNKNOWN."""
    memory = memory or JobConversationMemory()
    metadata = record.metadata
    equipment = []
    if graph is not None:
        for item in graph.equipment:
            entry = dict(item)
            entry.setdefault("knowledge_coverage",
                             knowledge_coverage(knowledge, item))
            equipment.append(entry)
    for item in record.equipment:
        existing = next((e for e in equipment if e.get("id") == item.equipment_id
                         or e.get("equipment_id") == item.equipment_id), None)
        if existing is None:
            equipment.append({
                "id": item.equipment_id, "manufacturer": item.manufacturer,
                "model": item.model, "serial": item.serial,
                "area_served": item.area_served,
                "knowledge_coverage": knowledge_coverage(
                    knowledge, {"id": item.equipment_id,
                                "manufacturer": item.manufacturer,
                                "model": item.model}),
            })
    readings = {}
    for key, entries in memory.readings.items():
        readings[key] = [e for e in entries[-5:]]
    completeness = evaluate(record)
    return {
        "job_id": metadata.job_id,
        "job_type": metadata.report_type or "UNKNOWN",
        "status": "UNKNOWN",
        "site": metadata.site_name or "UNKNOWN",
        "technician": metadata.technician or "UNKNOWN",
        "test_date": metadata.test_date.isoformat() if metadata.test_date else "UNKNOWN",
        "equipment": equipment,
        "air_devices": [d.to_dict() for d in record.air_devices],
        "readings": readings,
        "open_measurements": {k: v for k, v in memory.open_measurements.items()
                              if v.get("state") == "OPEN"},
        "active_procedures": dict(memory.active_procedures),
        "active_diagnostics": dict(memory.active_graphs),
        "design_facts": {
            "equipment": (graph.to_dict().get("equipment", []) if graph else []),
        },
        "conflicts": (graph.to_dict().get("conflicts", []) if graph else []) or [],
        "missing_context": (graph.missing_context if graph else []) or [],
        "findings": [f.to_dict() for f in record.findings],
        "report_readiness": {
            "ready": completeness.ready,
            "summary": completeness.summary,
        },
    }


def knowledge_coverage(knowledge: SCSKnowledgeLibrary | None,
                       equipment: dict[str, Any]) -> str:
    """Knowledge coverage for one equipment entity (Phase 11)."""
    if knowledge is None:
        return "NO_OEM_SOURCE"
    manufacturer = (equipment.get("manufacturer") or "").strip()
    model = (equipment.get("model") or "").strip()
    if not manufacturer and not model:
        return "NO_OEM_SOURCE"
    exact = knowledge.search(f"{manufacturer} {model}", limit=3,
                             active_only=True) if model else []
    if any(r.get("source_type", "").startswith("OEM_") for r in exact):
        return "EXACT_MODEL_MANUAL"
    family = knowledge.search(f"{manufacturer} {model}", limit=3,
                              active_only=True)
    if any(r.get("source_type", "").startswith("OEM_") for r in family):
        return "MODEL_SERIES_MANUAL"
    manufacturer_hits = knowledge.search(manufacturer, limit=3,
                                         active_only=True) if manufacturer else []
    if any(r.get("source_type", "").startswith("OEM_") for r in manufacturer_hits):
        return "GENERAL_MANUFACTURER_ONLY"
    return "NO_OEM_SOURCE"


def _structured_citations(raw: dict[str, Any]) -> list[dict[str, Any]]:
    verified = raw.get("verification", {}).get("verified", []) or []
    citations = []
    for claim in verified:
        source_refs = claim.get("source_refs") or []
        if source_refs:
            citations.append({
                "claim_id": claim.get("claim_id"),
                "source_refs": source_refs,
                "concept": claim.get("concept"),
                "applicability": claim.get("applicability"),
                "edition": claim.get("edition"),
            })
    return citations


def structured_answer(raw: dict[str, Any], job_id: str,
                      memory: JobConversationMemory) -> dict[str, Any]:
    """P10-P12 structured answer contract. No chain-of-thought."""
    trace = raw.get("trace", {})
    verification = raw.get("verification", {})
    quality = trace.get("quality", {}) or {}
    blocked = [r for r in verification.get("results", [])
               if r.get("verdict") in ("BLOCKED", "DOWNGRADED")]
    return {
        "answer_id": raw.get("answer_id"),
        "job_id": job_id,
        "visible_answer": raw.get("answer"),
        "copilot_mode": raw.get("copilot_mode"),
        "verified_claims": verification.get("verified", []),
        "blocked_claims": {
            "count": verification.get("CLAIMS_BLOCKED", 0),
            "reasons": sorted({r.get("reason") or "UNSUPPORTED" for r in blocked}),
        },
        "citations": _structured_citations(raw),
        "tool_calls": [
            {"name": c.get("name"), "ok": c.get("ok")}
            for c in trace.get("tool_calls", [])
        ],
        "open_measurements": [
            {"concept": k, **v}
            for k, v in memory.open_measurements.items() if v.get("state") == "OPEN"
        ],
        "next_measurements": raw.get("next_actions") or [],
        "active_procedure": list(memory.active_procedures),
        "active_diagnostic": list(memory.active_graphs),
        "session_durable": bool(raw.get("session_durable")),
        "data_gaps": raw.get("knowledge_gaps_open"),
        "conflicts": [],
        "model": quality.get("model"),
        "provider": quality.get("provider"),
        "latency_ms": quality.get("provider_latency_ms"),
        "answer_state": "answered" if raw.get("answer") else "blocked",
    }


def run_job_scoped_copilot(runtime: FieldJobRuntime, job_id: str,
                           question: str, *, provider=None) -> dict[str, Any]:
    """Run the trust-hardened agent for a job and return the structured answer."""
    record = runtime.load_job(job_id)
    graph = runtime.load_graph(job_id)
    basis = runtime.load_basis(job_id)
    knowledge_dir = runtime.knowledge_dir()
    library = SCSKnowledgeLibrary(knowledge_dir / "library.db")
    gaps = KnowledgeGapLog(knowledge_dir / "gaps.json")
    weaknesses = SCSWeaknessRegistry(knowledge_dir / "weaknesses.json")
    research = OemResearchStore(knowledge_dir / "research.json")
    instruments = InstrumentRegistry(knowledge_dir / "instruments.json")

    context = SCSJobContext(job_id=job_id, job=record, graph=graph,
                            design_basis=basis,
                            missing_context=(graph.missing_context if graph else []) or [])

    memory_store = runtime.memory_store(job_id)
    memory = memory_store.load(job_id)
    _seed_memory_from_job(memory, record)

    registry = ToolRegistry(context=context, knowledge=library, gaps=gaps,
                            procedures=PROCEDURE_LIBRARY,
                            diagnostics=build_diagnostics(),
                            instruments=instruments.all(),
                            resolver=None, memory=memory)
    provider = provider or build_copilot_provider()
    deterministic = CopilotRouter(context=context, knowledge=library, gaps=gaps)
    raw = run_agent(question, provider=provider, registry=registry,
                    context=context, memory=memory,
                    deterministic_router=deterministic)
    memory_store.commit(job_id, memory)

    from scs_copilot.answer_history import AnswerHistoryStore
    AnswerHistoryStore(runtime.paths.job_subdir(job_id, "answers")).append(job_id, {
        "answer_id": raw.get("answer_id"), "question": question,
        "mode": raw.get("copilot_mode"), "answer": raw.get("answer"),
        "verified_claim_ids": raw.get("trace", {}).get("verified_claim_ids", []),
        "blocked_claim_ids": raw.get("trace", {}).get("blocked_claim_ids", []),
        "tool_execution_ids": raw.get("trace", {}).get("tool_result_ids", []),
        "tool_calls": raw.get("trace", {}).get("tool_calls", []),
        "source_ids": raw.get("trace", {}).get("source_ids", []),
        "calculator_ids": raw.get("trace", {}).get("calculator_ids", []),
        "provider": raw.get("trace", {}).get("quality", {}).get("provider"),
        "model": raw.get("trace", {}).get("quality", {}).get("model"),
        "policy_version": raw.get("trace", {}).get("system_policy_version"),
        "timestamp": raw.get("trace", {}).get("created_at"),
    })
    library.close()
    return structured_answer(raw, job_id, memory)
