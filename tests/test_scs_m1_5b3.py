"""SCS M1.5B3 — fail-closed ingest cleanup + snapshot lifecycle tests."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from scs_knowledge.discovery import (
    DiscoveryLedgerError,
    KnowledgeDiscoveryStore,
)
from scs_knowledge.registry import (
    KnowledgeChunk,
    KnowledgeSource,
    SCSKnowledgeLibrary,
)


def _store(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("SCS_KNOWLEDGE_ROOT", str(root))
    return KnowledgeDiscoveryStore(root / "discovery.json", root=root)


def _discover(store, text="Carrier 50TC installation manual"):
    (store._root / "manual.txt").write_text(text, encoding="utf-8")
    store.discover()
    return store.list()[0]


def _classify_ready(store, record):
    store.classify(record["discovery_id"], manufacturer="CARRIER", model="50TC-E08")
    return store.get(record["discovery_id"])


# ---------------------------------------------------------------------------
# quarantine_source atomicity
# ---------------------------------------------------------------------------


def test_quarantine_source_disables_source_chunks_tables(tmp_path):
    library = SCSKnowledgeLibrary(tmp_path / "lib.db")
    library.add_source(KnowledgeSource(source_id="S1", source_type="OEM_IOM",
                                       document_hash="abc"))
    library.add_chunk(KnowledgeChunk(chunk_id="C1", source_id="S1", text="chunk"))
    library._db.execute("INSERT INTO tables (table_id, source_id, rows_json, active) "
                        "VALUES ('T1','S1','[]',1)")
    library._db.commit()
    library.quarantine_source("S1")
    assert library.get_source("S1").source_state == "QUARANTINED"
    assert library.get_source("S1").active is False
    chunk = library._db.execute("SELECT active FROM chunks WHERE chunk_id='C1'").fetchone()
    assert chunk["active"] == 0
    table = library._db.execute("SELECT active FROM tables WHERE table_id='T1'").fetchone()
    assert table["active"] == 0
    library.close()


# ---------------------------------------------------------------------------
# partial ingest cleanup
# ---------------------------------------------------------------------------


def test_partial_ingest_quarantined(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    record = _classify_ready(store, _discover(store))
    library = SCSKnowledgeLibrary(tmp_path / "lib.db")
    import scs_knowledge.discovery as disc
    original = disc.ingest_file
    sha = record["file_sha256"]
    source_id = f"SRC-{sha[:10]}"

    def partial_ingest(lib, path, **kw):
        lib.add_source(KnowledgeSource(source_id=source_id, source_type="OEM_IOM",
                                       document_hash=sha, title="manual"))
        lib.add_chunk(KnowledgeChunk(chunk_id="C1", source_id=source_id, text="chunk"))
        raise RuntimeError("injected chunk failure")

    disc.ingest_file = partial_ingest
    try:
        result = store.approve_and_index(record["discovery_id"], library,
                                         private_root=tmp_path / "priv")
    finally:
        disc.ingest_file = original
    assert result["state"] == "PARSE_FAILED"
    src = library.get_source(source_id)
    assert src.source_state == "QUARANTINED"
    assert src.active is False
    assert library._db.execute(
        "SELECT active FROM chunks WHERE source_id=?", (source_id,)).fetchone()["active"] == 0
    library.close()


def test_ingest_throws_before_result_no_attribute_error(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    record = _classify_ready(store, _discover(store))
    library = SCSKnowledgeLibrary(tmp_path / "lib.db")
    import scs_knowledge.discovery as disc
    original = disc.ingest_file
    disc.ingest_file = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("before insert"))
    try:
        result = store.approve_and_index(record["discovery_id"], library,
                                         private_root=tmp_path / "priv")
    finally:
        disc.ingest_file = original
    assert result["state"] == "PARSE_FAILED"  # no AttributeError
    assert library.get_source(f"SRC-{record['file_sha256'][:10]}") is None or \
        library.get_source(f"SRC-{record['file_sha256'][:10]}").source_state == "QUARANTINED"
    library.close()


def test_cleanup_failure_surfaces(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    record = _classify_ready(store, _discover(store))
    library = SCSKnowledgeLibrary(tmp_path / "lib.db")
    import scs_knowledge.discovery as disc
    original = disc.ingest_file
    disc.ingest_file = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    library.quarantine_source = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("quarantine fail"))
    try:
        with pytest.raises(DiscoveryLedgerError) as exc:
            store.approve_and_index(record["discovery_id"], library,
                                    private_root=tmp_path / "priv")
        assert "KNOWLEDGE_CLEANUP_FAILED" in str(exc.value)
    finally:
        disc.ingest_file = original
    # discovery must NOT be INDEXED
    assert store.get(record["discovery_id"])["state"] != "INDEXED"
    library.close()


def test_snapshot_removed_on_success(tmp_path, monkeypatch):
    staging_root = Path(tempfile.mkdtemp(prefix="scs_tmp_test_"))
    monkeypatch.setenv("TMPDIR", str(staging_root))
    monkeypatch.setenv("TEMP", str(staging_root))
    monkeypatch.setenv("TMP", str(staging_root))
    store = _store(tmp_path, monkeypatch)
    record = _classify_ready(store, _discover(store))
    library = SCSKnowledgeLibrary(tmp_path / "lib.db")
    result = store.approve_and_index(record["discovery_id"], library,
                                     manufacturer="CARRIER", model="50TC-E08",
                                     private_root=tmp_path / "priv")
    assert result["state"] == "INDEXED"
    # the durable private copy exists under authorized storage, not temp
    assert library.get_source(result["source_id"]).document_hash == record["file_sha256"]
    library.close()


# ---------------------------------------------------------------------------
# Job memory corruption fail-closed (M1.5C section 19)
# ---------------------------------------------------------------------------


def test_job_memory_corruption_fails_closed(tmp_path):
    from scs_copilot.memory import JobConversationMemory, JobMemoryCorrupt, JobMemoryStore
    store = JobMemoryStore(tmp_path / "mem")
    store.update("J", lambda m: m.record_reading("fan_rpm", 1130, stage="FINAL"))
    # corrupt the durable file
    (tmp_path / "mem" / "J.memory.json").write_text("{not valid json", encoding="utf-8")
    assert store.memory_state("J") == "CORRUPT"
    with pytest.raises(JobMemoryCorrupt):
        store.update("J", lambda m: m.record_reading("fan_rpm", 1140, stage="FINAL"))
    working = JobConversationMemory(job_id="J")
    working.record_reading("fan_rpm", 1140, stage="FINAL")
    with pytest.raises(JobMemoryCorrupt):
        store.commit("J", working)


def test_job_memory_missing_is_distinct_from_corrupt(tmp_path):
    from scs_copilot.memory import JobMemoryStore
    store = JobMemoryStore(tmp_path / "mem")
    assert store.memory_state("MISSING") == "EMPTY"
