class AIIngestExcluded(ValueError):
    pass


def assert_ai_ingest_allowed(*, filename: str, content_prefix: bytes | str | None = None) -> None:
    normalized = filename.replace("\\", "/").lstrip("/").lower()
    prefix = content_prefix.decode("utf-8", "ignore") if isinstance(content_prefix, bytes) else (content_prefix or "")
    if normalized.startswith("docs/superpowers/") or "DEFEND-AI-INGEST: EXCLUDE" in prefix[:4096]:
        raise AIIngestExcluded("Developer-only document is excluded from AI ingestion")
