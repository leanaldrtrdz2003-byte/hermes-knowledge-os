"""Chunking estructurado (§17): respeta encabezados Markdown, conserva metadata
de sección y emite (chunk_id, idx, heading, text). Determinista y reanudable.
"""
from __future__ import annotations

import re
import uuid

from kos.config import settings

_HEADING = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def split_text(text: str, *, size: int | None = None, overlap: int | None = None) -> list[dict]:
    """texto → lista de {idx, heading, body}."""
    size = size or settings.chunk_size
    overlap = overlap or settings.chunk_overlap
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []

    # secciones por encabezado (para mantener contexto semántico)
    matches = list(_HEADING.finditer(text))
    sections: list[tuple[str, str]] = []
    if not matches:
        sections = [("", text)]
    else:
        for i, m in enumerate(matches):
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            sections.append((m.group(2).strip(), text[start:end].strip()))

    chunks: list[dict] = []
    for heading, body in sections:
        if not body:
            continue
        # subdivide por tamaño en tokens aproximado (chars/4)
        words = body.split()
        step = max(1, size - overlap)
        for i in range(0, len(words), step):
            piece = " ".join(words[i:i + size])
            if piece:
                chunks.append({"heading": heading, "body": piece})
    return chunks


def make_chunks(doc_id: str, text: str) -> list[dict]:
    """chunks con ids estables para PG y Qdrant."""
    out = []
    for idx, c in enumerate(split_text(text)):
        out.append({
            "chunk_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{doc_id}:{idx}")),
            "doc_id": doc_id,
            "idx": idx,
            "heading": c["heading"],
            "body": c["body"],
            "token_count": max(1, len(c["body"].split())),
        })
    return out