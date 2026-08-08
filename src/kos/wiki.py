"""Compilador de conocimiento (§13) — wiki incremental con lineage (§48).

Cada página wiki es una síntesis LLM sobre evidencia concreta (chunks).
Incremental: si el hash de las fuentes no cambió, no se recompila (§9).
Nunca se borran las fuentes originales; la página las cita por id.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from datetime import datetime, timezone

from kos.config import settings
from kos.llm import complete

log = logging.getLogger("kos.wiki")

TEMPLATE_SECTIONS = [
    "summary", "definitions", "key_concepts", "relationships",
    "prerequisites", "applications", "contradictions", "open_questions",
    "sources", "confidence",
]


def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9áéíóúñü ]+", "", title.lower()).strip()
    return re.sub(r"\s+", "-", s)[:80] or "untitled"


def sources_fingerprint(chunk_ids: list[str]) -> str:
    key = "|".join(sorted(chunk_ids))
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def page_path(title: str) -> Path:
    return settings.vault_path / "02_WIKI" / "generated" / f"{_slug(title)}.md"


def is_fresh(title: str, chunk_ids: list[str]) -> bool:
    """Incremental: página existente con las mismas fuentes → no recompilar."""
    fp = sources_fingerprint(chunk_ids)
    p = page_path(title)
    if not p.exists():
        return False
    head = p.read_text(encoding="utf-8")[:400]
    return f"fingerprint: {fp}" in head


async def compile_page(title: str, evidence: list[dict], *, language: str = "es") -> Path | None:
    """evidence: [{chunk_id, doc_id, text, page?}]. Devuelve ruta o None si fresh."""
    chunk_ids = [e["chunk_id"] for e in evidence]
    if is_fresh(title, chunk_ids):
        log.info("wiki fresca (fuentes sin cambios): %s", title)
        return None

    fp = sources_fingerprint(chunk_ids)
    body = "\n\n".join(
        f"[chunk {e['chunk_id']} | doc {e['doc_id']}]\n{e['text'][:1500]}" for e in evidence[:12]
    )
    prompt = f"""Compila una página de wiki de conocimiento a partir de la EVIDENCIA siguiente.
Idioma: {language}. Estructura con encabezados: Resumen, Definiciones, Conceptos clave,
Relaciones, Prerrequisitos, Aplicaciones, Contradicciones, Preguntas abiertas, Fuentes, Confianza.
Cada afirmación debe poder rastrearse a un chunk [chunk_id]. Distingue hechos de inferencias.
Si hay contradicciones, repórtalas en su sección (no las reconcilies).
No inventes información fuera de la evidencia. Título: {title}

EVIDENCIA:
{body}"""
    out = await complete(prompt, system=None, max_tokens=3000)

    p = page_path(title)
    p.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = (
        "---\n"
        f"title: {title}\n"
        f"type: wiki-generated\n"
        f"fingerprint: {fp}\n"
        f"knowledge_version: 1\n"
        f"last_verified: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n"
        f"language: {language}\n"
        f"source_chunks: {len(chunk_ids)}\n"
        "---\n\n"
    )
    p.write_text(frontmatter + out + "\n", encoding="utf-8")
    log.info("wiki compilada: %s (%d chunks)", title, len(chunk_ids))
    return p


def index_wiki() -> Path:
    """Índice de páginas generadas (para 02_WIKI/indexes)."""
    pages = sorted(settings.vault_path.glob("02_WIKI/generated/*.md"))
    lines = ["# Índice de Wiki Generada", "", f"Páginas: {len(pages)}", ""]
    for p in pages:
        lines.append(f"- [[{p.stem}]]")
    idx = settings.vault_path / "02_WIKI" / "indexes" / "generated.md"
    idx.parent.mkdir(parents=True, exist_ok=True)
    idx.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return idx