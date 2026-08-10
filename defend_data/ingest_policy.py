import posixpath
from urllib.parse import unquote, urlsplit


class AIIngestExcluded(ValueError):
    pass


def assert_ai_ingest_allowed(*, filename: str, content_prefix: bytes | str | None = None) -> None:
    source = filename.replace("\\", "/")
    if "://" in source or source.startswith("//"):
        source = urlsplit(source).path
    normalized = posixpath.normpath(unquote(source)).lstrip("/").lower()
    prefix = content_prefix.decode("utf-8", "ignore") if isinstance(content_prefix, bytes) else (content_prefix or "")
    if normalized.startswith("docs/superpowers/") or "DEFEND-AI-INGEST: EXCLUDE" in prefix[:4096]:
        raise AIIngestExcluded("Developer-only document is excluded from AI ingestion")
