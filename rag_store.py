from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import lancedb
from lancedb.pydantic import LanceModel, Vector


STORE_DIR = Path("artifacts/lancedb")
STORE_DIR.mkdir(parents=True, exist_ok=True)

VECTOR_DIM = 1024  # qwen3-embedding:0.6b

TABLE_BY_SCOPE: dict[str, str] = {
    "permanent": "chunks",
    "research": "chunks_research",
    "session": "chunks_session",
}


class ChunkRow(LanceModel):
    chunk_id: str
    document_id: str
    source_id: str | None = None
    project_id: str | None = None
    text: str
    page: int | None = None
    chunk_index: int
    start_offset: int | None = None
    end_offset: int | None = None
    content_hash: str
    embedding_model: str
    vector: Vector(VECTOR_DIM)
    tags: str = ""
    ingested_at: str
    scope: str = "permanent"
    expires_at: str | None = None
    owner_session_id: str | None = None


def get_db():
    return lancedb.connect(str(STORE_DIR))


def table_name_for_scope(scope: str = "permanent") -> str:
    return TABLE_BY_SCOPE.get(scope, TABLE_BY_SCOPE["permanent"])


def ensure_fts_index(table=None) -> None:
    table = table or get_or_create_table("permanent")
    try:
        table.create_fts_index("text", replace=False)
    except Exception:
        pass


def get_or_create_table(scope: str = "permanent", db=None):
    db = db or get_db()
    name = table_name_for_scope(scope)
    names = set(db.table_names())
    if name in names:
        return db.open_table(name)
    return db.create_table(name, schema=ChunkRow)


def delete_document_chunks(document_id: str, scope: str = "permanent", db=None) -> int:
    table = get_or_create_table(scope, db)
    try:
        existing = (
            table.search()
            .where(f"document_id = '{document_id}'")
            .limit(10000)
            .to_list()
        )
        n = len(existing)
    except Exception:
        n = 0
    table.delete(f"document_id = '{document_id}'")
    return n


def purge_expired(scope: str = "research", db=None) -> int:
    table = get_or_create_table(scope, db)
    now = datetime.now(timezone.utc).isoformat()
    try:
        rows = table.search().limit(50000).to_list()
    except Exception:
        return 0
    n = 0
    for r in rows:
        exp = r.get("expires_at")
        cid = r.get("chunk_id")
        if exp and cid and str(exp) < now:
            try:
                table.delete(f"chunk_id = '{cid}'")
                n += 1
            except Exception:
                pass
    return n
