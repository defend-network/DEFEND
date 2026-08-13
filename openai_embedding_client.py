from __future__ import annotations

import math
from typing import Any

import httpx


class OpenAIEmbeddingClient:
    """Bounded OpenAI-compatible embeddings client for localhost model services."""

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        api_key: str,
        timeout: float = 120.0,
        batch_size: int = 32,
        vector_dim: int = 1024,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("embedding model must be a non-empty string")
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("embedding base URL must be a non-empty string")
        if not isinstance(api_key, str) or not api_key:
            raise ValueError("embedding API key must not be empty")
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size <= 0:
            raise ValueError("embedding batch size must be a positive integer")
        if isinstance(vector_dim, bool) or not isinstance(vector_dim, int) or vector_dim <= 0:
            raise ValueError("embedding vector dimension must be a positive integer")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("embedding timeout must be positive")

        normalized = base_url.rstrip("/")
        if normalized.endswith("/v1"):
            normalized = normalized[:-3]
        self.model = model.strip()
        self.base_url = normalized
        self.batch_size = batch_size
        self.vector_dim = vector_dim
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=float(timeout),
            transport=transport,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not isinstance(texts, list) or not all(isinstance(text, str) for text in texts):
            raise TypeError("embedding inputs must be a list of strings")

        output: list[list[float]] = []
        for offset in range(0, len(texts), self.batch_size):
            batch = texts[offset : offset + self.batch_size]
            try:
                response = await self._client.post(
                    "/v1/embeddings",
                    json={"model": self.model, "input": batch, "encoding_format": "float"},
                )
                response.raise_for_status()
                payload = response.json()
                output.extend(self._validated_batch(payload, len(batch)))
            except RuntimeError:
                raise
            except Exception as error:
                raise RuntimeError(
                    f"embedding request failed ({type(error).__name__})"
                ) from None
        return output

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self.embed_documents([text])
        return vectors[0]

    async def healthcheck(self) -> bool:
        try:
            response = await self._client.get("/v1/models")
            response.raise_for_status()
            data = response.json().get("data", [])
            return any(
                isinstance(item, dict) and item.get("id") == self.model
                for item in data
            )
        except Exception:
            return False

    async def close(self) -> None:
        await self._client.aclose()

    def _validated_batch(self, payload: Any, expected: int) -> list[list[float]]:
        try:
            rows = payload["data"]
            if not isinstance(rows, list) or len(rows) != expected:
                raise ValueError
            ordered: list[list[float] | None] = [None] * expected
            for row in rows:
                index = row["index"]
                vector = row["embedding"]
                if (
                    isinstance(index, bool)
                    or not isinstance(index, int)
                    or not 0 <= index < expected
                    or ordered[index] is not None
                    or not isinstance(vector, list)
                    or len(vector) != self.vector_dim
                    or any(
                        isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or not math.isfinite(float(value))
                        for value in vector
                    )
                ):
                    raise ValueError
                ordered[index] = [float(value) for value in vector]
            if any(vector is None for vector in ordered):
                raise ValueError
            return [vector for vector in ordered if vector is not None]
        except (KeyError, TypeError, ValueError):
            raise RuntimeError("invalid embedding response") from None
