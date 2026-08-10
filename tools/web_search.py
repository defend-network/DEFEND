from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from urllib.parse import urlparse

from tool_sdk import (
    DefendTool,
    ToolContext,
    ToolResult,
    ToolError,
    ToolErrorCode,
    RiskLevel,
    SideEffect,
    ToolPermission,
    DataClassification,
    SourceRef,
)
from bootstrap_models import WebSearchInput, WebSearchOutput, WebSearchResult
from tools.ddgs_provider import DDGSSearchProvider


def source_id_for_url(url: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return f"src_{digest}"


def _media_type_hint(url: str) -> str:
    path = (urlparse(url).path or "").lower()
    if path.endswith(".pdf"):
        return "pdf"
    if path.endswith((".doc", ".docx", ".xls", ".xlsx", ".xlsm")):
        return "document"
    return "html"


class _SimpleHit:
    __slots__ = ("title", "url", "snippet", "publisher")

    def __init__(self, title: str, url: str, snippet: str, publisher: str | None = None):
        self.title = title
        self.url = url
        self.snippet = snippet
        self.publisher = publisher


async def _tavily_search(query: str, limit: int) -> list[_SimpleHit]:
    import httpx

    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY not set")

    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": max(1, min(limit, 10)),
        "search_depth": "advanced",
        "include_answer": False,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post("https://api.tavily.com/search", json=payload)
        r.raise_for_status()
        data = r.json()

    hits: list[_SimpleHit] = []
    for item in data.get("results") or []:
        url = (item.get("url") or "").strip()
        if not url:
            continue
        hits.append(
            _SimpleHit(
                title=(item.get("title") or "").strip() or url,
                url=url,
                snippet=(item.get("content") or item.get("snippet") or "").strip(),
                publisher=None,
            )
        )
    return hits


class WebSearchTool(DefendTool[WebSearchInput, WebSearchOutput]):
    name = "web.search"
    description = "Search the public web and return ranked results with titles, URLs, and snippets."
    version = "1.1.0"

    input_model = WebSearchInput
    output_model = WebSearchOutput

    permissions = frozenset({ToolPermission.NETWORK, ToolPermission.READ_EXTERNAL})
    risk_level = RiskLevel.LOW
    side_effect = SideEffect.READ
    idempotent = True
    parallel_safe = True
    timeout_seconds = 30.0
    max_input_classification = DataClassification.PUBLIC
    max_output_classification = DataClassification.PUBLIC

    def __init__(self, provider=None):
        self.provider = provider or DDGSSearchProvider()

    async def execute(
        self,
        args: WebSearchInput,
        context: ToolContext,
    ) -> ToolResult[WebSearchOutput]:
        try:
            raw: list = []
            used = "ddgs"

            # Prefer Tavily when key is present
            if os.getenv("TAVILY_API_KEY", "").strip():
                try:
                    raw = await _tavily_search(args.query, args.limit)
                    used = "tavily"
                except Exception:
                    # Fall back to DDGS rather than failing the whole research path
                    raw = []
                    used = "ddgs_fallback"

            if not raw:
                raw = await self.provider.search(
                    args.query,
                    limit=args.limit,
                    region=args.region,
                    freshness=args.freshness.value if args.freshness else None,
                    domain=args.domain,
                )
                if used != "ddgs_fallback":
                    used = "ddgs"

            retrieved_at = datetime.now(timezone.utc)
            results: list[WebSearchResult] = []

            for i, item in enumerate(raw):
                url = getattr(item, "url", None) or ""
                if not url:
                    continue

                parsed = urlparse(url)
                domain = (parsed.netloc or "").lower().removeprefix("www.") or None
                media_hint = _media_type_hint(url)
                sid = source_id_for_url(url)

                results.append(
                    WebSearchResult(
                        source_id=sid,
                        title=getattr(item, "title", None) or url,
                        url=url,
                        snippet=getattr(item, "snippet", None),
                        publisher=getattr(item, "publisher", None),
                        published_at=None,
                        retrieved_at=retrieved_at,
                        score=None,
                        domain=domain,
                        media_type_hint=media_hint,
                        rank=i,
                    )
                )

            sources = [
                SourceRef(
                    source_id=r.source_id,
                    url=r.url,
                    title=r.title,
                    retrieved_at=retrieved_at.isoformat(),
                )
                for r in results
            ]

            return ToolResult(
                ok=True,
                data=WebSearchOutput(results=results),
                sources=sources,
            )

        except Exception as e:
            return ToolResult(
                ok=False,
                error=ToolError(
                    code=ToolErrorCode.UPSTREAM_ERROR,
                    message=str(e),
                    retryable=True,
                ),
            )
