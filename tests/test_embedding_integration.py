from registry import build_default_registry
from defend_data.admin_rag import PermanentRagService


class FakeEmbedder:
    model = "test-embedding"


def test_registry_shares_configured_embedder_across_rag_tools():
    embedder = FakeEmbedder()

    registry = build_default_registry(embedding_client=embedder)

    assert registry["rag.query"].embedder is embedder
    assert registry["rag.ingest"].embedder is embedder
    assert registry["research.cache_ingest"].embedder is embedder


def test_permanent_rag_service_can_share_configured_embedder(tmp_path):
    embedder = FakeEmbedder()

    service = PermanentRagService(tmp_path, embedding_client=embedder)

    assert service.embedding_client is embedder
