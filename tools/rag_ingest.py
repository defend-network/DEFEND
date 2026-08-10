from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from tool_sdk import (
    DefendTool,
    ToolContext,
    ToolResult,
    ToolError,
    ToolErrorCode,
    RiskLevel,
    SideEffect,
    DataClassification,
)
from bootstrap_models import RagIngestInput, RagIngestOutput
from defend_data.ingest_policy import assert_ai_ingest_allowed
from tools.documents_store import load_raw, load_meta
from rag_store import ChunkRow, get_or_create_table, delete_document_chunks, VECTOR_DIM
from ollama_embedding_client import OllamaEmbeddingClient


def _chunk_text(text: str, max_chars: int = 1800, overlap: int = 200) -> list[tuple[int, int, str]]:
    """Return list of (start, end, chunk_text). Prefer paragraph breaks."""
    text = text.strip()
    if not text:
        return []

    parts: list[tuple[int, int, str]] = []
    n = len(text)
    i = 0
    while i < n:
        end = min(i + max_chars, n)
        if end < n:
            # try break on paragraph/newline/space near end
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


def _page_chunks_from_pdf_text(text: str) -> list[tuple[int | None, str]]:
    """Split on [Page N] markers produced by documents.read if present."""
    pattern = re.compile(r"\[Page\s+(\d+)\]")
    spans = list(pattern.finditer(text))
    if not spans:
        return [(None, text)]

    out: list[tuple[int | None, str]] = []
    for idx, match in enumerate(spans):
        page = int(match.group(1))
        start = match.end()
        end = spans[idx + 1].start() if idx + 1 < len(spans) else len(text)
        body = text[start:end].strip()
        if body:
            out.append((page, body))
    return out or [(None, text)]


class RagIngestTool(DefendTool[RagIngestInput, RagIngestOutput]):
    name = "rag.ingest"
    description = "Ingest a previously fetched document into the local knowledge index."
    version = "1.0.0"

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

    def __init__(self, embedder: OllamaEmbeddingClient | None = None):
        self.embedder = embedder or OllamaEmbeddingClient()

    async def execute(self, args: RagIngestInput, context: ToolContext) -> ToolResult[RagIngestOutput]:
        try:
            meta = load_meta(args.document_id)
            raw = load_raw(args.document_id)
            assert_ai_ingest_allowed(
                filename=str(meta.get("title") or args.document_id),
                content_prefix=raw[:4096],
            )
            source_id = meta.get("source_id")
            media_type = str(meta.get("media_type") or "").lower()
            page_count = meta.get("page_count")
            content_hash = meta.get("content_hash") or ""
            embedding_model = self.embedder.model
            ingested_at = datetime.now(timezone.utc).isoformat()

            from tools.documents_read import DocumentsReadTool
            from bootstrap_models import DocumentsReadInput

            reader = DocumentsReadTool()

            # Build page/window texts WITHOUT a single global truncate
            page_blocks: list[tuple[int | None, str]] = []

            if "pdf" in media_type and page_count:
                # Read in small page windows until exhausted
                window = 3
                start = 1
                while start <= int(page_count):
                    end = min(start + window - 1, int(page_count))
                    read_result = await reader.execute(
                        DocumentsReadInput(
                            document_id=args.document_id,
                            page_start=start,
                            page_end=end,
                            max_chars=50_000,
                        ),
                        context,
                    )
                    if not read_result.ok or not read_result.data:
                        return ToolResult(
                            ok=False,
                            error=ToolError(
                                code=ToolErrorCode.INTERNAL_ERROR,
                                message=f"Failed reading pages {start}-{end} of {args.document_id}",
                                retryable=True,
                            ),
                        )
                    text = read_result.data.content or ""
                    if text.strip():
                        # Prefer explicit page markers if present; else assign window start page
                        marked = _page_chunks_from_pdf_text(text)
                        if marked and marked[0][0] is not None:
                            page_blocks.extend(marked)
                        else:
                            page_blocks.append((start, text))
                    start = end + 1
            else:
                # Non-PDF: one extract with high cap, still check truncated
                read_result = await reader.execute(
                    DocumentsReadInput(
                        document_id=args.document_id,
                        page_start=None,
                        page_end=None,
                        max_chars=200_000,
                    ),
                    context,
                )
                if not read_result.ok or not read_result.data:
                    return ToolResult(
                        ok=False,
                        error=ToolError(
                            code=ToolErrorCode.INTERNAL_ERROR,
                            message=f"Could not extract text for {args.document_id}",
                            retryable=False,
                        ),
                    )
                if getattr(read_result.data, "truncated", False):
                    return ToolResult(
                        ok=False,
                        error=ToolError(
                            code=ToolErrorCode.BUDGET_EXCEEDED,
                            message="Document extract truncated; refusing incomplete ingest",
                            retryable=False,
                        ),
                    )
                page_blocks = _page_chunks_from_pdf_text(read_result.data.content or "")

            staging: list[dict] = []
            texts_to_embed: list[str] = []
            chunk_index = 0

            for page, block in page_blocks:
                for start_off, end_off, chunk in _chunk_text(block):
                    raw_id = f"{args.document_id}:{page}:{chunk_index}:{chunk[:64]}"
                    chunk_id = "chk_" + hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:24]
                    staging.append(
                        {
                            "chunk_id": chunk_id,
                            "document_id": args.document_id,
                            "source_id": source_id,
                            "project_id": args.project_id,
                            "text": chunk,
                            "page": page,
                            "chunk_index": chunk_index,
                            "start_offset": start_off,
                            "end_offset": end_off,
                            "content_hash": content_hash,
                            "embedding_model": embedding_model,
                            "tags": ",".join(args.tags or []),
                            "ingested_at": ingested_at,
                        }
                    )
                    texts_to_embed.append(chunk)
                    chunk_index += 1

            if not staging:
                return ToolResult(
                    ok=True,
                    data=RagIngestOutput(
                        document_id=args.document_id,
                        chunks_added=0,
                        chunks_updated=0,
                        chunks_skipped=0,
                        embedding_model=embedding_model,
                        content_hash=content_hash,
                    ),
                )

            # Embed FIRST, then replace index (avoid deleting good data early)
            vectors = await self.embedder.embed_documents(texts_to_embed)
            if len(vectors) != len(staging):
                return ToolResult(
                    ok=False,
                    error=ToolError(
                        code=ToolErrorCode.INTERNAL_ERROR,
                        message="Embedding count mismatch",
                        retryable=True,
                    ),
                )

            rows: list[ChunkRow] = []
            for item, vec in zip(staging, vectors):
                if len(vec) != VECTOR_DIM:
                    return ToolResult(
                        ok=False,
                        error=ToolError(
                            code=ToolErrorCode.INTERNAL_ERROR,
                            message=f"Expected vector dim {VECTOR_DIM}, got {len(vec)}",
                            retryable=False,
                        ),
                    )
                rows.append(ChunkRow(vector=vec, **item))

            # Only now replace prior chunks
            deleted = delete_document_chunks(args.document_id)
            table = get_or_create_table()
            table.add(rows)

            return ToolResult(
                ok=True,
                data=RagIngestOutput(
                    document_id=args.document_id,
                    chunks_added=len(rows),
                    chunks_updated=deleted,
                    chunks_skipped=0,
                    embedding_model=embedding_model,
                    content_hash=content_hash,
                ),
            )

        except FileNotFoundError as e:
            return ToolResult(
                ok=False,
                error=ToolError(code=ToolErrorCode.NOT_FOUND, message=str(e), retryable=False),
            )
        except Exception as e:
            return ToolResult(
                ok=False,
                error=ToolError(code=ToolErrorCode.INTERNAL_ERROR, message=str(e), retryable=True),
            )
