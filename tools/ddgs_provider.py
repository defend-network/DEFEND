from __future__ import annotations

import asyncio
from tools.search_provider import SearchProvider, SearchProviderResult


class DDGSSearchProvider:
    async def search(
        self,
        query: str,
        *,
        limit: int = 8,
        region: str = "us-en",
        freshness: str | None = None,
        domain: str | None = None,
    ) -> list[SearchProviderResult]:
        from ddgs import DDGS

        # Optional domain bias
        if domain:
            query = f"site:{domain} {query}"

        def _run():
            with DDGS() as ddgs:
                return list(
                    ddgs.text(
                        query,
                        max_results=limit,
                        region=region,
                        timelimit=freshness,
                    )
                )

        raw = await asyncio.to_thread(_run)

        results: list[SearchProviderResult] = []
        for item in raw:
            results.append(
                SearchProviderResult(
                    title=item.get("title") or "",
                    url=item.get("href") or item.get("link") or "",
                    snippet=item.get("body") or item.get("snippet"),
                    publisher=None,
                )
            )
        return results