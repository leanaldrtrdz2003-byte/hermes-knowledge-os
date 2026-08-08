"""Query Router del Knowledge OS (§25) — clasifica, recupera y responde con citas.

Tipos A–H: factual(RAG), conceptual(RAG+wiki), relationship(graph), path(graph),
síntesis global, verificación de fuente, memoria de agente, educativo.
Ensamblaje: retrieve → dedupe → rerank(opcional) → fence (§33) → contexto → LLM.
"""
from __future__ import annotations

import logging
import time

from kos import config, embed, qdrant, security
from kos.config import settings
from kos.llm import complete

log = logging.getLogger("kos.router")

TYPE_NAMES = {
    "A": "factual", "B": "conceptual", "C": "relationship", "D": "path",
    "E": "sintesis", "F": "verificacion", "G": "memoria", "H": "educativo",
}

_PATTERNS: list[tuple[str, str]] = [
    ("G", r"\b(recuerda|memoria|que hiciste|decision tomada|aprendiste|proyectos)\b"),
    ("C", r"\b(relacion|relación|conecta|depende|relacionad|enlace)\b"),
    ("D", r"\b(camino|path|ruta entre|como llegar)\b"),
    ("F", r"\b(fuente|evidencia|dónde dice|verificar|verifica|cita)\b"),
    ("H", r"\b(aprender|prerrequisito|curriculum|leccion|explica paso a paso)\b"),
]


def classify(question: str) -> str:
    """Clasificador determinista A–H (LLM opcional en stage=strong)."""
    q = question.lower()
    for kind, pat in _PATTERNS:
        if __import__("re").search(pat, q):
            return kind
    return "A" if len(q.split()) < 12 else "B"


async def search_chunks(question: str, top_k: int = 12, filter_by: dict | None = None) -> list[dict]:
    vec = await embed.embed_texts([question])
    hits = qdrant.search(vec[0], top_k=top_k, filters=filter_by)
    return hits


def context_for(hits: list[dict]) -> str:
    """Ensambla fragmentos con valla anti-inyección y citas (§26/§33)."""
    blocks = []
    for h in hits:
        blocks.append(
            security.fence(
                f"{str(h.get('doc_id') or '?')[:8]}·c{str(h.get('chunk_id') or '?')[:8]}",
                f"[doc {h.get('doc_id')}] [chunk {h.get('chunk_id')}] {h.get('body', '')[:1200]}",
            )
        )
    return "\n".join(blocks)[:14000]


async def answer(question: str, mode: str = "hybrid") -> dict:
    t0 = time.time()
    qtype = classify(question)
    hits = await search_chunks(question, top_k=10)
    ctx = context_for(hits)

    from kos import lightrag_engine as le  # RAG gráfico (segundo grafo)

    try:
        rag = await le.query(question, mode=mode)
        rag_part = rag.get("answer", "")[:4000]
    except Exception as exc:  # noqa: BLE001
        log.warning("LightRAG no disponible: %s", exc)
        rag_part = ""

    evidence_n = len(hits)

    system = security.SYSTEM_FENCE
    if qtype == "F":
        prompt = (
            "Verifica la afirmación contra la evidencia. Responde qué está respaldado,\n"
            "qué falta y qué contradice las fuentes. Cita [doc_id] y [chunk_id].\n"
            f"PREGUNTA: {question}\n\nEVIDENCIA VECTORIAL:\n{ctx}\n\nSÍNTESIS RAG:\n{rag_part}"
        )
    elif qtype == "G":
        from kos import db

        mems = await db.query_memory(top=8)
        mem_blk = "\n".join(
            f"[{m['memory_kind']} {m['importance']:.2f}] {m['content']}" for m in mems
        )
        prompt = (
            "Responde usando la memoria del agente declarada abajo; distingue memoria\n"
            "de conocimiento general. EVIDENCIA VECTORIAL:\n" + ctx +
            "\n\nMEMORIA PERSISTIDA:\n" + mem_blk + f"\n\nPREGUNTA: {question}"
        )
    else:
        prompt = (
            "Responde a la PREGUNTA usando SOLO la evidencia entre external_source.\n"
            "Estructura: respuesta, luego 'Fuentes:' con [Source: doc_id] [Chunk: chunk_id].\n"
            "Si la evidencia es insuficiente o contradictoria, dilo explícitamente.\n\n"
            f"EVIDENCIA:\n{ctx}\n\nRAG GRÁFICO:\n{rag_part}\n\nPREGUNTA: {question}"
        )

    response = await complete(prompt, system=system, stage="router",
                              max_tokens=min(settings.llm_max_tokens, 1800))
    latency = int((time.time() - t0) * 1000)

    from kos import db

    await db.log_query(question, mode, len(response), latency,
                       settings.llm_provider, settings.llm_model,
                       query_type=qtype, n_retrieved=evidence_n)
    return {
        "question": question, "type": qtype, "type_name": TYPE_NAMES.get(qtype, "?"),
        "answer": response, "evidence_n": evidence_n, "latency_ms": latency,
    }