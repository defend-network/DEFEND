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
from bootstrap_models import DocumentsSearchInput, DocumentsSearchOutput, RagQueryInput
from tools.rag_query import RagQueryTool


class DocumentsSearchTool(DefendTool[DocumentsSearchInput, DocumentsSearchOutput]):
    name = "documents.search"
    description = "Search within a single ingested document using the shared knowledge index."
    version = "1.0.0"

    input_model = DocumentsSearchInput
    output_model = DocumentsSearchOutput

    permissions = frozenset()
    risk_level = RiskLevel.LOW
    side_effect = SideEffect.READ
    idempotent = True
    parallel_safe = True
    timeout_seconds = 60.0
    max_input_classification = DataClassification.PUBLIC
    max_output_classification = DataClassification.PUBLIC

    def __init__(self, rag_query: RagQueryTool | None = None):
        self.rag_query = rag_query or RagQueryTool()

    async def execute(self, args: DocumentsSearchInput, context: ToolContext) -> ToolResult[DocumentsSearchOutput]:
        # Session ACL: refuse foreign session documents
        try:
            from tools.documents_store import load_meta
            meta = load_meta(args.document_id)
            if meta.get("scope") == "session":
                owner = meta.get("owner_session_id")
                sess = getattr(context, "session_id", None)
                if owner and sess and owner != sess:
                    return ToolResult(
                        ok=False,
                        error=ToolError(
                            code=ToolErrorCode.PERMISSION_DENIED,
                            message="Session document not owned by this session",
                            retryable=False,
                        ),
                    )
        except FileNotFoundError:
            pass
        except Exception:
            pass

        result = await self.rag_query.execute(
            RagQueryInput(
                query=args.query,
                document_ids=[args.document_id],
                limit=args.limit,
                mode=args.mode,
                scope=getattr(args, "scope", None) or "permanent",
            ),
            context,
        )
        if not result.ok or result.data is None:
            return ToolResult(ok=False, error=result.error)

        return ToolResult(
            ok=True,
            data=DocumentsSearchOutput(
                document_id=args.document_id,
                hits=result.data.hits,
                mode=result.data.mode,
            ),
        )