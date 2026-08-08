"""Acceso a PostgreSQL (control plane del Knowledge OS).

Incluye: pool asyncpg, aplicación de schema, cola de jobs reanudable (§20),
doc-status, costes y helpers de observabilidad.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path

import asyncpg

from kos.config import settings

log = logging.getLogger("kos.db")


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(dsn=settings.pg_dsn, min_size=1, max_size=10)
    return _pool


async def apply_schema() -> None:
    """Idempotente: ejecuta schema.sql si las tablas no existen aún."""
    pool = await get_pool()
    has_tables = await pool.fetchval(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='sources')"
    )
    if not has_tables:
        sql = (Path(__file__).parent / "db" / "schema.sql").read_text()
        await pool.execute(sql)
    # migraciones idempotentes sobre esquema ya aplicado
    await pool.execute("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS has_embedding boolean NOT NULL DEFAULT FALSE")
    await pool.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_ingestion_status ON ingestion_status(doc_id, pipeline)")
    for col, ddl in {
        "question": "text", "mode": "text", "answer_chars": "int",
        "provider": "text", "model": "text",
    }.items():
        await pool.execute(f"ALTER TABLE queries_log ADD COLUMN IF NOT EXISTS {col} {ddl}")
    log.info("Schema PostgreSQL aplicado (control plane listo)")


# ═══════════════ JOBS (§20) ═══════════════

async def enqueue(doc_id: str, job_type: str) -> str | None:
    """Encola un job si no existe ya uno no terminado para (doc, stage)."""
    pool = await get_pool()
    return await pool.fetchval(
        """INSERT INTO ingestion_jobs (doc_id, job_type, status)
           VALUES ($1::uuid, $2, 'queued')
           ON CONFLICT DO NOTHING
           RETURNING job_id::text""",
        doc_id, job_type,
    )


async def has_done_job(doc_id: str) -> bool:
    pool = await get_pool()
    return bool(await pool.fetchval(
        "SELECT EXISTS (SELECT 1 FROM ingestion_jobs WHERE doc_id = $1::uuid AND status IN ('done','skipped'))",
        doc_id,
    ))


async def reset_stale_jobs(worker: str | None = None) -> int:
    """Reanudable (§17): jobs 'running' de ejecuciones huérfanas vuelven a 'queued'.
    Con worker=None resetea cualquier 'running' (despliegue de un solo worker)."""
    pool = await get_pool()
    if worker:
        rows = await pool.fetch(
            "UPDATE ingestion_jobs SET status='queued', error=NULL "
            "WHERE status='running' AND worker=$1 RETURNING job_id",
            worker,
        )
    else:
        rows = await pool.fetch(
            "UPDATE ingestion_jobs SET status='queued', error=NULL "
            "WHERE status='running' RETURNING job_id",
        )
    return len(rows)


async def reset_failed_jobs() -> int:
    """Re-encola jobs fallidos (reanudable, §17)."""
    pool = await get_pool()
    rows = await pool.fetch(
        "UPDATE ingestion_jobs SET status='queued', error=NULL "
        "WHERE status='failed' RETURNING job_id",
    )
    return len(rows)


async def claim_job(worker: str, job_types: list[str] | None = None) -> dict | None:
    """Reserva atómicamente el job más antiguo (única fila, sin JOIN)."""
    pool = await get_pool()
    type_filter = "AND job_type = ANY($2::text[])" if job_types else ""
    params: list = [worker]
    if job_types:
        params.append(job_types)
    row = await pool.fetchrow(
        f"""UPDATE ingestion_jobs
            SET status='running', attempt=attempt+1, started_at=now(), worker=$1
            WHERE job_id = (
              SELECT job_id FROM ingestion_jobs
              WHERE status='queued' {type_filter}
              ORDER BY created_at LIMIT 1
              FOR UPDATE SKIP LOCKED)
            RETURNING job_id::text, doc_id::text, job_type, status""",
        *params,
    )
    return dict(row) if row else None


async def finish_job(job_id: str, ok: bool = True, error: str | None = None) -> None:
    pool = await get_pool()
    await pool.execute(
        """UPDATE ingestion_jobs SET status=$2, finished_at=now(), error=$3 WHERE job_id=$1::uuid""",
        job_id, "done" if ok else "failed", error,
    )
    if not ok:
        await pool.execute(
            "INSERT INTO processing_errors(job_id, stage, message) VALUES ($1::uuid, 'worker', $2)",
            job_id, (error or "unknown")[:4000],
        )


async def retry_job(job_id: str) -> None:
    pool = await get_pool()
    await pool.execute("UPDATE ingestion_jobs SET status='queued', error=NULL WHERE job_id=$1::uuid", job_id)


# alias usado por el worker
finish = finish_job


async def doc_status(doc_id: str, pipeline: str, status: str, message: str = "") -> None:
    pool = await get_pool()
    await pool.execute(
        """INSERT INTO ingestion_status(doc_id, pipeline, status, message, updated_at)
           VALUES ($1::uuid, $2, $3::doc_status, $4, now())
           ON CONFLICT (doc_id)
           DO UPDATE SET pipeline=$2, status=$3::doc_status, message=$4, updated_at=now()""",
        doc_id, pipeline, status, message,
    )


async def mark_job_skipped(job_id: str) -> None:
    pool = await get_pool()
    await pool.execute("UPDATE ingestion_jobs SET status='skipped' WHERE job_id=$1::uuid", job_id)


async def log_cost(stage: str, provider: str, model: str, inp: int = 0, out: int = 0,
                   cost: float = 0.0, job_id: str | None = None, embeds: int = 0) -> None:
    pool = await get_pool()
    await pool.execute(
        """INSERT INTO processing_costs(job_id, stage, provider, model, input_tokens, output_tokens, est_cost_usd, embed_count)
           VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8)""",
        job_id, stage, provider, model, inp, out, cost, embeds,
    )


# ═══════════════ DOCUMENTOS ═══════════════

async def upsert_source_and_doc(*, title: str, content_hash: str, mime_type: str,
                                source_type: str, uri: str | None = None,
                                language: str | None = None) -> dict:
    """Crea source (inmutable) + document (versionado). Dedupe por hash.

    Retorna {source_id, doc_id, is_new, version}. Si el hash ya existe,
    devuelve el doc existente con is_new=False (no reprocesa, §9/§18).
    """
    pool = await get_pool()
    existing = await pool.fetchrow(
        "SELECT s.source_id, d.doc_id FROM sources s "
        "JOIN documents d ON d.source_id = s.source_id "
        "WHERE s.checksum_sha256 = $1 ORDER BY d.version DESC LIMIT 1",
        content_hash,
    )
    if existing:
        return {"source_id": existing["source_id"], "doc_id": existing["doc_id"],
                "is_new": False, "version": 1}
    src_id = await pool.fetchval(
        """INSERT INTO sources(source_type, source_uri, title, mime_type, language, checksum_sha256)
           VALUES ($1, $2, $3, $4, $5, $6) RETURNING source_id::text""",
        source_type, uri or "", title, mime_type, language, content_hash,
    )
    doc_id = await pool.fetchval(
        """INSERT INTO documents(source_id, title, content_hash, version)
           VALUES ($1::uuid, $2, $3, 1) RETURNING doc_id::text""",
        src_id, title or "untitled", content_hash,
    )
    return {"source_id": src_id, "doc_id": doc_id, "is_new": True, "version": 1}


async def set_chunk_batch(doc_id: str, chunks: list[dict]) -> int:
    """Persiste chunks (chunk_id derivado de doc+idx) e inserta en Qdrant."""
    from kos import qdrant
    pool = await get_pool()
    rows = []
    for c in chunks:
        rows.append({
            "doc_id": doc_id,
            "chunk_idx": c["idx"],
            "chunk_id": c["chunk_id"],
            "heading": c.get("heading", ""),
            "content": c["body"],
        })
    await pool.copy_records_to_table(
        "chunks", records=rows,
        columns=["doc_id", "idx", "chunk_id", "heading", "content"],
    )
    qdrant.upsert_chunks(chunks, [c["embedding"] for c in chunks if "embedding" in c],
                         {"tenant": settings.tenant})
    return len(rows)


# ═══════════════ MEMORIA (§12) ═══════════════

async def persist_memory(*, kind: str, text: str, importance: float,
                         dedupe_key: str, source_session: str | None = None) -> dict | None:
    """Inserta memoria si el dedupe_key no existe. None → duplicado."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """INSERT INTO agent_memory(memory_kind, content, importance, dedupe_key, source_session)
           VALUES ($1, $2, $3, $4, $5)
           ON CONFLICT DO NOTHING
           RETURNING memory_id::text, importance""",
        kind, text, importance, dedupe_key[:500], source_session,
    )
    if row is None:
        return None
    return {"memory_id": row["memory_id"], "importance": row["importance"]}


async def query_memory(kind: str | None = None, *, top: int = 20) -> list[dict]:
    pool = await get_pool()
    if kind:
        rows = await pool.fetch(
            "SELECT memory_id, memory_kind, content, importance, created_at "
            "FROM agent_memory WHERE memory_kind = $1 ORDER BY importance DESC, created_at DESC LIMIT $2",
            kind, top,
        )
    else:
        rows = await pool.fetch(
            "SELECT memory_id, memory_kind, content, importance, created_at "
            "FROM agent_memory ORDER BY importance DESC, created_at DESC LIMIT $1",
            top,
        )
    return [dict(r) for r in rows]


# ═══════════════ OBSERVABILIDAD (§30) ═══════════════

async def dashboard_stats() -> dict:
    pool = await get_pool()
    out = {}
    for key, sql in {
        "sources": "SELECT COUNT(*) FROM sources",
        "documents": "SELECT COUNT(*) FROM documents",
        "document_versions": "SELECT COUNT(*) FROM document_versions",
        "chunks": "SELECT COUNT(*) FROM chunks",
        "chunks_embedded": "SELECT COUNT(*) FROM chunks WHERE has_embedding",
        "entities": "SELECT COUNT(*) FROM entities",
        "relations": "SELECT COUNT(*) FROM relations",
        "claims": "SELECT COUNT(*) FROM claims",
        "memories": "SELECT COUNT(*) FROM agent_memory",
        "jobs_done": "SELECT COUNT(*) FROM ingestion_jobs WHERE status = 'done'",
        "jobs_failed": "SELECT COUNT(*) FROM ingestion_jobs WHERE status = 'failed'",
        "jobs_queued": "SELECT COUNT(*) FROM ingestion_jobs WHERE status = 'queued'",
        "llm_calls": "SELECT COUNT(*) FROM processing_costs",
        "llm_est_cost_usd": "SELECT COALESCE(SUM(est_cost_usd), 0) FROM processing_costs",
        "queries": "SELECT COUNT(*) FROM queries_log",
    }.items():
        val = await pool.fetchval(sql)
        out[key] = int(val or 0)
    return out


async def get_documents(limit: int = 100) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT doc_id::text, title, content_hash FROM documents ORDER BY created_at DESC LIMIT $1",
        limit,
    )
    return [dict(r) for r in rows]


async def get_versions() -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT component, name, version, commit_tag, active FROM pipeline_versions ORDER BY component, installed_at"
    )
    return [dict(r) for r in rows]


async def record_version(component: str, name: str, version: str, commit_tag: str | None = None) -> None:
    pool = await get_pool()
    await pool.execute(
        """INSERT INTO pipeline_versions(component, name, version, commit_tag, active)
           VALUES ($1, $2, $3, $4, true)
           ON CONFLICT (component, name, version) DO UPDATE SET active = true""",
        component, name, version, commit_tag,
    )


# ═══════════════ DETALLE CHUNKS (pipeline) ═══════════════
async def log_hash(sha256: str, kind: str, ref_type: str, ref_id: str) -> None:
    pool = await get_pool()
    await pool.execute(
        """INSERT INTO hashes(sha256, kind, ref_type, ref_id)
           VALUES ($1, $2, $3, $4::uuid) ON CONFLICT DO NOTHING""",
        sha256, kind, ref_type, ref_id,
    )


async def clear_chunks(doc_id: str) -> None:
    pool = await get_pool()
    await pool.execute("DELETE FROM chunks WHERE doc_id = $1::uuid", doc_id)


async def bulk_insert_chunks(doc_id: str, chunks: list[dict]) -> None:
    """Inserta chunks (sin embeddings). El chunk_id lo genera PG."""
    pool = await get_pool()
    await pool.executemany(
        """INSERT INTO chunks (doc_id, idx, body_text, section_heading)
           VALUES ($1::uuid, $2, $3, $4)""",
        [(doc_id, c["idx"], c["body"], c.get("heading", "")) for c in chunks],
    )


async def load_chunks(doc_id: str) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT chunk_id::text, idx, section_heading AS heading, body_text AS content "
        "FROM chunks WHERE doc_id = $1::uuid ORDER BY idx",
        doc_id,
    )
    return [dict(r) for r in rows]


async def mark_chunks_embedded(doc_id: str, count: int) -> None:
    pool = await get_pool()
    await pool.execute("UPDATE chunks SET has_embedding = TRUE WHERE doc_id = $1::uuid", doc_id)


async def persist_graph_fragment(doc_id: str, frag: dict) -> None:
    """Entidades/relaciones extraídas (LLM) → PG con lineage al doc (§48)."""
    pool = await get_pool()
    id_map: dict[str, str] = {}
    for n in frag.get("nodes", []):
        eid = n.get("id") or n.get("label") or ""
        label = n.get("label") or eid
        row = await pool.fetchrow(
            """INSERT INTO entities(name, kind, canonical_name, domain)
               VALUES ($1, 'concept', $2, NULL)
               ON CONFLICT (canonical_name, kind) DO UPDATE SET name = EXCLUDED.name
               RETURNING entity_id::text""",
            label[:500], eid[:500],
        )
        if row:
            id_map[eid] = row["entity_id"]
    for e in frag.get("edges", []):
        src = id_map.get(e.get("source", ""))
        tgt = id_map.get(e.get("target", ""))
        if not src or not tgt:
            continue
        await pool.execute(
            """INSERT INTO relations(source_id, target_id, relation_type, confidence,
                                     source_doc, provenance)
               VALUES ($1::uuid, $2::uuid, $3, $4::rel_confidence, $5::uuid,
                       jsonb_build_object('doc_id', $5::text))
               ON CONFLICT DO NOTHING""",
            src, tgt, e.get("relation", "related_to")[:100],
            e.get("confidence", "INFERRED"), doc_id,
        )


async def log_query(question: str, mode: str, answer_chars: int, latency_ms: int,
                    provider: str, model: str, query_type: str | None = None,
                    n_retrieved: int | None = None) -> None:
    pool = await get_pool()
    await pool.execute(
        """INSERT INTO queries_log(query_hash, query_type, question, mode,
                                  n_retrieved, answer_chars, provider, model, latency_ms)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
        hashlib.sha256(question.encode()).hexdigest()[:16], query_type or mode,
        question[:500], mode, n_retrieved, answer_chars, provider, model, latency_ms,
    )