"""SCS M1.4.3 Runtime Truth Certification tests (P0-P24 + adversarial matrix).

Reproduce the runtime/trust gaps the independent audit found and assert the
CORRECT behavior. These are the red/green tests for strict entity/concept
binding, provider-native tool continuation, concurrent durable memory,
idempotent seeding, canonical open measurements, answer history, and
diagnostic strength runtime wiring.
"""
from __future__ import annotations

import json
import threading
from datetime import date
from pathlib import Path

import pytest

from scs_copilot.agent import run_agent
from scs_copilot.answer_history import AnswerHistoryStore
from scs_copilot.claims import (
    ENTITY_CONFLICT,
    ENTITY_GLOBAL,
    ENTITY_UNRESOLVED,
    build_evidence,
    concept_key,
    entity_in_text,
    entity_relation,
    verify_claims,
)
from scs_copilot.context import SCSJobContext
from scs_copilot.memory import (
    COMPOSITE_COMPONENTS,
    JobConversationMemory,
    JobMemoryStore,
    canonical_measurement,
)
from scs_copilot.router import CopilotRouter
from scs_copilot.sessions import DiagnosticSession
from scs_copilot.tools import ToolRegistry
from scs_diagnostics.airflow import low_airflow_graph
from scs_knowledge.registry import KnowledgeSource, SCSKnowledgeLibrary
from scs_procedures.library import PROCEDURE_LIBRARY
from scs_reports.schema import AirDevice, JobMetadata, JobRecord


def _claim(**kw):
    base = {"claim_id": "C1", "claim_type": "NUMERIC", "concept": "CFM",
            "value": 2444, "unit": "CFM", "entity_id": None,
            "assertion_text": "2444 CFM", "evidence_refs": [],
            "calculator_ref": None, "source_refs": [], "inference": False,
            "applicability": "UNKNOWN", "confidence": "HIGH"}
    base.update(kw)
    return base


def _fact(**kw):
    base = {"evidence_id": "E1", "label": "FIELD", "concept": "CFM",
            "value": 2444, "unit": "CFM", "entity_id": None}
    base.update(kw)
    return base


def _context(job_id="J"):
    return SCSJobContext(job_id=job_id,
                         job=JobRecord(JobMetadata(job_id=job_id, project_name="P",
                                                   technician="T", site_name="S",
                                                   test_date=date(2026, 8, 24))))


# ---------------------------------------------------------------------------
# Phase - strict entity binding (P0-P2)
# ---------------------------------------------------------------------------


def test_entity_relation_semantics():
    assert entity_relation("RTU-5", "RTU-5") == "ENTITY_EXACT"
    assert entity_relation("RTU-5", "RTU-7") == ENTITY_CONFLICT
    assert entity_relation("RTU-5", None) == ENTITY_UNRESOLVED
    assert entity_relation(None, "RTU-7") == ENTITY_UNRESOLVED
    assert entity_relation(None, None) == ENTITY_GLOBAL


def test_claim_entity_missing_cannot_wildcard_rtu_evidence():
    claim = _claim(entity_id=None)
    fact = _fact(concept="FIELD_SUPPLY_CFM", entity_id="RTU-7")
    report = verify_claims([claim], build_evidence([fact]))
    assert report["CLAIMS_BLOCKED"] == 1


def test_evidence_entity_missing_cannot_verify_explicit_rtu_claim():
    claim = _claim(entity_id="RTU-5")
    fact = _fact(entity_id=None)
    report = verify_claims([claim], build_evidence([fact]))
    assert report["CLAIMS_BLOCKED"] == 1


def test_rtu5_value_cannot_verify_rtu7_claim():
    claim = _claim(entity_id="RTU-19", concept="FIELD_SUPPLY_CFM")
    fact = _fact(concept="FIELD_SUPPLY_CFM", entity_id="RTU-7")
    report = verify_claims([claim], build_evidence([fact]))
    assert report["CLAIMS_BLOCKED"] == 1


def test_prose_entity_extraction():
    assert entity_in_text("RTU-5 is delivering 2,444 CFM") == "RTU-5"
    assert entity_in_text("AHU-2 supply static is 0.31") == "AHU-2"
    assert entity_in_text("VAV-17 min is 40%") == "VAV-17"
    assert entity_in_text("RTU-5000 does not exist") is None  # >3 digits
    assert entity_in_text("just airflow, no entity") is None


def test_ambiguous_entity_not_invented():
    from scs_copilot.claims import extract_claims_from_prose
    claims = extract_claims_from_prose("The airflow is 2444 CFM", build_evidence([]))
    assert claims[0]["entity_id"] is None  # no entity invented


# ---------------------------------------------------------------------------
# Phase - strict concept binding (P3-P5)
# ---------------------------------------------------------------------------


def test_supply_return_static_do_not_cross_verify():
    claim = _claim(concept="FIELD_SUPPLY_STATIC", value=0.31, unit="IN.W.C.",
                   entity_id="RTU-5")
    fact = _fact(concept="FIELD_RETURN_STATIC", value=0.31, unit="IN.W.C.",
                 entity_id="RTU-5")
    report = verify_claims([claim], build_evidence([fact]))
    assert report["CLAIMS_BLOCKED"] == 1


def test_filter_coil_dp_do_not_cross_verify():
    claim = _claim(concept="FILTER_DP", value=0.20, unit="IN.W.C.", entity_id="RTU-5")
    fact = _fact(concept="COIL_DP", value=0.20, unit="IN.W.C.", entity_id="RTU-5")
    report = verify_claims([claim], build_evidence([fact]))
    assert report["CLAIMS_BLOCKED"] == 1


def test_oa_supply_cfm_do_not_cross_verify():
    claim = _claim(concept="FIELD_OA_CFM", value=500, entity_id="RTU-5")
    fact = _fact(concept="FIELD_SUPPLY_CFM", value=500, entity_id="RTU-5")
    report = verify_claims([claim], build_evidence([fact]))
    assert report["CLAIMS_BLOCKED"] == 1


def test_design_field_cfm_do_not_cross_verify():
    claim = _claim(concept="DESIGN_SUPPLY_CFM", value=3900, entity_id="RTU-5")
    fact = _fact(concept="FIELD_SUPPLY_CFM", value=3900, entity_id="RTU-5")
    report = verify_claims([claim], build_evidence([fact]))
    assert report["CLAIMS_BLOCKED"] == 1


def test_same_concept_entity_unit_verifies():
    claim = _claim(concept="FIELD_SUPPLY_CFM", value=2444, entity_id="RTU-5")
    fact = _fact(concept="FIELD_SUPPLY_CFM", value=2444, entity_id="RTU-5")
    report = verify_claims([claim], build_evidence([fact]))
    assert report["CLAIMS_VERIFIED"] == 1


def test_concept_key_strictness():
    assert concept_key("FIELD_SUPPLY_STATIC") != concept_key("FIELD_RETURN_STATIC")
    assert concept_key("FILTER_DP") != concept_key("COIL_DP")
    assert concept_key("FIELD_OA_CFM") != concept_key("FIELD_SUPPLY_CFM")
    assert concept_key("DESIGN_SUPPLY_CFM") != concept_key("FIELD_SUPPLY_CFM")
    # explicit TESP alias still holds
    assert concept_key("TOTAL_EXTERNAL_STATIC_PRESSURE") == concept_key("TESP")


# ---------------------------------------------------------------------------
# Phase - OEM/standard applicability (P6-P7)
# ---------------------------------------------------------------------------


def test_exact_model_oem_claim_requires_applicability():
    claim = _claim(claim_type="OEM", concept="OEM_MAX_ESP", value=2.5, unit="IN.W.C.",
                   entity_id="50TC-E08", source_refs=["SRC-OEM1"],
                   applicability="EXACT_MODEL")
    evidence = {"oem_sources": {"SRC-OEM1"},
                "source_map": {"SRC-OEM1": {"source_type": "OEM_IOM",
                                            "source_id": "SRC-OEM1",
                                            "applicability": "FAMILY"}}}
    report = verify_claims([claim], evidence)
    assert report["CLAIMS_BLOCKED"] == 1
    assert any(r.get("reason") == "OEM_APPLICABILITY_INSUFFICIENT"
               for r in report["results"])


def test_family_source_cannot_become_exact_model():
    claim = _claim(claim_type="OEM", concept="OEM_MAX_ESP", value=2.5, unit="IN.W.C.",
                   entity_id="50TC-E08", source_refs=["SRC-OEM1"],
                   applicability="EXACT_MODEL")
    evidence = {"oem_sources": {"SRC-OEM1"},
                "source_map": {"SRC-OEM1": {"source_type": "OEM_CATALOG",
                                            "applicability": "GENERAL_MANUFACTURER"}}}
    report = verify_claims([claim], evidence)
    assert report["CLAIMS_BLOCKED"] == 1


def test_oem_claim_with_sufficient_applicability_verifies():
    claim = _claim(claim_type="OEM", concept="OEM_MAX_ESP", value=2.5, unit="IN.W.C.",
                   entity_id="50TC-E08", source_refs=["SRC-OEM1"],
                   applicability="MODEL_SERIES")
    evidence = {"oem_sources": {"SRC-OEM1"},
                "source_map": {"SRC-OEM1": {"source_type": "OEM_IOM",
                                            "applicability": "EXACT_MODEL",
                                            "model": "50TC-E08"}}}
    report = verify_claims([claim], evidence)
    assert report["CLAIMS_VERIFIED"] == 1


def test_standard_edition_claim_requires_edition():
    claim = _claim(claim_type="STANDARD", concept="STANDARD_REQUIREMENT",
                   value=10, edition="2026", source_refs=["SRC-NEBB1"])
    evidence = {"standard_sources": {"SRC-NEBB1"},
                "source_map": {"SRC-NEBB1": {"source_type": "STANDARD_NEBB",
                                             "edition": "2015"}}}
    report = verify_claims([claim], evidence)
    assert report["CLAIMS_BLOCKED"] == 1
    assert any(r.get("reason") == "STANDARD_EDITION_MISMATCH"
               for r in report["results"])


# ---------------------------------------------------------------------------
# Phase - provider-native tool continuation (P8-P9, P14-P22)
# ---------------------------------------------------------------------------


class ProtocolProvider:
    provider_name = "proto"
    privacy_class = "LOCAL_PRIVATE"

    def __init__(self, script):
        self.script = script
        self.index = 0
        self.messages_seen = []

    def complete(self, messages, *, tools=None, timeout=90.0):
        self.messages_seen.append(list(messages))
        response = self.script[min(self.index, len(self.script) - 1)]
        self.index += 1
        return {**response, "model": "m", "provider": "proto"}

    def tool_call_message(self, tool_calls):
        return {"role": "assistant", "content": None,
                "tool_calls": [{"function": {"name": tc["name"],
                                             "arguments": tc.get("arguments", {})},
                                "id": tc.get("id")} for tc in tool_calls]}

    def tool_result_message(self, tool_call_id, content):
        return {"role": "tool", "content": content,
                "tool_call_id": tool_call_id}


def test_provider_tool_call_id_preserved_and_evidence_id_separate():
    provider = ProtocolProvider([
        {"tool_calls": [{"name": "job.readings", "arguments": {}, "id": "PTC-1"}],
         "finish_reason": "tool_calls"},
        {"content": "done", "finish_reason": "stop"},
    ])
    registry = ToolRegistry(context=_context())
    answer = run_agent("what readings", provider=provider, registry=registry,
                       context=_context(), memory=None,
                       deterministic_router=CopilotRouter(context=_context()))
    calls = answer["trace"]["tool_calls"]
    assert calls[0]["provider_tool_call_id"] == "PTC-1"
    assert calls[0]["evidence_id"].startswith("EVID-")
    assert calls[0]["evidence_id"] != "PTC-1"


def test_tool_result_references_provider_tool_call_id():
    provider = ProtocolProvider([
        {"tool_calls": [{"name": "job.readings", "arguments": {}, "id": "PTC-9"}],
         "finish_reason": "tool_calls"},
        {"content": "done", "finish_reason": "stop"},
    ])
    registry = ToolRegistry(context=_context())
    run_agent("q", provider=provider, registry=registry, context=_context(),
              memory=None, deterministic_router=CopilotRouter(context=_context()))
    continuation = provider.messages_seen[-1]  # messages sent on the final call
    tool_results = [m for m in continuation if m.get("role") == "tool"]
    assert tool_results and tool_results[0].get("tool_call_id") == "PTC-9"


def test_two_sequential_tool_turns():
    provider = ProtocolProvider([
        {"tool_calls": [{"name": "job.readings", "arguments": {}, "id": "PTC-1"}],
         "finish_reason": "tool_calls"},
        {"tool_calls": [{"name": "job.photos", "arguments": {}, "id": "PTC-2"}],
         "finish_reason": "tool_calls"},
        {"content": "done", "finish_reason": "stop"},
    ])
    registry = ToolRegistry(context=_context())
    answer = run_agent("q", provider=provider, registry=registry, context=_context(),
                       memory=None, deterministic_router=CopilotRouter(context=_context()))
    names = [c["name"] for c in answer["trace"]["tool_calls"]]
    assert names == ["job.readings", "job.photos"]


def test_rejected_tool_result_still_returns_continuation():
    provider = ProtocolProvider([
        {"tool_calls": [{"name": "does.not.exist", "arguments": {}, "id": "PTC-X"}],
         "finish_reason": "tool_calls"},
        {"content": "that tool is invalid", "finish_reason": "stop"},
    ])
    registry = ToolRegistry(context=_context())
    answer = run_agent("q", provider=provider, registry=registry, context=_context(),
                       memory=None, deterministic_router=CopilotRouter(context=_context()))
    # provider continuation received a tool result (not a crash)
    assert provider.messages_seen[-1]
    assert not answer["trace"]["tool_calls"][0]["ok"]


def test_malformed_tool_args_rejected():
    registry = ToolRegistry()
    result = registry.execute("plan.query", {"equipment_id": 123})
    assert not result["ok"] and "must be" in result["error"]


# ---------------------------------------------------------------------------
# Phase - concurrent durable memory (P12-P14, P23-P32)
# ---------------------------------------------------------------------------


def test_two_stores_do_not_lose_updates(tmp_path):
    store_a = JobMemoryStore(tmp_path / "mem")
    store_b = JobMemoryStore(tmp_path / "mem")

    def write_a():
        store_a.update("JOB-1", lambda m: m.record_reading(
            "fan_rpm", 1130, stage="FINAL", equipment_id="RTU-5"))

    def write_b():
        store_b.update("JOB-1", lambda m: m.record_reading(
            "return_static", -0.48, stage="AS_FOUND", equipment_id="RTU-5"))

    t1 = threading.Thread(target=write_a)
    t2 = threading.Thread(target=write_b)
    t1.start(); t2.start(); t1.join(); t2.join()
    memory = store_a.load("JOB-1")
    assert memory.latest_reading("fan_rpm") == 1130
    assert memory.latest_reading("return_static") == -0.48


def test_twenty_concurrent_updates_retain_all_fields(tmp_path):
    store = JobMemoryStore(tmp_path / "mem")

    def write(i):
        store.update("JOB-1", lambda m: m.record_reading(
            f"reading_{i}", i, stage="AS_FOUND"))

    threads = [threading.Thread(target=write, args=(i,)) for i in range(20)]
    for t in threads: t.start()
    for t in threads: t.join()
    memory = store.load("JOB-1")
    assert sum(len(v) for v in memory.readings.values()) == 20


def test_memory_job_isolation(tmp_path):
    store = JobMemoryStore(tmp_path / "mem")
    store.update("JOB-A", lambda m: m.record_reading("cfm", 100, stage="AS_FOUND"))
    assert store.load("JOB-B").readings == {}


def _job_record_with_readings(device_id="RTU-5", as_found=3900, final=4850):
    record = JobRecord(JobMetadata(job_id="J", project_name="P", technician="T",
                                   site_name="S", test_date=date(2026, 8, 24)))
    device = AirDevice(device_id=device_id, function="SUPPLY", design_cfm=4850,
                       as_found_cfm=as_found, final_cfm=final)
    record.air_devices.append(device)
    return record


def test_seeding_same_job_record_idempotent(tmp_path):
    from tools.job_copilot import _seed_memory_from_job
    store = JobMemoryStore(tmp_path / "mem")
    memory = store.load("J")
    record = _job_record_with_readings()
    context = _context("J")
    for _ in range(10):
        _seed_memory_from_job(memory, record, context)
    key = "RTU-5:cfm"
    assert len(memory.readings[key]) == 2  # 1 AS_FOUND + 1 FINAL, not 20


def test_changed_job_record_creates_new_revision(tmp_path):
    from tools.job_copilot import _seed_memory_from_job
    store = JobMemoryStore(tmp_path / "mem")
    memory = store.load("J")
    context = _context("J")
    _seed_memory_from_job(memory, _job_record_with_readings(as_found=3900), context)
    _seed_memory_from_job(memory, _job_record_with_readings(as_found=4100), context)
    key = "RTU-5:cfm"
    as_found_entries = [e for e in memory.readings[key] if e["stage"] == "AS_FOUND"]
    assert len(as_found_entries) == 2  # changed value -> new revision
    assert as_found_entries[-1]["value"] == 4100
    assert as_found_entries[-1]["observed_at"] == "SOURCE_TIMESTAMP_UNKNOWN"
    assert as_found_entries[-1]["recorded_at"]  # server-derived ingestion time


def test_canonical_open_measurement_key_only():
    memory = JobConversationMemory()
    memory.record_open_measurement("fan rpm", "need fan RPM")
    assert "FAN_RPM" in memory.open_measurements
    assert "fan rpm" not in memory.open_measurements


def test_entity_scoped_open_measurement():
    memory = JobConversationMemory()
    memory.record_open_measurement("fan rpm", "need fan RPM", entity_id="RTU-5")
    # a different entity's RPM does NOT resolve RTU-5's request
    memory.record_reading("fan_rpm", 900, concept="FAN_RPM", equipment_id="RTU-7")
    assert memory.open_measurements["FAN_RPM"]["state"] == "OPEN"
    memory.record_reading("fan_rpm", 1130, concept="FAN_RPM", equipment_id="RTU-5")
    assert memory.open_measurements["FAN_RPM"]["state"] == "ANSWERED"


def test_static_split_needs_both_components():
    memory = JobConversationMemory()
    memory.record_open_measurement("static split", "need static split", entity_id="RTU-5")
    memory.record_reading("supply_static", 0.31, concept="FIELD_SUPPLY_STATIC",
                          equipment_id="RTU-5")
    assert memory.open_measurements["STATIC_SPLIT"]["state"] == "OPEN"  # only one side
    memory.record_reading("return_static", -0.48, concept="FIELD_RETURN_STATIC",
                          equipment_id="RTU-5")
    assert memory.open_measurements["STATIC_SPLIT"]["state"] == "ANSWERED"


def test_restart_reload(tmp_path):
    store = JobMemoryStore(tmp_path / "mem")
    store.update("J", lambda m: m.record_reading("fan_rpm", 1130, stage="FINAL"))
    store2 = JobMemoryStore(tmp_path / "mem")  # new instance == process restart
    assert store2.load("J").latest_reading("fan_rpm") == 1130


# ---------------------------------------------------------------------------
# Phase - answer history (P21, P33-P36)
# ---------------------------------------------------------------------------


def test_answer_history_concurrent_safe(tmp_path):
    store = AnswerHistoryStore(tmp_path / "answers")

    def write(i):
        store.append("J", {"answer_id": f"A{i}", "answer": f"safe {i}"})

    threads = [threading.Thread(target=write, args=(i,)) for i in range(20)]
    for t in threads: t.start()
    for t in threads: t.join()
    history = store.load("J")
    assert len(history) == 20


def test_answer_history_retains_verified_blocked_ids(tmp_path):
    store = AnswerHistoryStore(tmp_path / "answers")
    store.append("J", {"answer_id": "A1", "answer": "safe answer",
                       "verified_claim_ids": ["C1"], "blocked_claim_ids": ["C2"]})
    entry = store.load("J")[0]
    assert entry["verified_claim_ids"] == ["C1"]
    assert entry["blocked_claim_ids"] == ["C2"]
    assert "raw_reasoning" not in entry


# ---------------------------------------------------------------------------
# Phase - diagnostic strength runtime (P22-P23)
# ---------------------------------------------------------------------------


def test_diagnostic_strength_from_real_session():
    session = DiagnosticSession(low_airflow_graph(), job_id="J", entity="RTU-5")
    for _ in range(3):
        session.update_cause("low_fan_speed", "fan RPM 800 below design 1100",
                             supports=True, basis="field")
    facts = [{"evidence_id": "E1", "label": "DIAGNOSTIC", "concept": "DIAGNOSTIC",
              "value": session.graph_id, "diagnostic": session.to_dict()}]
    evidence = build_evidence(facts)
    assert evidence["diagnostic_support"] >= 2
    claim = {"claim_id": "C", "claim_type": "DIAGNOSTIC_INFERENCE",
             "concept": "DIAGNOSTIC", "value": "fan speed low", "inference": True}
    report = verify_claims([claim], evidence)
    assert report["verified"][0]["diagnostic_strength"] == "STRONGLY_SUPPORTED"


def test_diagnostic_contradiction_downgrades():
    session = DiagnosticSession(low_airflow_graph(), job_id="J")
    session.update_cause("return_side_restriction", "return static high",
                         supports=True, basis="field")
    session.update_cause("return_side_restriction", "return static actually low",
                         supports=False, basis="field")
    facts = [{"evidence_id": "E1", "label": "DIAGNOSTIC", "concept": "DIAGNOSTIC",
              "value": session.graph_id, "diagnostic": session.to_dict()}]
    evidence = build_evidence(facts)
    assert evidence["diagnostic_contradiction"] >= 1
    claim = {"claim_id": "C", "claim_type": "DIAGNOSTIC_INFERENCE",
             "concept": "DIAGNOSTIC", "value": "return restricted", "inference": True}
    report = verify_claims([claim], evidence)
    assert report["verified"][0]["diagnostic_strength"] == "CONTRADICTED"


# ---------------------------------------------------------------------------
# Phase - knowledge root / source (regression from M1.4.2)
# ---------------------------------------------------------------------------


def test_shared_knowledge_root_resolver(tmp_path, monkeypatch):
    monkeypatch.setenv("SCS_KNOWLEDGE_ROOT", str(tmp_path / "custom"))
    from scs_knowledge import resolve_knowledge_root
    root = resolve_knowledge_root(tmp_path / "default")
    assert root == (tmp_path / "custom").resolve()


def test_source_state_first_class():
    source = KnowledgeSource(source_id="S", source_type="OEM_IOM")
    assert source.source_state == "ACTIVE"


# ---------------------------------------------------------------------------
# M1.4.3A - entity-scoped open measurement fail-closed (P0-P3)
# ---------------------------------------------------------------------------


def test_entity_scoped_open_not_resolved_by_unscoped_reading():
    memory = JobConversationMemory()
    memory.record_open_measurement("fan rpm", "need fan RPM", entity_id="RTU-5")
    memory.record_reading("fan_rpm", 1130, concept="FAN_RPM", equipment_id=None)
    assert memory.open_measurements["FAN_RPM"]["state"] == "OPEN"


def test_entity_scoped_open_not_resolved_by_wrong_entity():
    memory = JobConversationMemory()
    memory.record_open_measurement("fan rpm", "need fan RPM", entity_id="RTU-5")
    memory.record_reading("fan_rpm", 1130, concept="FAN_RPM", equipment_id="RTU-7")
    assert memory.open_measurements["FAN_RPM"]["state"] == "OPEN"


def test_entity_scoped_open_resolved_by_exact_entity():
    memory = JobConversationMemory()
    memory.record_open_measurement("fan rpm", "need fan RPM", entity_id="RTU-5")
    memory.record_reading("fan_rpm", 1130, concept="FAN_RPM", equipment_id="RTU-5")
    assert memory.open_measurements["FAN_RPM"]["state"] == "ANSWERED"


def test_static_split_unscoped_component_does_not_resolve():
    memory = JobConversationMemory()
    memory.record_open_measurement("static split", "need static split", entity_id="RTU-5")
    memory.record_reading("supply_static", 0.31, concept="FIELD_SUPPLY_STATIC",
                          equipment_id=None)
    memory.record_reading("return_static", -0.48, concept="FIELD_RETURN_STATIC",
                          equipment_id="RTU-5")
    assert memory.open_measurements["STATIC_SPLIT"]["state"] == "OPEN"


def test_static_split_wrong_entity_component_does_not_resolve():
    memory = JobConversationMemory()
    memory.record_open_measurement("static split", "need static split", entity_id="RTU-5")
    memory.record_reading("supply_static", 0.31, concept="FIELD_SUPPLY_STATIC",
                          equipment_id="RTU-7")
    memory.record_reading("return_static", -0.48, concept="FIELD_RETURN_STATIC",
                          equipment_id="RTU-5")
    assert memory.open_measurements["STATIC_SPLIT"]["state"] == "OPEN"


def test_static_split_exact_entity_components_resolve():
    memory = JobConversationMemory()
    memory.record_open_measurement("static split", "need static split", entity_id="RTU-5")
    memory.record_reading("supply_static", 0.31, concept="FIELD_SUPPLY_STATIC",
                          equipment_id="RTU-5")
    memory.record_reading("return_static", -0.48, concept="FIELD_RETURN_STATIC",
                          equipment_id="RTU-5")
    assert memory.open_measurements["STATIC_SPLIT"]["state"] == "ANSWERED"


# ---------------------------------------------------------------------------
# M1.4.3A - standard edition fail-closed (P4-P5)
# ---------------------------------------------------------------------------


def _standard_claim(edition):
    return _claim(claim_type="STANDARD", concept="STANDARD_REQUIREMENT",
                  value=10, edition=edition, source_refs=["SRC-NEBB1"])


def _standard_evidence(source_edition):
    meta = {"source_type": "STANDARD_NEBB"}
    if source_edition is not None:
        meta["edition"] = source_edition
    return {"standard_sources": {"SRC-NEBB1"},
            "source_map": {"SRC-NEBB1": meta}}


def test_standard_edition_match_verifies():
    report = verify_claims([_standard_claim("2026")], _standard_evidence("2026"))
    assert report["CLAIMS_VERIFIED"] == 1


def test_standard_edition_mismatch_blocked():
    report = verify_claims([_standard_claim("2026")], _standard_evidence("2015"))
    assert report["CLAIMS_BLOCKED"] == 1
    assert any(r.get("reason") == "STANDARD_EDITION_MISMATCH"
               for r in report["results"])


def test_standard_edition_missing_blocked():
    report = verify_claims([_standard_claim("2026")], _standard_evidence(None))
    assert report["CLAIMS_BLOCKED"] == 1
    assert any(r.get("reason") == "STANDARD_EDITION_UNPROVEN"
               for r in report["results"])


def test_standard_edition_blank_blocked():
    report = verify_claims([_standard_claim("2026")], _standard_evidence(""))
    assert report["CLAIMS_BLOCKED"] == 1
    assert any(r.get("reason") == "STANDARD_EDITION_UNPROVEN"
               for r in report["results"])


def test_standard_no_edition_claim_governed_by_authority_only():
    claim = _claim(claim_type="STANDARD", concept="STANDARD_REQUIREMENT",
                   value=10, edition=None, source_refs=["SRC-NEBB1"])
    report = verify_claims([claim], _standard_evidence("2015"))
    assert report["CLAIMS_VERIFIED"] == 1  # no edition asserted, no edition gate


# ---------------------------------------------------------------------------
# M1.4.3A - OEM applicability fail-closed (P6-P8)
# ---------------------------------------------------------------------------


def _oem_claim(applicability="UNKNOWN", entity_id="50TC-E08"):
    return _claim(claim_type="OEM", concept="OEM_MAX_ESP", value=2.5, unit="IN.W.C.",
                  entity_id=entity_id, source_refs=["SRC-OEM1"],
                  applicability=applicability)


def _oem_evidence(source_applicability, **extra):
    meta = {"source_type": "OEM_IOM", "source_id": "SRC-OEM1",
            "applicability": source_applicability}
    meta.update(extra)
    return {"oem_sources": {"SRC-OEM1"},
            "source_map": {"SRC-OEM1": meta}}


def test_oem_model_specific_unknown_general_manufacturer_blocked():
    report = verify_claims([_oem_claim("UNKNOWN", "50TC-E08")],
                           _oem_evidence("GENERAL_MANUFACTURER"))
    assert report["CLAIMS_BLOCKED"] == 1


def test_oem_model_specific_unknown_family_passes():
    report = verify_claims([_oem_claim("UNKNOWN", "50TC-E08")],
                           _oem_evidence("FAMILY", equipment_family_tags=["50TC"]))
    assert report["CLAIMS_VERIFIED"] == 1


def test_oem_model_series_general_manufacturer_blocked():
    report = verify_claims([_oem_claim("MODEL_SERIES", "50TC-E08")],
                           _oem_evidence("GENERAL_MANUFACTURER"))
    assert report["CLAIMS_BLOCKED"] == 1


def test_oem_model_series_model_series_passes():
    report = verify_claims([_oem_claim("MODEL_SERIES", "50TC-E08")],
                           _oem_evidence("MODEL_SERIES", model="50TC-E"))
    assert report["CLAIMS_VERIFIED"] == 1


def test_oem_exact_model_family_blocked():
    report = verify_claims([_oem_claim("EXACT_MODEL", "50TC-E08")],
                           _oem_evidence("FAMILY"))
    assert report["CLAIMS_BLOCKED"] == 1


def test_oem_exact_model_exact_model_passes():
    report = verify_claims([_oem_claim("EXACT_MODEL", "50TC-E08")],
                           _oem_evidence("EXACT_MODEL", model="50TC-E08"))
    assert report["CLAIMS_VERIFIED"] == 1


def test_oem_generic_no_entity_general_manufacturer_passes():
    claim = _claim(claim_type="OEM", concept="OEM_REQUIREMENT", value=None,
                   entity_id=None, source_refs=["SRC-OEM1"], applicability="UNKNOWN")
    report = verify_claims([claim], _oem_evidence("GENERAL_MANUFACTURER"))
    assert report["CLAIMS_VERIFIED"] == 1


# ---------------------------------------------------------------------------
# M1.4.3A - deterministic session durability truthfulness (P11)
# ---------------------------------------------------------------------------


def test_deterministic_session_durability_flag_truthful():
    from scs_copilot.agent import _materialize_deterministic_session
    from scs_copilot.tools import ToolRegistry
    # no memory backing -> NOT durable, even though procedure.start succeeds
    registry = ToolRegistry(context=_context(), procedures=PROCEDURE_LIBRARY)
    pre_route = {"tool": "procedure.start",
                 "procedure": {"procedure_id": "vav_max_verification"}}
    answer = {}
    _materialize_deterministic_session(pre_route, registry, answer)
    assert answer.get("session_durable") is False
    # a failing registry (no procedures) must not claim durability
    empty_registry = ToolRegistry(context=_context())
    answer2 = {}
    _materialize_deterministic_session(pre_route, empty_registry, answer2)
    assert answer2.get("session_durable") is False


# ---------------------------------------------------------------------------
# M1.4.3B - symmetric applicability normalization + fail-closed (defect 1)
# ---------------------------------------------------------------------------


def test_claim_exact_applicability_alias_family_source_blocked():
    report = verify_claims([_oem_claim("EXACT_APPLICABILITY", "50TC-E08")],
                           _oem_evidence("FAMILY", equipment_family_tags=["50TC"]))
    assert report["CLAIMS_BLOCKED"] == 1


def test_claim_exact_applicability_alias_exact_model_passes():
    report = verify_claims([_oem_claim("EXACT_APPLICABILITY", "50TC-E08")],
                           _oem_evidence("EXACT_MODEL", model="50TC-E08"))
    assert report["CLAIMS_VERIFIED"] == 1


def test_claim_model_prefix_general_manufacturer_blocked():
    report = verify_claims([_oem_claim("MODEL_PREFIX", "50TC-E08")],
                           _oem_evidence("GENERAL_MANUFACTURER"))
    assert report["CLAIMS_BLOCKED"] == 1


def test_claim_model_prefix_model_series_passes():
    report = verify_claims([_oem_claim("MODEL_PREFIX", "50TC-E08")],
                           _oem_evidence("MODEL_SERIES", model="50TC-E"))
    assert report["CLAIMS_VERIFIED"] == 1


def test_unrecognized_claim_applicability_blocked():
    report = verify_claims([_oem_claim("TOTALLY_UNKNOWN_SCOPE", "50TC-E08")],
                           _oem_evidence("EXACT_MODEL", model="50TC-E08"))
    assert report["CLAIMS_BLOCKED"] == 1
    assert any(r.get("reason") == "APPLICABILITY_UNRECOGNIZED"
               for r in report["results"])


def test_unrecognized_source_applicability_blocked():
    report = verify_claims([_oem_claim("FAMILY", "50TC-E08")],
                           _oem_evidence("TOTALLY_UNKNOWN_SCOPE",
                                         equipment_family_tags=["50TC"]))
    assert report["CLAIMS_BLOCKED"] == 1
    assert any(r.get("reason") == "APPLICABILITY_UNRECOGNIZED"
               for r in report["results"])


# ---------------------------------------------------------------------------
# M1.4.3B - family / model_series identity coverage (defect 2)
# ---------------------------------------------------------------------------


def test_family_source_correct_family_passes():
    report = verify_claims([_oem_claim("FAMILY", "50TC-E08")],
                           _oem_evidence("FAMILY", manufacturer="CARRIER",
                                         equipment_family_tags=["50TC"]))
    assert report["CLAIMS_VERIFIED"] == 1


def test_family_source_unrelated_family_blocked():
    report = verify_claims([_oem_claim("FAMILY", "50TC-E08")],
                           _oem_evidence("FAMILY", manufacturer="CARRIER",
                                         equipment_family_tags=["48TC"]))
    assert report["CLAIMS_BLOCKED"] == 1
    assert any(r.get("reason") == "APPLICABILITY_UNPROVEN"
               for r in report["results"])


def test_family_source_no_identity_blocked():
    report = verify_claims([_oem_claim("FAMILY", "50TC-E08")],
                           _oem_evidence("FAMILY", manufacturer="CARRIER"))
    assert report["CLAIMS_BLOCKED"] == 1
    assert any(r.get("reason") == "APPLICABILITY_UNPROVEN"
               for r in report["results"])


def test_model_series_source_covering_series_passes():
    report = verify_claims([_oem_claim("MODEL_SERIES", "50TC-E08")],
                           _oem_evidence("MODEL_SERIES", model="50TC-E"))
    assert report["CLAIMS_VERIFIED"] == 1


def test_model_series_source_unrelated_series_blocked():
    report = verify_claims([_oem_claim("MODEL_SERIES", "50TC-E08")],
                           _oem_evidence("MODEL_SERIES", model="48TC-E"))
    assert report["CLAIMS_BLOCKED"] == 1
    assert any(r.get("reason") == "APPLICABILITY_UNPROVEN"
               for r in report["results"])


def test_exact_model_gate_continues():
    report = verify_claims([_oem_claim("EXACT_MODEL", "50TC-E08")],
                           _oem_evidence("EXACT_MODEL", model="50TC-E08"))
    assert report["CLAIMS_VERIFIED"] == 1
    report = verify_claims([_oem_claim("EXACT_MODEL", "50TC-E08")],
                           _oem_evidence("EXACT_MODEL", model="50TC-E080"))
    assert report["CLAIMS_BLOCKED"] == 1


# ---------------------------------------------------------------------------
# M1.4.3B - session_durable requires memory backing (defect 3)
# ---------------------------------------------------------------------------


def test_session_durable_procedure_with_memory_backing():
    from scs_copilot.agent import _materialize_deterministic_session
    from scs_copilot.memory import JobConversationMemory
    registry = ToolRegistry(context=_context(), procedures=PROCEDURE_LIBRARY,
                            memory=JobConversationMemory(job_id="J"))
    pre_route = {"tool": "procedure.start",
                 "procedure": {"procedure_id": "vav_max_verification"}}
    answer = {}
    _materialize_deterministic_session(pre_route, registry, answer)
    assert answer.get("session_durable") is True


def test_session_durable_diagnostic_with_memory_backing():
    from scs_copilot.agent import _materialize_deterministic_session
    from scs_copilot.memory import JobConversationMemory
    registry = ToolRegistry(context=_context(), diagnostics={"LOW_AIRFLOW": low_airflow_graph()},
                            memory=JobConversationMemory(job_id="J"))
    pre_route = {"tool": "diagnostic.start", "graph": {"graph_id": "LOW_AIRFLOW"}}
    answer = {}
    _materialize_deterministic_session(pre_route, registry, answer)
    assert answer.get("session_durable") is True


def test_session_durable_procedure_without_memory_false():
    from scs_copilot.agent import _materialize_deterministic_session
    registry = ToolRegistry(context=_context(), procedures=PROCEDURE_LIBRARY)
    pre_route = {"tool": "procedure.start",
                 "procedure": {"procedure_id": "vav_max_verification"}}
    answer = {}
    _materialize_deterministic_session(pre_route, registry, answer)
    assert answer.get("session_durable") is False


def test_session_durable_failed_start_false():
    from scs_copilot.agent import _materialize_deterministic_session
    from scs_copilot.memory import JobConversationMemory
    registry = ToolRegistry(context=_context(), procedures=PROCEDURE_LIBRARY,
                            memory=JobConversationMemory(job_id="J"))
    pre_route = {"tool": "procedure.start",
                 "procedure": {"procedure_id": "does_not_exist"}}
    answer = {}
    _materialize_deterministic_session(pre_route, registry, answer)
    assert answer.get("session_durable") is False
