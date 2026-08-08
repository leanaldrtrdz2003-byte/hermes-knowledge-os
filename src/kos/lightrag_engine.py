"""Motor LightRAG 1.5.6 del Knowledge OS (§3).

Backends de producción:
  KV + DocStatus → PostgreSQL (PGKVStorage / PGDocStatusStorage)
  Vectores       → Qdrant        (QdrantVectorDBStorage)
  Grafo interno  → NetworkXStorage (JSON derivado; el KG estructural es Graphify)
LLM/embeddings   → Ollama local (qwen2.5:7b / bge-m3) — cero coste.

LightRAG recibe los storages por NOMBRE y lee su conexión desde env vars;
este módulo normaliza el entorno desde nuestra Settings antes de construir.
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

from lightrag import LightRAG, QueryParam
from lightrag.llm.openai import openai_complete_if_cache
from lightrag.llm.ollama import ollama_embed

from kos.config import settings

log = logging.getLogger("kos.lightrag")

_rag: LightRAG | None = None
_inited = False


def _normalize_env() -> None:
    """LightRAG lee POSTGRES_*/QDRANT_*; alinearlos con nuestro .env."""
    os.environ.setdefault("POSTGRES_USER", os.environ.get("POSTGRES_USER", "kos"))
    os.environ.setdefault("POSTGRES_PASSWORD", os.environ.get("POSTGRES_PASSWORD", "kos"))
    os.environ.setdefault("POSTGRES_DATABASE", os.environ.get("POSTGRES_DB", "knowledge_os"))
    os.environ.setdefault("POSTGRES_HOST", os.environ.get("POSTGRES_HOST", "localhost"))
    os.environ.setdefault("POSTGRES_PORT", os.environ.get("POSTGRES_PORT", "5432"))
    os.environ.setdefault("QDRANT_URL", settings.qdrant_url)
    if settings.qdrant_api_key:
        os.environ.setdefault("QDRANT_API_KEY", settings.qdrant_api_key)


async def _zen_complete(prompt: str, system_prompt: str | None = None,
                        history_messages: list[dict] | None = None,
                        keyword_extraction: bool = False, **_extra: object) -> Any:
    """Wrapper firma-agnóstico: LightRAG 1.5.6 llama (prompt, system_prompt,
    history…, hashing_kv…); openai_complete_if_cache espera (model, prompt, …).
    Los kwargs extra se ignoran a propósito (chocan con la firma).
    Fallback a la cadena de Hermes (zen → opencode-go) si el primario falla."""
    try:
        return await openai_complete_if_cache(
            settings.llm_model, prompt,
            system_prompt=system_prompt,
            history_messages=history_messages,
            keyword_extraction=keyword_extraction,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
        )
    except Exception as exc:  # noqa: BLE001
        if not (settings.llm_fallback_base_url and settings.llm_fallback_api_key):
            raise
        log.warning("LightRAG LLM %s falló (%s); fallback → %s", settings.llm_model, exc,
                    settings.llm_fallback_model)
        return await openai_complete_if_cache(
            settings.llm_fallback_model, prompt,
            system_prompt=system_prompt,
            history_messages=history_messages,
            keyword_extraction=keyword_extraction,
            base_url=settings.llm_fallback_base_url,
            api_key=settings.llm_fallback_api_key,
        )


def build() -> LightRAG:
    global _rag
    if _rag is not None:
        return _rag
    _normalize_env()
    (settings.data_dir / "lightrag").mkdir(parents=True, exist_ok=True)
    _rag = LightRAG(
        working_dir=str(settings.data_dir / "lightrag"),
        kv_storage="PGKVStorage",
        vector_storage="QdrantVectorDBStorage",
        graph_storage="NetworkXStorage",
        doc_status_storage="PGDocStatusStorage",
        llm_model_func=_zen_complete,
        llm_model_name=settings.llm_model,
        llm_model_kwargs={},
        embedding_func=ollama_embed,
        chunk_token_size=settings.chunk_size,
        chunk_overlap_token_size=settings.chunk_overlap,
        top_k=30,
        log_level=logging.WARNING,
    )
    return _rag


async def init() -> None:
    rag = build()
    await rag.initialize_storages()
    log.info("LightRAG inicializado (storages PG+Qdrant+NetworkX)")


async def _ensure_ready() -> None:
    global _inited
    if not _inited:
        await init()
        _inited = True


async def insert(doc_id: str, text_or_path: str, *, is_file: bool = False) -> None:
    """Inserta un documento. is_file=True → ruta a archivo (parser nativo);
    False → texto puro chunkado por LightRAG."""
    await _ensure_ready()
    rag = build()
    if is_file:
        await rag.ainsert(text_or_path, ids=[doc_id], file_paths=[text_or_path])
    else:
        await rag.ainsert(text_or_path, ids=[doc_id])
    log.info("LightRAG insertado doc %s", doc_id)


async def query(question: str, mode: str = "hybrid", top_k: int = 20) -> dict:
    """Consulta LightRAG. mode: naive|local|global|hybrid|mix."""
    await _ensure_ready()
    rag = build()
    param = QueryParam(mode=mode, top_k=top_k, chunk_top_k=min(top_k, 20),
                       response_type="Multiple Paragraphs", include_references=True)
    res = await rag.aquery(question, param=param)
    if isinstance(res, tuple):
        answer, context = res
        return {"answer": answer, "context": context}
    return {"answer": res, "context": None}


async def delete_doc(doc_id: str) -> None:
    rag = build()
    await rag.adelete_by_doc_id(doc_id)


def close() -> None:
    global _rag
    if _rag is not None:
        try:
            _rag.finalize()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
        _rag = None