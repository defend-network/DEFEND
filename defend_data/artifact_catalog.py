from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .config import DataPaths
from .raw_store import RawStore
from .sqlite_utils import connect_sqlite, json_dumps, json_loads, transaction


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    sha256: str
    byte_size: int
    media_type: str | None
    raw_relpath: str
    retention_class: str
    classification: str
    created_at: str
    metadata: dict[str, Any]


class ArtifactCatalog:
    """Catalog/provenance for downloaded, uploaded and imported bytes."""

    VALID_RETENTION = {"permanent", "cache", "session", "licensed"}
    VALID_CLASSIFICATION = {"public", "internal", "confidential", "restricted"}

    def __init__(self, paths: DataPaths, raw_store: RawStore | None = None):
        self.paths = paths.ensure()
        self.raw = raw_store or RawStore(paths)
        self.db_path = self.paths.db / "catalog.db"
        self.conn = connect_sqlite(self.db_path)
        self._migrate()

    def close(self) -> None:
        self.conn.close()

    def _migrate(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS artifacts (
                artifact_id TEXT PRIMARY KEY,
                sha256 TEXT NOT NULL UNIQUE,
                byte_size INTEGER NOT NULL,
                media_type TEXT,
                raw_relpath TEXT NOT NULL,
                retention_class TEXT NOT NULL,
                expires_at TEXT,
                classification TEXT NOT NULL,
                created_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS retrievals (
                retrieval_id TEXT PRIMARY KEY,
                artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
                source_url TEXT,
                canonical_url TEXT,
                retrieved_at TEXT NOT NULL,
                collector TEXT,
                dataset TEXT,
                domain TEXT,
                scope TEXT,
                license_note TEXT,
                parent_artifact_id TEXT REFERENCES artifacts(artifact_id),
                ingestion_run_id TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_retrievals_artifact ON retrievals(artifact_id);
            CREATE INDEX IF NOT EXISTS idx_retrievals_url ON retrievals(canonical_url);
            CREATE INDEX IF NOT EXISTS idx_retrievals_dataset ON retrievals(dataset);
            CREATE TABLE IF NOT EXISTS ingestion_runs (
                run_id TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                source_name TEXT,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT NOT NULL,
                records_seen INTEGER NOT NULL DEFAULT 0,
                records_written INTEGER NOT NULL DEFAULT 0,
                artifacts_written INTEGER NOT NULL DEFAULT 0,
                errors INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS artifact_tags (
                artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
                tag TEXT NOT NULL,
                PRIMARY KEY (artifact_id, tag)
            );
            """
        )
        self.conn.execute("INSERT OR REPLACE INTO schema_meta(key,value) VALUES('schema_version','1')")
        self.conn.commit()

    def start_ingestion_run(self, source_type: str, source_name: str | None = None, metadata: dict[str, Any] | None = None) -> str:
        run_id = f"ing_{uuid.uuid4().hex}"
        self.conn.execute(
            "INSERT INTO ingestion_runs(run_id,source_type,source_name,started_at,status,metadata_json) VALUES(?,?,?,?,?,?)",
            (run_id, source_type, source_name, utc_now(), "running", json_dumps(metadata or {})),
        )
        self.conn.commit()
        return run_id

    def finish_ingestion_run(self, run_id: str, *, status: str = "succeeded", records_seen: int = 0,
                             records_written: int = 0, artifacts_written: int = 0, errors: int = 0) -> None:
        self.conn.execute(
            """UPDATE ingestion_runs SET completed_at=?,status=?,records_seen=?,records_written=?,artifacts_written=?,errors=? WHERE run_id=?""",
            (utc_now(), status, records_seen, records_written, artifacts_written, errors, run_id),
        )
        self.conn.commit()

    def ingest_bytes(self, data: bytes, *, media_type: str | None = None, source_url: str | None = None,
                     canonical_url: str | None = None, collector: str | None = None, dataset: str | None = None,
                     domain: str | None = None, scope: str | None = None, license_note: str | None = None,
                     retention_class: str = "permanent", expires_at: str | None = None,
                     classification: str = "public", parent_artifact_id: str | None = None,
                     ingestion_run_id: str | None = None, artifact_metadata: dict[str, Any] | None = None,
                     retrieval_metadata: dict[str, Any] | None = None) -> ArtifactRecord:
        if retention_class not in self.VALID_RETENTION:
            raise ValueError(f"Invalid retention_class: {retention_class}")
        if classification not in self.VALID_CLASSIFICATION:
            raise ValueError(f"Invalid classification: {classification}")

        raw_obj = self.raw.put_bytes(data)
        now = utc_now()
        with transaction(self.conn, immediate=True):
            row = self.conn.execute("SELECT * FROM artifacts WHERE sha256=?", (raw_obj.sha256,)).fetchone()
            if row is None:
                artifact_id = f"art_{uuid.uuid4().hex}"
                self.conn.execute(
                    """INSERT INTO artifacts(artifact_id,sha256,byte_size,media_type,raw_relpath,retention_class,expires_at,classification,created_at,metadata_json)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (artifact_id, raw_obj.sha256, raw_obj.byte_size, media_type, raw_obj.relative_path,
                     retention_class, expires_at, classification, now, json_dumps(artifact_metadata or {})),
                )
            else:
                artifact_id = row["artifact_id"]

            self.conn.execute(
                """INSERT INTO retrievals(retrieval_id,artifact_id,source_url,canonical_url,retrieved_at,collector,dataset,domain,scope,license_note,parent_artifact_id,ingestion_run_id,metadata_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (f"ret_{uuid.uuid4().hex}", artifact_id, source_url, canonical_url or source_url, now,
                 collector, dataset, domain, scope, license_note, parent_artifact_id, ingestion_run_id,
                 json_dumps(retrieval_metadata or {})),
            )
        return self.get_artifact(artifact_id)

    def get_artifact(self, artifact_id: str) -> ArtifactRecord:
        row = self.conn.execute("SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        return ArtifactRecord(row["artifact_id"], row["sha256"], row["byte_size"], row["media_type"],
                              row["raw_relpath"], row["retention_class"], row["classification"],
                              row["created_at"], json_loads(row["metadata_json"], {}))


    def stats(self) -> dict[str, int]:
        artifacts = int(self.conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0])
        retrievals = int(self.conn.execute("SELECT COUNT(*) FROM retrievals").fetchone()[0])
        ingestion_runs = int(self.conn.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone()[0])
        return {
            "artifacts": artifacts,
            "retrievals": retrievals,
            "ingestion_runs": ingestion_runs,
        }

    def retrieval_count(self, artifact_id: str) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM retrievals WHERE artifact_id=?", (artifact_id,)).fetchone()
        return int(row["n"])
