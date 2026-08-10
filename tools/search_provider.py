from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class SearchProviderResult:
    title: str
    url: str
    snippet: str | None = None
    publisher: str | None = None


class SearchProvider(Protocol):
    async def search(
        self,
        query: str,
        *,
        limit: int = 8,
        region: str = "us-en",
        freshness: str | None = None,
        domain: str | None = None,
    ) -> list[SearchProviderResult]:
        ...