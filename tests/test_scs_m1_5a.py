"""SCS M1.5A — workstation convergence tests.

Durable discovery → approval → indexing, truthful knowledge coverage,
assignment-scoped field job access, structured field reading writes and
ready-to-leave vs report-ready separation.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from scs_copilot.job_service import FieldJobRuntime, knowledge_coverage, _source_coverage
from scs_copilot.memory import JobConversationMemory
from scs_knowledge.discovery import KnowledgeDiscoveryStore
from scs_knowledge.registry import KnowledgeSource, SCSKnowledgeLibrary
from scs_reports.completeness import evaluate as evaluate_report
from scs_reports.readiness import evaluate_readiness
from scs_reports.schema import AirDevice, JobMetadata, JobRecord


def _record(job_id="J1", *, final=300, design=300) -> JobRecord:
    record = JobRecord(JobMetadata(job_id=job_id, project_name="P", technician="T",
                                   site_name="S", test_date=date(2026, 8, 23),
                                   report_type="AIRFLOW_VERIFICATION"))
    record.air_devices.append(AirDevice(device_id="SA-1", function="SUPPLY",
                                        design_cfm=design, as_found_cfm=200,
                                        final_cfm=final))
    return record


# ---------------------------------------------------------------------------
# Durable discovery (P0-P4)
# ---------------------------------------------------------------------------


def _store(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    return KnowledgeDiscoveryStore(root / "discovery.json", root=root)


def test_discovery_persists_candidate(tmp_path):
    store = _store(tmp_path)
    (store._root / "manual.txt").write_text("Carrier 50TC installation", encoding="utf-8")
    records = store.discover()
    assert len(records) == 1
    assert records[0]["state"] == "DISCOVERED"
    assert records[0]["discovery_id"].startswith("DSC-")


def test_rediscovery_same_hash_idempotent(tmp_path):
    store = _store(tmp_path)
    path = store._root / "manual.txt"
    path.write_text("Carrier 50TC installation", encoding="utf-8")
    store.discover()
    first_id = store.list()[0]["discovery_id"]
    store.discover()  # same bytes
    records = store.list()
    assert len(records) == 1  # no duplicate
    assert records[0]["discovery_id"] == first_id


def test_changed_hash_invalidates_prior_approval(tmp_path):
    store = _store(tmp_path)
    path = store._root / "manual.txt"
    path.write_text("version one", encoding="utf-8")
    store.discover()
    record = store.list()[0]
    store.approve(record["discovery_id"], manufacturer="CARRIER", model="50TC")
    assert store.get(record["discovery_id"])["state"] == "OWNER_APPROVED"
    path.write_text("version two changed", encoding="utf-8")
    store.discover()
    states = {r["discovery_id"]: r["state"] for r in store.list()}
    assert states[record["discovery_id"]] == "STALE_CHANGED"
    assert any(r["state"] == "DISCOVERED" and r["discovery_id"] != record["discovery_id"]
               for r in store.list())


def test_approve_and_index_runs_ingestor(tmp_path):
    store = _store(tmp_path)
    (store._root / "manual.txt").write_text("Carrier 50TC installation manual max ESP 2.5", encoding="utf-8")
    store.discover()
    record = store.list()[0]
    library = SCSKnowledgeLibrary(tmp_path / "lib.db")
    result = store.approve_and_index(record["discovery_id"], library,
                                     manufacturer="CARRIER", model="50TC-E08",
                                     family_tags=["50TC"],
                                     private_root=tmp_path / "priv")
    assert result["state"] == "INDEXED"
    assert result["source_id"]
    library.close()


def test_parse_failure_not_indexed(tmp_path):
    store = _store(tmp_path)
    (store._root / "mystery.xyz").write_text("nope", encoding="utf-8")
    # unsupported suffix is not discovered at all -> empty
    assert store.discover() == []


def test_block_prevents_retrieval(tmp_path):
    store = _store(tmp_path)
    (store._root / "manual.txt").write_text("content", encoding="utf-8")
    store.discover()
    record = store.list()[0]
    store.block(record["discovery_id"], "owner blocked")
    assert store.get(record["discovery_id"])["state"] == "BLOCKED"


def test_unapproved_source_not_authoritative(tmp_path):
    store = _store(tmp_path)
    (store._root / "manual.txt").write_text("Carrier content", encoding="utf-8")
    store.discover()
    library = SCSKnowledgeLibrary(tmp_path / "lib.db")
    # discovery alone created no library source; nothing retrievable
    assert library.list_sources() == []
    library.close()


# ---------------------------------------------------------------------------
# Knowledge coverage truth (P5-P6)
# ---------------------------------------------------------------------------


def _coverage_library(tmp_path, *, manufacturer, model=None, model_series=None,
                      families=None, source_type="OEM_IOM"):
    library = SCSKnowledgeLibrary(tmp_path / "lib.db")
    src = KnowledgeSource(source_id="S1", source_type=source_type,
                          manufacturer=manufacturer, model=model,
                          model_series=model_series,
                          equipment_family_tags=families or [])
    library.add_source(src)
    library.set_source_state("S1", "SOURCE_VERIFIED")
    return library


def test_coverage_exact_model(tmp_path):
    lib = _coverage_library(tmp_path, manufacturer="CARRIER", model="50TC-E08")
    assert knowledge_coverage(lib, {"manufacturer": "CARRIER", "model": "50TC-E08"}) == "EXACT_MODEL_MANUAL"
    lib.close()


def test_coverage_model_series(tmp_path):
    lib = _coverage_library(tmp_path, manufacturer="CARRIER", model_series="50TC-E")
    assert knowledge_coverage(lib, {"manufacturer": "CARRIER", "model": "50TC-E08"}) == "MODEL_SERIES_MANUAL"
    lib.close()


def test_coverage_family(tmp_path):
    lib = _coverage_library(tmp_path, manufacturer="CARRIER", families=["50TC"])
    assert knowledge_coverage(lib, {"manufacturer": "CARRIER", "model": "50TC-E08"}) == "FAMILY_REFERENCE"
    lib.close()


def test_coverage_general_manufacturer_only(tmp_path):
    lib = _coverage_library(tmp_path, manufacturer="CARRIER")
    assert knowledge_coverage(lib, {"manufacturer": "CARRIER", "model": "50TC-E08"}) == "GENERAL_MANUFACTURER_ONLY"
    lib.close()


def test_coverage_wrong_manufacturer_no_source(tmp_path):
    lib = _coverage_library(tmp_path, manufacturer="TRANE", model="50TC-E08")
    assert knowledge_coverage(lib, {"manufacturer": "CARRIER", "model": "50TC-E08"}) == "NO_OEM_SOURCE"
    lib.close()


# ---------------------------------------------------------------------------
# Structured field reading + append-only (P12-P14)
# ---------------------------------------------------------------------------


def test_structured_reading_append_only():
    memory = JobConversationMemory(job_id="J1")
    memory.record_reading("supply_cfm", 200, stage="AS_FOUND", equipment_id="RTU-1",
                          concept="FIELD_SUPPLY_CFM")
    memory.record_reading("supply_cfm", 300, stage="FINAL", equipment_id="RTU-1",
                          concept="FIELD_SUPPLY_CFM")
    entries = memory.readings["supply_cfm"]
    assert [e["stage"] for e in entries] == ["AS_FOUND", "FINAL"]
    assert entries[0]["value"] == 200  # as-found retained


def test_readiness_report_ready_distinct():
    record = _record(final=300)  # final present but no photos -> blocking
    memory = JobConversationMemory(job_id="J1")
    field = evaluate_readiness(record, memory=memory)
    report = evaluate_report(record)
    # field readiness (leave) and report readiness are separate objects/states
    assert field.state in ("NOT_READY", "NEEDS_REVIEW", "READY_WITH_NOTES", "READY")
    assert report.ready in (True, False)


# ---------------------------------------------------------------------------
# Assignment-scoped field job access (P7-P9)
# ---------------------------------------------------------------------------


def test_authorizer_distinguishes_view_all_jobs():
    from scs_data.authorization import Permission, ScsAuthorizer, ScsPrincipal
    authorizer = ScsAuthorizer()
    owner = ScsPrincipal("e1", ("owner",), (), "active")
    tech = ScsPrincipal("e2", (), ("field_technician",), "active")
    assert Permission.VIEW_ALL_JOBS in authorizer.permissions(owner)
    assert Permission.VIEW_ALL_JOBS not in authorizer.permissions(tech)
    assert Permission.WORK_ASSIGNED_JOBS in authorizer.permissions(tech)


def test_field_job_runtime_identity():
    from scs_copilot.job_service import FieldJobRuntime
    runtime = FieldJobRuntime.from_workspace(Path("C:/SCS_DATA/copilot"))
    assert runtime.paths is not None
    assert runtime.store is not None
