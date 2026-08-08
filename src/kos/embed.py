"""Embeddings del Knowledge OS (§23).

Proveedores: ollama (bge-m3, local, 1024 dims) | openai-compatible (/embeddings).
Registra conteo en processing_costs vía embedding_batch.
"""
from __future__ import annotations

import logging

import httpx

from kos.config import settings

log = logging.getLogger("kos.embed")


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    if settings.embedding_provider == "ollama":
        return await _ollama_embed(texts)
    return await _openai_embed(texts)


async def _ollama_embed(texts: list[str]) -> list[list[float]]:
    url = settings.embedding_base_url.replace("/v1", "") + "/api/embed"
    async with httpx.AsyncClient(timeout=180) as cli:
        r = await cli.post(url, json={"model": settings.embedding_model, "input": texts})
        r.raise_for_status()
        data = r.json()
    return data["embeddings"]


async def _openai_embed(texts: list[str]) -> list[list[float]]:
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"}
    async with httpx.AsyncClient(timeout=180) as cli:
        r = await cli.post(
            settings.llm_base_url.rstrip("/") + "/embeddings",
            json={"model": settings.embedding_model, "input": texts},
            headers=headers,
        )
        r.raise_for_status()
        data = r.json()
    return [item["embedding"] for item in data["data"]]


def dimension() -> int:
    return settings.embedding_dimension