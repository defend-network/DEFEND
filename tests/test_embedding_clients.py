from __future__ import annotations

import json
import math
import asyncio
from functools import wraps

import httpx
import pytest

from openai_embedding_client import OpenAIEmbeddingClient


def run_async(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return wrapped


def vector(value: float) -> list[float]:
    return [value] * 1024


@run_async
async def test_openai_client_batches_authenticates_and_restores_index_order():
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content)
        assert request.headers["authorization"] == "Bearer test-embedding-key"
        assert body["model"] == "Qwen/Qwen3-Embedding-0.6B"
        data = [
            {"index": index, "embedding": vector(float(len(text)))}
            for index, text in reversed(list(enumerate(body["input"])))
        ]
        return httpx.Response(200, json={"data": data})

    client = OpenAIEmbeddingClient(
        model="Qwen/Qwen3-Embedding-0.6B",
        base_url="http://127.0.0.1:8002",
        api_key="test-embedding-key",
        batch_size=2,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await client.embed_documents(["a", "bb", "ccc"])
    finally:
        await client.close()

    assert [item[0] for item in result] == [1.0, 2.0, 3.0]
    assert [request.url.path for request in requests] == [
        "/v1/embeddings",
        "/v1/embeddings",
    ]


@run_async
async def test_openai_client_healthcheck_verifies_served_model():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(
            200,
            json={"data": [{"id": "Qwen/Qwen3-Embedding-0.6B"}]},
        )

    client = OpenAIEmbeddingClient(
        model="Qwen/Qwen3-Embedding-0.6B",
        base_url="http://127.0.0.1:8002/v1",
        api_key="test-embedding-key",
        transport=httpx.MockTransport(handler),
    )
    try:
        assert await client.healthcheck()
    finally:
        await client.close()


@pytest.mark.parametrize(
    "embedding",
    [[1.0], [math.nan] * 1024, ["bad"] * 1024],
)
@run_async
async def test_openai_client_rejects_malformed_vectors_without_leaking_key(embedding):
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=json.dumps({"data": [{"index": 0, "embedding": embedding}]}),
            headers={"content-type": "application/json"},
        )

    client = OpenAIEmbeddingClient(
        model="Qwen/Qwen3-Embedding-0.6B",
        base_url="http://127.0.0.1:8002",
        api_key="test-embedding-key",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(RuntimeError, match="invalid embedding response") as raised:
            await client.embed_query("query")
    finally:
        await client.close()

    assert "test-embedding-key" not in str(raised.value)


@run_async
async def test_openai_client_empty_input_makes_no_request():
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    client = OpenAIEmbeddingClient(
        model="Qwen/Qwen3-Embedding-0.6B",
        base_url="http://127.0.0.1:8002",
        api_key="test-embedding-key",
        transport=httpx.MockTransport(handler),
    )
    try:
        assert await client.embed_documents([]) == []
    finally:
        await client.close()
    assert calls == 0
