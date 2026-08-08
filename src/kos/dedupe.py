"""Deduplicación (§18).

Clasifica: duplicate | near_duplicate | new_version | translation | mirror | independent.
Estrategias: SHA256 de contenido canónico, URL canónica, fingerprint (estructura),
similitud coseno (embeddings) sobre candidatos.
"""
from __future__ import annotations

import hashlib
import logging
import re

log = logging.getLogger("kos.dedupe")

_NORM_SPACE = re.compile(r"\s+")


def canonicalize_text(text: str) -> str:
    """Normalización para fingerprint: minúsculas, espacios plegados, sin puntuación de ruido."""
    t = _SPACE.sub(" ", text.lower())
    t = re.sub(r"[^a-z0-9áéíóúñü ]+", " ", t)
    return _SPACE.sub(" ", t).strip()


def content_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_url(url: str) -> str:
    """Normaliza URL: sin fragmento, scheme lowercase, quita trailing slash (excepto raíz)."""
    from urllib.parse import urlparse, urlunparse
    u = urlparse(url.strip())
    u = u._replace(fragment="", scheme=(u.scheme or "http").lower(),
                   netloc=u.netloc.lower().replace("www.", ""))
    path = u.path.rstrip("/") if u.path != "/" else "/"
    return urlunparse(u._replace(path=path))


def structural_fingerprint(text: str, n: int = 12) -> str:
    """Fingerprint por n-gramas posicionales de palabras (near-duplicates)."""
    words = canonicalize_text(text).split()
    if len(words) < n:
        return "|".join(words)
    return "|".join(words[:n]) + "::" + "|".join(words[-n:])


def classify(*, sha: str | None, url: str | None, fingerprint: str | None,
             existing: dict | None) -> str:
    """existing: {'sha256', 'canonical_url', 'fingerprint'} del registro previo."""
    if existing is None:
        return "independent"
    if sha and existing.get("sha256") == sha:
        return "duplicate"
    if sha and existing.get("sha256"):
        return "new_version"
    if url and existing.get("canonical_url") == url:
        return "mirror"
    if fingerprint and existing.get("fingerprint") == fingerprint:
        return "near_duplicate"
    return "independent"