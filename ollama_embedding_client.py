from __future__ import annotations

import httpx


class OllamaEmbeddingClient:
    def __init__(
        self,
        model: str = "qwen3-embedding:0.6b",
        base_url: str = "http://127.0.0.1:11434",
        timeout: float = 120.0,
        batch_size: int = 32,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.batch_size = batch_size
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            resp = await self._client.post(
                "/api/embed",
                json={
                    "model": self.model,
                    "input": batch,
                    "truncate": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            embeddings = data.get("embeddings")
            if not embeddings or len(embeddings) != len(batch):
                raise RuntimeError(
                    f"Embedding batch failed: expected {len(batch)}, got {0 if not embeddings else len(embeddings)}"
                )
            out.extend(embeddings)
        return out

    async def embed_query(self, text: str) -> list[float]:
        vecs = await self.embed_documents([text])
        return vecs[0]

    async def healthcheck(self) -> bool:
        try:
            resp = await self._client.get("/api/tags")
            resp.raise_for_status()
            names = [m.get("name", "") for m in resp.json().get("models", [])]
            return any(self.model in n for n in names)
        except Exception:
            return False

    async def close(self) -> None:
        await self._client.aclose()