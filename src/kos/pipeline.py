"""Pipeline de ingestión (§17) — etapas modulares, reanudables e idempotentes.

source → detección → parse → normalización → dedupe → chunk → embed →
graph → wiki → index → validate → ready.

Ejecución vía cola de jobs en PostgreSQL (§20): el worker extrae un job,
procesa la etapa y encadena la siguiente. Cada etapa es idempotente:
re-ejecutar un job fallido no duplica datos.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from kos import db, dedupe, embed, graph, lightrag_engine, qdrant, s3, security
from kos.config import settings

log = logging.getLogger("kos.pipeline")

# etapa → siguiente en la cadena
NEXT_STAGE: dict[str, str | None] = {
    "parse": "chunk",
    "chunk": "embed",
    "embed": "index",
    "index": "graph",
    "graph": "wiki",
    "wiki": None,
}

STAGES = tuple(NEXT_STAGE)
STAGE_ORDER = STAGES

# etapa → estado del enum doc_status (para ingestion_status)
STAGE_STATUS = {
    "parse": "parsed", "chunk": "chunked", "embed": "embedded",
    "index": "indexed", "graph": "graphed", "wiki": "wiki",
}


def _mime(p: Path) -> str:
    return {
        ".md": "text/markdown", ".txt": "text/plain", ".html": "text/html",
        ".htm": "text/html", ".pdf": "application/pdf", ".json": "application/json",
        ".csv": "text/csv", ".py": "text/x-python", ".sql": "text/x-sql",
    }.get(p.suffix.lower(), "application/octet-stream")


def _kind(p: Path) -> str:
    return {
        ".md": "documentation", ".txt": "documentation", ".html": "website",
        ".htm": "website", ".pdf": "paper", ".json": "dataset", ".csv": "dataset",
        ".py": "code", ".js": "code", ".sql": "code", ".ts": "code",
    }.get(p.suffix.lower(), "documentation")


def _strip_html(text: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s{2,}", "\n", text)


def parse_to_text(p: Path) -> str:
    """Extrae texto de un archivo de entrada (markdown/txt/html). PDF requiere pypdf."""
    suffix = p.suffix.lower()
    raw = p.read_bytes()
    if suffix in (".md", ".txt", ".json", ".csv", ".yaml", ".yml", ".toml", ".py", ".js", ".ts", ".sql", ".sh", ".rs", ".go", ".c", ".cpp", ".java"):
        return raw.decode("utf-8", errors="replace")
    if suffix in (".html", ".htm", ".xml"):
        return _strip_html(raw.decode("utf-8", errors="replace"))
    if suffix == ".pdf":
        try:
            import pypdf  # type: ignore[import-not-found]

            reader = pypdf.PdfReader(p)
            return "\n\n".join((page.extract_text() or "") for page in reader.pages)
        except ImportError:
            raise ValueError("PDF requiere pypdf (uv pip install pypdf)")
    raise ValueError(f"formato no soportado para texto: {suffix}")


async def stage_parse(item: dict, workdir: Path) -> dict:
    """Convierte a texto plano la copia local del source y deja staging."""
    doc_id = item["doc_id"]
    src_file = _staging_source(doc_id, workdir)
    text = parse_to_text(src_file)
    security.validate_text(text)
    digest = hashlib.sha256(text.encode()).hexdigest()
    staging = workdir / doc_id
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "content.txt").write_text(text, encoding="utf-8")
    (staging / "meta.json").write_text(
        json.dumps({"digest": digest, "title": src_file.stem, "mime": _mime(src_file),
                    "kind": _kind(src_file)}),
        encoding="utf-8",
    )
    await db.log_hash(digest, "content", "document", doc_id)
    return {"digest": digest}


def _staging_source(doc_id: str, workdir: Path) -> Path:
    """Localiza la copia del archivo original en staging (pattern source.<ext>)."""
    d = workdir / doc_id
    for p in d.glob("source.*"):
        return p
    raise FileNotFoundError(f"copia local de {doc_id} no encontrada en {d}")


async def stage_chunk(item: dict, workdir: Path) -> None:
    from kos import chunk as chunker
    doc_id = item["doc_id"]
    text = (workdir / doc_id / "content.txt").read_text(encoding="utf-8")
    chunks = chunker.make_chunks(doc_id, text)
    if not chunks:
        raise ValueError("sin chunks")
    # persistir en PG (sin embeddings aún)
    from kos import db
    await db.clear_chunks(doc_id)
    await db.bulk_insert_chunks(doc_id, chunks)
    log.info("doc %s: %d chunks", doc_id, len(chunks))


async def stage_embed(doc_id: str) -> None:
    from kos import db, embed, qdrant
    rows = await db.load_chunks(doc_id)
    if not rows:
        raise ValueError("sin chunks para embed")
    texts = [r["embedding" if "embedding" in r else "content"] for r in rows]
    vecs = await embed.embed_texts(texts)
    for r, v in zip(rows, vecs):
        r["embedding"] = v
    qdrant.upsert_chunks(rows, vecs, {"tenant": settings.tenant, "doc_id": doc_id})
    await db.mark_chunks_embedded(doc_id, count=len(rows))
    log.info("doc %s: %d vectores en Qdrant", doc_id, len(rows))


def _doc_text_path(doc_id: str, workdir: Path) -> Path:
    p = workdir / doc_id / "content.txt"
    if p.exists():
        return p
    raise FileNotFoundError(f"staging de {doc_id} no disponible")


async def stage_index(doc_id: str, workdir: Path) -> None:
    """Índice LightRAG completo (su propio chunking + grafo + vectores)."""
    await lightrag_engine.insert(doc_id, str(_doc_text_path(doc_id, workdir)), is_file=True)


async def stage_graph(doc_id: str, workdir: Path) -> None:
    """Extracción de entidades/relaciones (LLM local) → grafo estructural."""
    text = (workdir / doc_id / "content.txt").read_text(encoding="utf-8")[:12000]
    meta = __import__("json").loads((workdir / doc_id / "meta.json").read_text())
    title = meta.get("title", doc_id)
    frag = await graph.extract_docs_llm(title, text)
    await db.persist_graph_fragment(doc_id, frag)
    log.info("doc %s: %d nodos/%d edges (LLM)", doc_id, len(frag["nodes"]), len(frag["edges"]))


async def stage_wiki(doc_id: str, workdir: Path) -> None:
    """Compila página wiki por dominio si no está fresca (§9)."""
    from kos import wiki
    meta = __import__("json").loads((workdir / doc_id / "meta.json").read_text())
    title_base = meta.get("title", doc_id)
    chunks = await db.load_chunks(doc_id)
    evidence = [{"chunk_id": c["chunk_id"], "doc_id": doc_id, "text": c["content"]} for c in chunks[:15]]
    if not evidence:
        return
    await wiki.compile_page(f"{title_base} — síntesis", evidence)


async def run_stage(stage_name: str, item: dict, workdir: Path) -> None:
    """Dispatcher de etapas."""
    if stage_name == "parse":
        await stage_parse(item, workdir)
    elif stage_name == "chunk":
        await stage_chunk(item, workdir)
    elif stage_name == "embed":
        await stage_embed(item["doc_id"])
    elif stage_name == "index":
        await stage_index(item["doc_id"], workdir)
    elif stage_name == "graph":
        await stage_graph(item["doc_id"], workdir)
    elif stage_name == "wiki":
        await stage_wiki(item["doc_id"], workdir)
    else:
        raise ValueError(f"etapa desconocida: {stage_name}")


async def process_document(doc: dict, workdir: Path) -> dict | None:
    """Registrado: source/document en PG + copia local + MinIO + cadena de jobs."""
    src = await db.upsert_source_and_doc(
        title=doc["title"], content_hash=doc["content_hash"],
        mime_type=doc["mime_type"], source_type=doc["source_type"],
        uri=doc.get("uri"), language=doc.get("language"),
    )
    if not src["is_new"]:
        # re-ingest idempotente: re-encolar SOLO si el doc nunca se procesó
        if not await db.has_done_job(src["doc_id"]):
            for stage in STAGE_ORDER:
                await db.enqueue(src["doc_id"], stage)
        log.info("ya procesado (hash): %s", doc["title"])
        return None
    # copia local para staging (los workers no dependen de red para parse)
    local = Path(doc["path"])
    stage_dir = workdir / src["doc_id"]
    stage_dir.mkdir(parents=True, exist_ok=True)
    (stage_dir / f"source{local.suffix or '.md'}").write_bytes(local.read_bytes())
    # MinIO: versión 1 del objeto (inmutable)
    suffix = local.suffix or ".md"
    key = s3.upload(src["source_id"], _kind(local), 1, suffix, local.read_bytes())
    await db.doc_status(src["doc_id"], "minio", "detected", key)
    for stage in STAGE_ORDER:
        await db.enqueue(src["doc_id"], stage)
    return src


async def worker_loop(worker_id: str = "w1", *, once: bool = False) -> None:
    """Consume jobs de la cola hasta vaciarla (o una ronda si once=True)."""
    workdir = settings.data_dir / "staging"
    workdir.mkdir(parents=True, exist_ok=True)
    await db.reset_stale_jobs()  # jobs 'running' huérfanos → 'queued' (reanudable)
    while True:
        job = await db.claim_job(worker_id, list(STAGE_ORDER))
        if job is None:
            if once:
                return
            await asyncio.sleep(settings.job_poll_seconds)
            continue
        t0 = time.time()
        try:
            await run_stage(job["job_type"], job, workdir)
            await db.finish_job(job["job_id"], ok=True)
            await db.doc_status(job["doc_id"], "kos", STAGE_STATUS.get(job["job_type"], "ready"), "done")
            log.info("job %s/%s OK (%.1fs)", job["job_type"], job["doc_id"], time.time() - t0)
        except (FileNotFoundError, ValueError) as exc:  # noqa: BLE001
            log.warning("job %s/%s SALTA: %s", job["job_type"], job["doc_id"], exc)
            await db.finish(job["job_id"], ok=True, error=str(exc)[:200])
            await db.mark_job_skipped(job["job_id"])
        except Exception as exc:  # noqa: BLE001
            log.exception("job %s/%s FAILED", job["job_type"], job["doc_id"])
            await db.finish(job["job_id"], ok=False, error=str(exc)[:500])