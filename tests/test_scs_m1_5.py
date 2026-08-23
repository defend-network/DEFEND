"""SCS M1.5 Field Workstation tests.

Covers the server-authoritative job truth packet, job-scoped copilot answer
contract, deterministic ready-to-leave engine, and owner knowledge
discovery/approval boundary.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from scs_copilot.job_service import build_job_truth_packet, knowledge_coverage, structured_answer
from scs_copilot.memory import JobConversationMemory
from scs_knowledge.discovery import (
    approve_source,
    block_source,
    discover_documents,
    inventory,
)
from scs_knowledge.registry import SCSKnowledgeLibrary
from scs_reports.readiness import READY_STATES, evaluate_readiness
from scs_reports.schema import AirDevice, JobMetadata, JobRecord


def _record(job_id="J1", *, as_found=None, final=None, design=None,
            devices=True) -> JobRecord:
    record = JobRecord(JobMetadata(job_id=job_id, project_name="P", technician="T",
                                   site_name="S", test_date=date(2026, 8, 23),
                                   report_type="AIRFLOW_VERIFICATION"))
    if devices:
        record.air_devices.append(AirDevice(
            device_id="SA-1", function="SUPPLY", design_cfm=design or 300,
            as_found_cfm=as_found, final_cfm=final))
    return record


# ---------------------------------------------------------------------------
# Job truth packet (P9)
# ---------------------------------------------------------------------------


def test_job_truth_packet_unknown_not_na():
    record = _record()
    packet = build_job_truth_packet(record, None, None, None)
    assert packet["job_id"] == "J1"
    assert packet["status"] == "UNKNOWN"  # never fabricated as N/A
    assert packet["site"] == "S"
    assert packet["air_devices"]


def test_job_truth_packet_includes_readings_and_open_measurements():
    record = _record(as_found=250, final=300)
    memory = JobConversationMemory(job_id="J1")
    memory.record_reading("SA-1:cfm", 300, stage="FINAL", equipment_id="SA-1")
    memory.record_open_measurement("fan rpm", "need fan RPM", entity_id="RTU-1")
    packet = build_job_truth_packet(record, None, memory, None)
    assert packet["readings"]
    assert "FAN_RPM" in packet["open_measurements"]


def test_knowledge_coverage_states():
    assert knowledge_coverage(None, {"id": "RTU-1"}) == "NO_OEM_SOURCE"
    assert knowledge_coverage(None, {"manufacturer": "CARRIER", "model": "50TC"}) == "NO_OEM_SOURCE"


# ---------------------------------------------------------------------------
# Structured answer contract (P10-P12)
# ---------------------------------------------------------------------------


def test_structured_answer_contract():
    raw = {
        "answer_id": "ANS-1", "answer": "visible", "copilot_mode": "DETERMINISTIC_FALLBACK",
        "verification": {"verified": [], "results": [],
                         "CLAIMS_BLOCKED": 1, "CLAIMS_DOWNGRADED": 0},
        "trace": {"tool_calls": [], "tool_result_ids": [], "quality": {}},
        "session_durable": False, "next_actions": [], "knowledge_gaps_open": 0,
    }
    memory = JobConversationMemory(job_id="J1")
    answer = structured_answer(raw, "J1", memory)
    assert answer["answer_id"] == "ANS-1"
    assert answer["job_id"] == "J1"
    assert answer["visible_answer"] == "visible"
    assert answer["blocked_claims"]["count"] == 1
    assert answer["session_durable"] is False


# ---------------------------------------------------------------------------
# Ready-to-leave engine (P20-P23)
# ---------------------------------------------------------------------------


def test_readiness_ready_when_complete():
    record = _record(as_found=250, final=300)
    # clear photos requirement by not having devices require photos is not
    # possible here, but a full record with finals should not block on devices
    result = evaluate_readiness(record, memory=JobConversationMemory(job_id="J1"))
    assert result.state in READY_STATES


def test_readiness_open_measurement_blocks():
    record = _record(as_found=250, final=300)
    memory = JobConversationMemory(job_id="J1")
    memory.record_open_measurement("fan rpm", "need fan RPM", entity_id="RTU-1")
    result = evaluate_readiness(record, memory=memory)
    assert result.state == "NOT_READY"
    assert any(r.key == "open_measurement:FAN_RPM" for r in result.blocking())


def test_readiness_incomplete_procedure_blocks():
    record = _record(as_found=250, final=300)
    memory = JobConversationMemory(job_id="J1")
    memory.active_procedures["vav_max_verification"] = {
        "procedure_id": "vav_max_verification", "steps": [
            {"step_id": "s1", "state": "NOT_STARTED"},
            {"step_id": "s2", "state": "COMPLETE"},
        ]}
    result = evaluate_readiness(record, memory=memory)
    assert result.state == "NOT_READY"
    assert any(r.key == "procedure:vav_max_verification" for r in result.blocking())


def test_readiness_unresolved_diagnostic_needs_review():
    record = _record(as_found=250, final=300)
    memory = JobConversationMemory(job_id="J1")
    memory.active_graphs["LOW_AIRFLOW"] = {
        "graph_id": "LOW_AIRFLOW",
        "causes": [{"cause_id": "c1", "belief": "SUPPORTED"}]}
    result = evaluate_readiness(record, memory=memory)
    assert "diagnostic:LOW_AIRFLOW" in [r.key for r in result.reasons]


def test_readiness_reasons_have_actions():
    record = _record(final=None)  # missing final -> blocking
    result = evaluate_readiness(record, memory=JobConversationMemory(job_id="J1"))
    assert result.state == "NOT_READY"
    assert any(r.action for r in result.blocking())


# ---------------------------------------------------------------------------
# Knowledge discovery + owner approval (P2-P6)
# ---------------------------------------------------------------------------


def test_discover_documents_is_discovered_not_authoritative(tmp_path):
    doc = tmp_path / "carrier manual.txt"
    doc.write_text("Carrier 50TC installation guide", encoding="utf-8")
    discovered = discover_documents(tmp_path)
    assert discovered
    assert discovered[0]["state"] == "DISCOVERED"
    assert discovered[0]["candidate_source_type"] == "OEM_IOM"


def test_discover_documents_ignores_library_db(tmp_path):
    (tmp_path / "library.db").write_bytes(b"sqlite-bytes")
    (tmp_path / "manual.txt").write_text("content", encoding="utf-8")
    discovered = discover_documents(tmp_path)
    assert all(d["filename"] != "library.db" for d in discovered)


def test_approval_boundary_physical_presence_not_authority(tmp_path):
    library = SCSKnowledgeLibrary(tmp_path / "lib.db")
    doc = tmp_path / "manual.txt"
    doc.write_text("Carrier 50TC max ESP 2.5", encoding="utf-8")
    from scs_knowledge.ingestor import ingest_file
    result = ingest_file(library, doc, private_root=tmp_path / "priv")
    # not authoritative until owner-approved
    assert library.get_source(result.source_id).source_state != "SOURCE_VERIFIED"
    approved = approve_source(library, result.source_id, manufacturer="CARRIER",
                              model="50TC-E08", equipment_family_tags=["50TC"])
    assert approved["ingestion_state"] == "OWNER_APPROVED"
    assert approved["source_state"] == "SOURCE_VERIFIED"
    assert approved["manufacturer"] == "CARRIER"


def test_block_source(tmp_path):
    library = SCSKnowledgeLibrary(tmp_path / "lib.db")
    doc = tmp_path / "manual.txt"
    doc.write_text("content", encoding="utf-8")
    from scs_knowledge.ingestor import ingest_file
    result = ingest_file(library, doc, private_root=tmp_path / "priv")
    blocked = block_source(library, result.source_id)
    assert blocked["ingestion_state"] == "BLOCKED"


def test_inventory_counts(tmp_path):
    library = SCSKnowledgeLibrary(tmp_path / "lib.db")
    doc = tmp_path / "manual.txt"
    doc.write_text("content", encoding="utf-8")
    from scs_knowledge.ingestor import ingest_file
    ingest_file(library, doc, private_root=tmp_path / "priv")
    inv = inventory(library)
    assert inv["documents"]
    assert inv["indexed"] >= 1
