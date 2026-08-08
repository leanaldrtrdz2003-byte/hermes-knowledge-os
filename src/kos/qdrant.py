"""Índice vectorial Qdrant (§7) — colección con payload de filtrado multi-tenant.

Payload por punto: document_id, chunk_id, source_id, language, domain,
tenant, knowledge_type (world|agent_memory), version, timestamp, embedding_model.
"""
from __future__ import annotations

import logging
import time

from qdrant_client import QdrantClient, models

from kos.config import settings

log = logging.getLogger("kos.qdrant")


def _client() -> QdrantClient:
    return QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key or None,
    )


def ensure_collection() -> None:
    c = _client()
    if not c.collection_exists(settings.vector_collection):
        c.create_collection(
            collection_name=settings.vector_collection,
            vectors_config=models.VectorParams(
                size=settings.embedding_dimension,
                distance=models.Distance.COSINE,
            ),
        )
        log.info("colección %s creada (dim=%d)", settings.vector_collection, settings.embedding_dimension)
    c.close()


def upsert_chunks(chunks: list[dict], embeddings: list[list[float]],
                  payload_base: dict | None = None) -> int:
    """chunks: [{chunk_id, doc_id, idx, heading, body, …}]; embeddings alineados."""
    if not chunks:
        return 0
    c = _client()
    points = [
        models.PointStruct(
            id=chunks[i]["chunk_id"],
            vector=embeddings[i],
            payload={
                "document_id": (payload_base or {}).get("doc_id") or chunks[i].get("doc_id"),
                "chunk_id": chunks[i]["chunk_id"],
                "idx": chunks[i].get("idx", i),
                "heading": chunks[i].get("heading", ""),
                "body": (chunks[i].get("body") or chunks[i].get("content") or "")[:2000],
                "language": payload_base.get("language") if payload_base else None,
                "domain": (payload_base or {}).get("domain"),
                "tenant": (payload_base or {}).get("tenant", settings.tenant),
                "knowledge_type": (payload_base or {}).get("knowledge_type", "world"),
                "version": (payload_base or {}).get("version", 1),
                "timestamp": int(time.time()),
                "embedding_model": settings.embedding_model,
            },
        )
        for i in range(len(chunks))
    ]
    c.upsert(collection_name=settings.vector_collection, points=points)
    return len(points)


def search(vector: list[float], *, top_k: int = 10, filters: dict | None = None) -> list[dict]:
    c = _client()
    must = []
    for k, v in (filters or {}).items():
        must.append(models.FieldCondition(key=k, match=models.MatchValue(value=v)))
    res = c.query_points(
        collection_name=settings.vector_collection,
        query=vector,
        limit=top_k,
        query_filter=models.Filter(must=must) if must else None,
        with_payload=True,
    )
    return [
        {"chunk_id": p.payload["chunk_id"], "doc_id": p.payload.get("document_id"),
         "score": p.score, "heading": p.payload.get("heading"),
         "body": p.payload.get("body"), "tenant": p.payload.get("tenant")}
        for p in res.points
    ]


def count() -> int:
    return _client().count(collection_name=settings.vector_collection).count