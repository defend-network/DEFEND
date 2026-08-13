from __future__ import annotations

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
from bootstrap_models import RagQueryInput, RagQueryOutput, RagHit
from rag_store import get_or_create_table, ensure_fts_index
from embedding_client import EmbeddingClient
from ollama_embedding_client import OllamaEmbeddingClient


def _score_from_row(row: dict) -> tuple[float | None, float]:
    """Return (raw_score, relevance_score)."""
    if "_distance" in row and row["_distance"] is not None:
        dist = float(row["_distance"])
        return dist, 1.0 / (1.0 + dist)
    if "score" in row and row["score"] is not None:
        s = float(row["score"])
        return s, s
    if "_score" in row and row["_score"] is not None:
        s = float(row["_score"])
        return s, s
    return None, 0.0


def _row_to_hit(
    row: dict,
    *,
    vector_score=None,
    lexical_score=None,
    relevance_score: float = 0.0,
    score_method: str = "vector_distance",
) -> RagHit:
    return RagHit(
        chunk_id=row.get("chunk_id", "") or "",
        document_id=row.get("document_id", "") or "",
        source_id=row.get("source_id"),
        text=row.get("text", "") or "",
        page=row.get("page"),
        start_offset=row.get("start_offset"),
        end_offset=row.get("end_offset"),
        vector_score=vector_score,
        lexical_score=lexical_score,
        relevance_score=float(relevance_score),
        score_method=score_method,
        content_hash=row.get("content_hash", "") or "",
    )


def _build_where(project_id: str | None, document_ids: list[str] | None) -> str | None:
    clauses = []
    if project_id:
        safe = project_id.replace("'", "")
        clauses.append(f"project_id = '{safe}'")
    if document_ids:
        cleaned = [d.replace("'", "") for d in document_ids]
        ids = ", ".join(f"'{d}'" for d in cleaned)
        clauses.append(f"document_id IN ({ids})")
    return " AND ".join(clauses) if clauses else None


def _rrf_fuse(
    vector_rows: list[dict],
    lexical_rows: list[dict],
    limit: int,
    k: int = 60,
) -> list[RagHit]:
    scores: dict[str, dict] = {}

    for rank, row in enumerate(vector_rows):
        cid = row.get("chunk_id") or f"v{rank}"
        raw, _ = _score_from_row(row)
        entry = scores.setdefault(
            cid,
            {"row": row, "vector_rank": None, "lex_rank": None, "vraw": None, "lraw": None},
        )
        entry["vector_rank"] = rank
        entry["vraw"] = raw
        entry["row"] = row

    for rank, row in enumerate(lexical_rows):
        cid = row.get("chunk_id") or f"l{rank}"
        raw, _ = _score_from_row(row)
        entry = scores.setdefault(
            cid,
            {"row": row, "vector_rank": None, "lex_rank": None, "vraw": None, "lraw": None},
        )
        entry["lex_rank"] = rank
        entry["lraw"] = raw
        if not entry["row"].get("text"):
            entry["row"] = row

    fused: list[tuple[float, dict]] = []
    for _cid, entry in scores.items():
        score = 0.0
        if entry["vector_rank"] is not None:
            score += 1.0 / (k + entry["vector_rank"] + 1)
        if entry["lex_rank"] is not None:
            score += 1.0 / (k + entry["lex_rank"] + 1)
        fused.append((score, entry))

    fused.sort(key=lambda x: x[0], reverse=True)
    hits: list[RagHit] = []
    for score, entry in fused[:limit]:
        hits.append(
            _row_to_hit(
                entry["row"],
                vector_score=entry["vraw"],
                lexical_score=entry["lraw"],
                relevance_score=score,
                score_method="rrf",
            )
        )
    return hits


class RagQueryTool(DefendTool[RagQueryInput, RagQueryOutput]):
    name = "rag.query"
    description = "Query the local DEFEND knowledge index (semantic, lexical, or hybrid)."
    version = "1.1.1"

    input_model = RagQueryInput
    output_model = RagQueryOutput

    permissions = frozenset()
    risk_level = RiskLevel.LOW
    side_effect = SideEffect.READ
    idempotent = True
    parallel_safe = True
    timeout_seconds = 60.0
    max_input_classification = DataClassification.PUBLIC
    max_output_classification = DataClassification.PUBLIC

    def __init__(self, embedder: EmbeddingClient | None = None):
        self.embedder = embedder or OllamaEmbeddingClient()

    async def execute(self, args: RagQueryInput, context: ToolContext) -> ToolResult[RagQueryOutput]:
        try:
            scope = getattr(args, "scope", None) or "permanent"
            if scope == "research":
                from rag_store import purge_expired
                purge_expired("research")
            table = get_or_create_table(scope)
            ensure_fts_index(table)
            where = _build_where(args.project_id, args.document_ids)
            fetch_n = max(args.limit * 5, args.limit)

            vector_rows: list[dict] = []
            lexical_rows: list[dict] = []

            if args.mode in {"semantic", "hybrid"}:
                query_vec = await self.embedder.embed_query(args.query)
                search = table.search(query_vec).limit(fetch_n)
                if where:
                    search = search.where(where)
                vector_rows = search.to_list()

            if args.mode in {"lexical", "hybrid"}:
                try:
                    search = table.search(args.query, query_type="fts").limit(fetch_n)
                    if where:
                        search = search.where(where)
                    lexical_rows = search.to_list()
                except Exception:
                    if args.mode == "lexical" and not vector_rows:
                        query_vec = await self.embedder.embed_query(args.query)
                        search = table.search(query_vec).limit(fetch_n)
                        if where:
                            search = search.where(where)
                        vector_rows = search.to_list()

            if args.mode == "hybrid":
                hits = _rrf_fuse(vector_rows, lexical_rows, args.limit)
            elif args.mode == "lexical" and lexical_rows:
                hits = []
                for row in lexical_rows[: args.limit]:
                    raw, final = _score_from_row(row)
                    hits.append(
                        _row_to_hit(
                            row,
                            lexical_score=raw,
                            relevance_score=final,
                            score_method="bm25",
                        )
                    )
            else:
                hits = []
                for row in vector_rows[: args.limit]:
                    raw, final = _score_from_row(row)
                    hits.append(
                        _row_to_hit(
                            row,
                            vector_score=raw,
                            relevance_score=final,
                            score_method="vector_distance",
                        )
                    )

            return ToolResult(
                ok=True,
                data=RagQueryOutput(
                    hits=hits,
                    embedding_model=self.embedder.model,
                    mode=args.mode,
                ),
            )

        except Exception as e:
            return ToolResult(
                ok=False,
                error=ToolError(
                    code=ToolErrorCode.INTERNAL_ERROR,
                    message=str(e),
                    retryable=True,
                ),
            )
