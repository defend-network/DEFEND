from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import re

from tool_sdk import (
    DefendTool, ToolContext, ToolResult, ToolError, ToolErrorCode,
    RiskLevel, SideEffect, DataClassification,
)
from bootstrap_models import RagIngestInput, RagIngestOutput, DocumentsReadInput
from tools.documents_store import load_meta
from tools.documents_read import DocumentsReadTool
from rag_store import (
    ChunkRow, VECTOR_DIM, get_or_create_table,
    delete_document_chunks, ensure_fts_index, purge_expired,
)
from ollama_embedding_client import OllamaEmbeddingClient
from embedding_client import EmbeddingClient

DEFAULT_TTL_HOURS = 24 * 7


def _chunk_text(text: str, max_chars: int = 1800, overlap: int = 200):
    text = (text or "").strip()
    if not text:
        return []
    parts, n, i = [], len(text), 0
    while i < n:
        end = min(i + max_chars, n)
        if end < n:
            window = text[i:end]
            br = max(window.rfind("\n\n"), window.rfind("\n"), window.rfind(" "))
            if br > max_chars * 0.4:
                end = i + br
        chunk = text[i:end].strip()
        if chunk:
            parts.append((i, end, chunk))
        if end >= n:
            break
        i = max(end - overlap, i + 1)
    return parts


def _page_blocks(text: str):
    pattern = re.compile(r"\[Page\s+(\d+)\]")
    spans = list(pattern.finditer(text or ""))
    if not spans:
        return [(None, text or "")]
    out = []
    for idx, m in enumerate(spans):
        start = m.end()
        end = spans[idx + 1].start() if idx + 1 < len(spans) else len(text)
        body = text[start:end].strip()
        if body:
            out.append((int(m.group(1)), body))
    return out or [(None, text or "")]


class ResearchCacheIngestTool(DefendTool[RagIngestInput, RagIngestOutput]):
    name = "research.cache_ingest"
    description = "Index into isolated ephemeral RESEARCH table (TTL). Not permanent knowledge."
    version = "1.1.0"
    input_model = RagIngestInput
    output_model = RagIngestOutput
    permissions = frozenset()
    risk_level = RiskLevel.LOW
    side_effect = SideEffect.WRITE
    idempotent = True
    parallel_safe = False
    timeout_seconds = 180.0
    max_input_classification = DataClassification.PUBLIC
    max_output_classification = DataClassification.PUBLIC

    def __init__(self, embedder: EmbeddingClient | None = None, ttl_hours: int = DEFAULT_TTL_HOURS):
        self.embedder = embedder or OllamaEmbeddingClient()
        self.ttl_hours = ttl_hours

    async def execute(self, args: RagIngestInput, context: ToolContext) -> ToolResult[RagIngestOutput]:
        try:
            purge_expired("research")
            meta = load_meta(args.document_id)
            source_id = meta.get("source_id")
            media_type = str(meta.get("media_type") or "").lower()
            page_count = meta.get("page_count")
            content_hash = meta.get("content_hash") or ""
            embedding_model = self.embedder.model
            now = datetime.now(timezone.utc)
            ingested_at = now.isoformat()
            expires_at = (now + timedelta(hours=self.ttl_hours)).isoformat()

            reader = DocumentsReadTool()
            page_blocks = []
            if "pdf" in media_type and page_count:
                start = 1
                while start <= int(page_count):
                    end = min(start + 2, int(page_count))
                    rr = await reader.execute(
                        DocumentsReadInput(document_id=args.document_id, page_start=start, page_end=end, max_chars=50000),
                        context,
                    )
                    if not rr.ok or not rr.data:
                        return ToolResult(ok=False, error=ToolError(code=ToolErrorCode.INTERNAL_ERROR, message=f"read {start}-{end} failed", retryable=True))
                    text = rr.data.content or ""
                    if text.strip():
                        marked = _page_blocks(text)
                        if marked and marked[0][0] is not None:
                            page_blocks.extend(marked)
                        else:
                            page_blocks.append((start, text))
                    start = end + 1
            else:
                rr = await reader.execute(DocumentsReadInput(document_id=args.document_id, max_chars=200000), context)
                if not rr.ok or not rr.data:
                    return ToolResult(ok=False, error=ToolError(code=ToolErrorCode.INTERNAL_ERROR, message="extract failed", retryable=False))
                page_blocks = _page_blocks(rr.data.content or "")

            staging, texts, chunk_index = [], [], 0
            tags = list(args.tags or [])
            if "research_cache" not in tags:
                tags.append("research_cache")
            tag_str = ",".join(tags)
            for page, block in page_blocks:
                for so, eo, chunk in _chunk_text(block):
                    raw_id = f"research:{args.document_id}:{page}:{chunk_index}:{chunk[:64]}"
                    cid = "chk_" + hashlib.sha256(raw_id.encode()).hexdigest()[:24]
                    staging.append(dict(
                        chunk_id=cid, document_id=args.document_id, source_id=source_id,
                        project_id=args.project_id, text=chunk, page=page, chunk_index=chunk_index,
                        start_offset=so, end_offset=eo, content_hash=content_hash,
                        embedding_model=embedding_model, tags=tag_str, ingested_at=ingested_at,
                        scope="research", expires_at=expires_at,
                        owner_session_id=getattr(context, "session_id", None),
                    ))
                    texts.append(chunk)
                    chunk_index += 1

            if not staging:
                return ToolResult(ok=True, data=RagIngestOutput(
                    document_id=args.document_id, chunks_added=0, chunks_updated=0,
                    chunks_skipped=0, embedding_model=embedding_model, content_hash=content_hash))

            vectors = await self.embedder.embed_documents(texts)
            if len(vectors) != len(staging):
                return ToolResult(ok=False, error=ToolError(code=ToolErrorCode.INTERNAL_ERROR, message="embed mismatch", retryable=True))

            rows = []
            for item, vec in zip(staging, vectors):
                if len(vec) != VECTOR_DIM:
                    return ToolResult(ok=False, error=ToolError(code=ToolErrorCode.INTERNAL_ERROR, message=f"dim {len(vec)}", retryable=False))
                rows.append(ChunkRow(vector=vec, **item))

            deleted = delete_document_chunks(args.document_id, scope="research")
            table = get_or_create_table("research")
            table.add(rows)
            ensure_fts_index(table)
            return ToolResult(ok=True, data=RagIngestOutput(
                document_id=args.document_id, chunks_added=len(rows), chunks_updated=deleted,
                chunks_skipped=0, embedding_model=embedding_model, content_hash=content_hash))
        except FileNotFoundError as e:
            return ToolResult(ok=False, error=ToolError(code=ToolErrorCode.NOT_FOUND, message=str(e), retryable=False))
        except Exception as e:
            return ToolResult(ok=False, error=ToolError(code=ToolErrorCode.INTERNAL_ERROR, message=str(e), retryable=True))
