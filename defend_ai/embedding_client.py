from __future__ import annotations

from typing import Protocol


class EmbeddingClient(Protocol):
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    async def embed_query(self, text: str) -> list[float]:
        ...

    async def healthcheck(self) -> bool:
        ...

    async def close(self) -> None:
        ...