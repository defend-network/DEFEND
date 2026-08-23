"""SCS M1.5B2 — exact-byte knowledge + field measurement semantics tests."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

from scs_copilot.concepts import (
    normalize_concept,
    normalize_measurement,
    scope_of,
)
from scs_copilot.memory import JobConversationMemory
from scs_knowledge.discovery import (
    ForbiddenTransition,
    KnowledgeDiscoveryStore,
    approve_source,
)
from scs_knowledge.registry import SCSKnowledgeLibrary


def _store(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("SCS_KNOWLEDGE_ROOT", str(root))
    return KnowledgeDiscoveryStore(root / "discovery.json", root=root)


def _discover(store, name="manual.txt", text="Carrier 50TC installation manual"):
    (store._root / name).write_text(text, encoding="utf-8")
    store.discover()
    return store.list()[0]


# ---------------------------------------------------------------------------
# Exact-byte snapshot authority (AUDIT-B2-01/02)
# ---------------------------------------------------------------------------


def test_approve_and_index_snapshot_sha_binds(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    record = _discover(store, text="Carrier 50TC installation manual max ESP 2.5")
    store.classify(record["discovery_id"])
    library = SCSKnowledgeLibrary(tmp_path / "lib.db")
    result = store.approve_and_index(record["discovery_id"], library,
                                     manufacturer="CARRIER", model="50TC-E08",
                                     private_root=tmp_path / "priv")
    assert result["state"] == "INDEXED"
    src = library.get_source(result["source_id"])
    assert src.document_hash == record["file_sha256"]  # indexed == discovery sha
    assert src.source_origin == "DISCOVERY_MANAGED"
    library.close()


def test_original_mutation_during_ingest_does_not_affect_snapshot(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    record = _discover(store, text="Carrier 50TC installation manual")
    store.classify(record["discovery_id"])
    library = SCSKnowledgeLibrary(tmp_path / "lib.db")
    import scs_knowledge.discovery as disc
    original = disc.ingest_file

    def mutating_ingest(library, path, **kw):
        (store._root / "manual.txt").write_text("MUTATED AFTER STAGING", encoding="utf-8")
        return original(library, path, **kw)

    disc.ingest_file = mutating_ingest
    try:
        result = store.approve_and_index(record["discovery_id"], library,
                                         private_root=tmp_path / "priv")
    finally:
        disc.ingest_file = original
        library.close()
    assert result["state"] == "INDEXED"
    lib2 = SCSKnowledgeLibrary(tmp_path / "lib.db")
    assert lib2.get_source(result["source_id"]).document_hash == record["file_sha256"]
    lib2.close()


def test_large_pdf_byte_binding(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
    from fixtures.make_blueprint import build_blueprint_m12
    pdf = store._root / "bp.pdf"
    build_blueprint_m12(pdf)
    store.discover()
    record = next(r for r in store.list() if r["filename"] == "bp.pdf")
    store.classify(record["discovery_id"], source_type="PROJECT_PLAN")
    library = SCSKnowledgeLibrary(tmp_path / "lib.db")
    result = store.approve_and_index(record["discovery_id"], library,
                                     private_root=tmp_path / "priv")
    assert result["state"] in ("INDEXED", "PARSE_FAILED")
    if result["state"] == "INDEXED":
        assert library.get_source(result["source_id"]).document_hash == record["file_sha256"]
    library.close()


def test_discovery_managed_source_rejects_legacy_approval(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    record = _discover(store, text="Carrier 50TC installation manual")
    store.classify(record["discovery_id"])
    library = SCSKnowledgeLibrary(tmp_path / "lib.db")
    result = store.approve_and_index(record["discovery_id"], library,
                                     manufacturer="CARRIER",
                                     private_root=tmp_path / "priv")
    assert result["state"] == "INDEXED"
    with pytest.raises(ForbiddenTransition):
        approve_source(library, result["source_id"], manufacturer="CARRIER")
    library.close()


# ---------------------------------------------------------------------------
# Measurement normalization (AUDIT-B2-04/05/06)
# ---------------------------------------------------------------------------


def test_pa_converted_numerically():
    result = normalize_measurement("FIELD_TESP", 100.0, "PA")
    assert result is not None
    assert result["canonical_unit"] == "IN.W.C."
    assert result["submitted_value"] == 100.0
    assert result["submitted_unit"] == "PA"
    assert math.isclose(result["canonical_value"], 100.0 / 249.089, rel_tol=1e-6)


def test_cfm_normalization_identity():
    result = normalize_measurement("FIELD_SUPPLY_CFM", 2444.0, "CFM")
    assert result["canonical_value"] == 2444.0
    assert result["canonical_unit"] == "CFM"


def test_inwg_label_normalized():
    result = normalize_measurement("FIELD_TESP", 0.5, "IN.W.G.")
    assert result["canonical_unit"] == "IN.W.C."
    assert result["canonical_value"] == 0.5  # synonymous unit, magnitude unchanged


def test_non_finite_rejected():
    assert normalize_measurement("FIELD_TESP", float("nan"), "PA") is None
    assert normalize_measurement("FIELD_TESP", float("inf"), "PA") is None
    assert normalize_measurement("FIELD_TESP", float("-inf"), "PA") is None


def test_unknown_unit_rejected():
    assert normalize_measurement("FIELD_TESP", 100.0, "M") is None
    assert normalize_measurement("FIELD_TESP", 100.0, "KPA") is None


def test_unknown_concept_rejected():
    assert normalize_concept("MADE_UP") is None


# ---------------------------------------------------------------------------
# Timestamp + canonical storage (AUDIT-B2-10/11)
# ---------------------------------------------------------------------------


def test_observed_and_recorded_separate():
    memory = JobConversationMemory(job_id="J1")
    entry = memory.record_reading("FIELD_SUPPLY_CFM", 300, stage="FINAL",
                                  equipment_id="RTU-1", concept="FIELD_SUPPLY_CFM",
                                  unit="CFM", entered_by="emp-1",
                                  observed_at="2026-08-23T08:00:00",
                                  submitted_value=300, submitted_unit="CFM",
                                  submitted_concept="SUPPLY_CFM")
    assert entry["observed_at"] == "2026-08-23T08:00:00"
    assert entry["recorded_at"] != "2026-08-23T08:00:00"  # server-derived
    assert entry["recorded_at"]
    assert entry["concept"] == "FIELD_SUPPLY_CFM"  # canonical
    assert entry["submitted_concept"] == "SUPPLY_CFM"


def test_canonical_storage_key():
    memory = JobConversationMemory(job_id="J1")
    memory.record_reading("FIELD_SUPPLY_CFM", 300, stage="FINAL",
                          equipment_id="RTU-1", concept="FIELD_SUPPLY_CFM", unit="CFM")
    assert "FIELD_SUPPLY_CFM" in memory.readings  # canonical bucket
    assert "SUPPLY_CFM" not in memory.readings


def test_job_scope_no_equipment_required():
    assert scope_of("BUILDING_PRESSURE") == "JOB"
    memory = JobConversationMemory(job_id="J1")
    entry = memory.record_reading("BUILDING_PRESSURE", -0.03, stage="FINAL",
                                  equipment_id=None, concept="BUILDING_PRESSURE",
                                  unit="IN.W.C.")
    assert entry["equipment_id"] is None
