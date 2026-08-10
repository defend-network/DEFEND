from __future__ import annotations

from tool_sdk import DefendTool
from tools.calculator import CalculatorTool
from tools.time_tool import TimeNowTool
from tools.web_search import WebSearchTool
from tools.web_fetch import WebFetchTool
from tools.documents_fetch import DocumentsFetchTool
from tools.documents_read import DocumentsReadTool
from tools.rag_ingest import RagIngestTool
from tools.rag_query import RagQueryTool
from tools.documents_search import DocumentsSearchTool
from tools.research_cache_ingest import ResearchCacheIngestTool
from tools.memory_search import MemorySearchTool
from tools.memory_propose import MemoryProposeTool


def build_default_registry(memory_manager=None) -> dict[str, DefendTool]:
    registry: dict[str, DefendTool] = {}

    for tool_cls in (
        DocumentsSearchTool,
        RagQueryTool,
        RagIngestTool,  # present for admin/dev; ProductionPolicy denies public use
        ResearchCacheIngestTool,  # public research PDF path
        CalculatorTool,
        TimeNowTool,
        WebSearchTool,
        WebFetchTool,
        DocumentsFetchTool,
        DocumentsReadTool,
    ):
        instance = tool_cls()
        if instance.name in registry:
            raise ValueError(f"Duplicate tool registration: {instance.name}")
        registry[instance.name] = instance

    # Memory tools are registered only when a real persistent MemoryManager exists.
    # This preserves registry-only tests/dev construction while avoiding global state.
    if memory_manager is not None:
        for instance in (MemorySearchTool(memory_manager), MemoryProposeTool(memory_manager)):
            if instance.name in registry:
                raise ValueError(f"Duplicate tool registration: {instance.name}")
            registry[instance.name] = instance

    return registry
