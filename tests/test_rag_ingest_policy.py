import asyncio
import importlib.util
import sys
import types
from pathlib import Path

from bootstrap_models import RagIngestInput
from tool_sdk import ToolContext, ToolErrorCode


def _load_rag_ingest(monkeypatch):
    rag_store = types.ModuleType("rag_store")
    rag_store.ChunkRow = object
    rag_store.VECTOR_DIM = 1
    rag_store.delete_document_chunks = lambda _: 0
    rag_store.get_or_create_table = lambda: None
    monkeypatch.setitem(sys.modules, "rag_store", rag_store)

    ollama = types.ModuleType("ollama_embedding_client")

    class OllamaEmbeddingClient:
        model = "test-model"

    ollama.OllamaEmbeddingClient = OllamaEmbeddingClient
    monkeypatch.setitem(sys.modules, "ollama_embedding_client", ollama)

    module_path = Path(__file__).parents[1] / "tools" / "rag_ingest.py"
    spec = importlib.util.spec_from_file_location("test_rag_ingest", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_rag_ingest_rejects_authoritative_source_path_without_retry(monkeypatch):
    rag_ingest = _load_rag_ingest(monkeypatch)
    monkeypatch.setattr(
        rag_ingest,
        "load_meta",
        lambda _: {"source_path": "docs/superpowers/specs/design.md", "title": "benign.pdf"},
    )
    monkeypatch.setattr(rag_ingest, "load_raw", lambda _: b"ordinary content")

    result = asyncio.run(
        rag_ingest.RagIngestTool().execute(
            RagIngestInput(document_id="doc_test"),
            ToolContext(request_id="req_test", trace_id="trace_test"),
        )
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.PERMISSION_DENIED
    assert result.error.message == "Developer-only document is excluded from AI ingestion"
    assert result.error.retryable is False
