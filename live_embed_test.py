from __future__ import annotations

import asyncio
from ollama_embedding_client import OllamaEmbeddingClient


async def main():
    client = OllamaEmbeddingClient()
    try:
        ok = await client.healthcheck()
        print("Embedding model present:", ok)
        if not ok:
            print("Pull it: ollama pull qwen3-embedding:0.6b")
            return

        vecs = await client.embed_documents(
            [
                "Black adult imprisonment rates BJS",
                "Florida HVAC contractor licensing",
            ]
        )
        q = await client.embed_query("imprisonment rate by race")
        print("doc dims:", len(vecs[0]), "query dims:", len(q))
        print("ok")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())