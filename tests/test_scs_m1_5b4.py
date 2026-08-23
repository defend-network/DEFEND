"""SCS M1.5B4 — durable-authority closure tests."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from scs_copilot.memory import JobConversationMemory, JobMemoryCorrupt, JobMemoryStore
from scs_knowledge.discovery import (
    DiscoveryLedgerError,
    ForbiddenTransition,
    KnowledgeDiscoveryStore,
    source_id_for_sha256,
)
from scs_knowledge.registry import (
    KnowledgeSource,
    SCSKnowledgeLibrary,
    SourceIdCollision,
)


def _store(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("SCS_KNOWLEDGE_ROOT", str(root))
    return KnowledgeDiscoveryStore(root / "discovery.json", root=root)


def _ready(store, text="Carrier 50TC installation manual"):
    (store._root / "manual.txt").write_text(text, encoding="utf-8")
    store.discover()
    record = store.list()[0]
    store.classify(record["discovery_id"], manufacturer="CARRIER", model="50TC-E08")
    return store, record


# ---------------------------------------------------------------------------
# B4-01 — fresh-process corruption fail-closed
# ---------------------------------------------------------------------------


def _corrupt_memory_dir(tmp_path):
    mem_dir = tmp_path / "mem"
    store = JobMemoryStore(mem_dir)
    store.update("J", lambda m: m.record_reading("fan_rpm", 1130, stage="FINAL"))
    (mem_dir / "J.memory.json").write_text("{corrupt", encoding="utf-8")
    return mem_dir


def test_fresh_load_corrupt_raises(tmp_path):
    mem_dir = _corrupt_memory_dir(tmp_path)
    store2 = JobMemoryStore(mem_dir)  # new process
    with pytest.raises(JobMemoryCorrupt):
        store2.load("J")


def test_fresh_update_corrupt_raises_and_preserves(tmp_path):
    mem_dir = _corrupt_memory_dir(tmp_path)
    original = (mem_dir / "J.memory.json").read_text(encoding="utf-8")
    store2 = JobMemoryStore(mem_dir)
    with pytest.raises(JobMemoryCorrupt):
        store2.update("J", lambda m: m.record_reading("fan_rpm", 1140, stage="FINAL"))
    assert (mem_dir / "J.memory.json").read_text(encoding="utf-8") == original


def test_fresh_commit_corrupt_raises(tmp_path):
    mem_dir = _corrupt_memory_dir(tmp_path)
    store2 = JobMemoryStore(mem_dir)
    working = JobConversationMemory(job_id="J")
    with pytest.raises(JobMemoryCorrupt):
        store2.commit("J", working)


def test_fresh_save_corrupt_raises(tmp_path):
    mem_dir = _corrupt_memory_dir(tmp_path)
    original = (mem_dir / "J.memory.json").read_text(encoding="utf-8")
    store2 = JobMemoryStore(mem_dir)
    with pytest.raises(JobMemoryCorrupt):
        store2.save(JobConversationMemory(job_id="J"))
    assert (mem_dir / "J.memory.json").read_text(encoding="utf-8") == original


def test_explicit_recovery_preserves_corrupt(tmp_path):
    mem_dir = _corrupt_memory_dir(tmp_path)
    store = JobMemoryStore(mem_dir)
    result = store.archive_corrupt_and_reset("J", actor="owner")
    assert result["archived"] is True
    assert result["archive_sha"]
    assert (mem_dir / "_recovery").exists()
    # after recovery, the job memory is EMPTY and writable again
    assert store.memory_state("J") == "EMPTY"
    store.update("J", lambda m: m.record_reading("fan_rpm", 1200, stage="FINAL"))
    assert store.load("J").latest_reading("fan_rpm") == 1200


def test_missing_file_remains_empty_and_writable(tmp_path):
    store = JobMemoryStore(tmp_path / "mem")
    assert store.memory_state("NOPE") == "EMPTY"
    store.update("NOPE", lambda m: m.record_reading("x", 1, stage="FINAL"))
    assert store.load("NOPE").latest_reading("x") == 1


# ---------------------------------------------------------------------------
# B4-02 — post-mutation exceptions all clean up
# ---------------------------------------------------------------------------


def _library(tmp_path):
    return SCSKnowledgeLibrary(tmp_path / "lib.db")


def test_mark_discovery_managed_failure_quarantines(tmp_path, monkeypatch):
    store, record = _ready(_store(tmp_path, monkeypatch))
    library = _library(tmp_path)
    library.mark_discovery_managed = lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("managed fail"))
    result = store.approve_and_index(record["discovery_id"], library,
                                     private_root=tmp_path / "priv")
    assert result["state"] != "INDEXED"
    sid = source_id_for_sha256(record["file_sha256"])
    src = library.get_source(sid)
    if src is not None:
        assert src.source_state == "QUARANTINED"
    library.close()


def test_verify_source_failure_quarantines(tmp_path, monkeypatch):
    store, record = _ready(_store(tmp_path, monkeypatch))
    library = _library(tmp_path)
    library.verify_source = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("verify fail"))
    result = store.approve_and_index(record["discovery_id"], library,
                                     private_root=tmp_path / "priv")
    assert result["state"] != "INDEXED"
    sid = source_id_for_sha256(record["file_sha256"])
    src = library.get_source(sid)
    if src is not None:
        assert src.source_state == "QUARANTINED"
    library.close()


def test_forbidden_transition_during_mark_indexed_quarantines(tmp_path, monkeypatch):
    store, record = _ready(_store(tmp_path, monkeypatch))
    library = _library(tmp_path)
    store.mark_indexed = lambda *a, **k: (_ for _ in ()).throw(
        ForbiddenTransition("forbidden transition X -> INDEXED"))
    result = store.approve_and_index(record["discovery_id"], library,
                                     private_root=tmp_path / "priv")
    assert result["state"] != "INDEXED"
    sid = source_id_for_sha256(record["file_sha256"])
    src = library.get_source(sid)
    if src is not None:
        assert src.source_state == "QUARANTINED"
    library.close()


def test_cleanup_failure_surfaces_distinct(tmp_path, monkeypatch):
    store, record = _ready(_store(tmp_path, monkeypatch))
    library = _library(tmp_path)
    library.mark_discovery_managed = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))
    library.quarantine_source = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("q fail"))
    with pytest.raises(DiscoveryLedgerError) as exc:
        store.approve_and_index(record["discovery_id"], library, private_root=tmp_path / "priv")
    assert "KNOWLEDGE_CLEANUP_FAILED" in str(exc.value)
    library.close()


# ---------------------------------------------------------------------------
# B4-03 — incompatible ledger recovery
# ---------------------------------------------------------------------------


def test_incompatible_ledger_recovery(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("SCS_KNOWLEDGE_ROOT", str(root))
    manifest = root / "discovery.json"
    manifest.write_text(json.dumps({"DSC-old": {"state": "DISCOVERED"}}), encoding="utf-8")
    store = KnowledgeDiscoveryStore(manifest, root=root)
    assert store.ledger_state == "INCOMPATIBLE"
    result = store.archive_and_rediscover(actor="owner")
    assert result["archived"] is True
    assert result["auto_approved_count"] == 0
    assert store.ledger_state == "OK"


def test_incompatible_ledger_with_authority_refuses_recovery(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("SCS_KNOWLEDGE_ROOT", str(root))
    manifest = root / "discovery.json"
    manifest.write_text(json.dumps({"DSC-old": {"state": "INDEXED"}}), encoding="utf-8")
    store = KnowledgeDiscoveryStore(manifest, root=root)
    assert store.ledger_state == "INCOMPATIBLE"
    result = store.archive_and_rediscover(actor="owner")
    assert result["state"] == "LEGACY_LEDGER_AUTHORITY_PRESENT"
    assert result["archived"] is False


# ---------------------------------------------------------------------------
# B4-04 — source id canonical + collision
# ---------------------------------------------------------------------------


def test_source_id_for_sha256_canonical():
    assert source_id_for_sha256("a" * 64) == "SRC-" + "a" * 10


def test_source_id_collision_fails_closed(tmp_path):
    library = SCSKnowledgeLibrary(tmp_path / "lib.db")
    library.add_source(KnowledgeSource(source_id="SRC-abcdefghij", source_type="OEM_IOM",
                                       document_hash="x" * 64))
    with pytest.raises(SourceIdCollision):
        library.add_source(KnowledgeSource(source_id="SRC-abcdefghij", source_type="OEM_IOM",
                                           document_hash="y" * 64))
    library.close()


# ---------------------------------------------------------------------------
# snapshot deletion is actually asserted
# ---------------------------------------------------------------------------


def test_snapshot_absent_after_success(tmp_path, monkeypatch):
    staging = Path(tempfile.mkdtemp(prefix="scs_b4_tmp_"))
    monkeypatch.setenv("TMPDIR", str(staging))
    monkeypatch.setenv("TEMP", str(staging))
    monkeypatch.setenv("TMP", str(staging))
    store, record = _ready(_store(tmp_path, monkeypatch))
    library = _library(tmp_path)
    result = store.approve_and_index(record["discovery_id"], library,
                                     manufacturer="CARRIER", model="50TC-E08",
                                     private_root=tmp_path / "priv")
    assert result["state"] == "INDEXED"
    leftovers = list(staging.glob("scs_stage_*"))
    assert leftovers == []  # TemporaryDirectory removed the staging dir
    library.close()
