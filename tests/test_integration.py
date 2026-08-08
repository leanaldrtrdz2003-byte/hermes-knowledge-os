"""Tests de integración (requieren infra UP: PG + Qdrant + Ollama)."""
import asyncio
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kos import db, qdrant, wiki  # noqa: E402
from kos.embed import embed_texts  # noqa: E402

pytestmark = pytest.mark.integration


from conftest import _KOS_LOOP as _LOOP


def _run(coro):
    """Reusa UN loop para toda la suite (el pool asyncpg queda atado al loop
    donde se crea)."""
    return _LOOP.run_until_complete(coro)


def test_schema_idempotente():
    async def _t():
        await db.apply_schema()
        await db.apply_schema()
        return True

    assert _run(_t())


def test_dedupe_upsert_por_hash():
    async def _t():
        h = uuid.uuid4().hex
        r1 = await db.upsert_source_and_doc(title="t-unico", content_hash=h,
                                            mime_type="text/markdown", source_type="documentation")
        r2 = await db.upsert_source_and_doc(title="t-unico", content_hash=h,
                                            mime_type="text/markdown", source_type="documentation")
        return r1, r2

    r1, r2 = _run(_t())
    assert r1["is_new"] is True
    assert r2["is_new"] is False
    assert str(r1["doc_id"]) == str(r2["doc_id"])


def test_qdrant_roundtrip():
    async def _t():
        qdrant.ensure_collection()
        vecs = await embed_texts(["el transformador usa atención",
                                  "la entropía siempre crece en sistemas aislados"])
        payload_base = {"tenant": "test"}
        uuids = [str(uuid.uuid4()), str(uuid.uuid4())]
        chunk_rows = [
            {"chunk_id": uuids[i], "idx": i, "heading": "", "body": t}
            for i, t in enumerate(["el transformador usa atención",
                                   "la entropía siempre crece en sistemas aislados"])
        ]
        qdrant.upsert_chunks(chunk_rows, vecs, payload_base)
        hits = qdrant.search(vecs[0], top_k=2)
        return bool(hits)

    assert _run(_t())


def test_memoria_dedupe_key():
    async def _t():
        dk = f"dk-{uuid.uuid4().hex[:8]}"
        r1 = await db.persist_memory(kind="semantic", text="hecho de prueba",
                                     importance=0.9, dedupe_key=dk)
        r2 = await db.persist_memory(kind="semantic", text="hecho de prueba",
                                     importance=0.9, dedupe_key=dk)
        return r1, r2

    r1, r2 = _run(_t())
    assert r1 is not None
    assert r2 is None  # misma dedupe_key → duplicado


def test_wiki_fresca_incremental(tmp_path, monkeypatch):
    monkeypatch.setattr(wiki, "page_path", lambda title: tmp_path / "page.md")
    p = wiki.page_path("x")
    fp = wiki.sources_fingerprint(["c1", "c2"])
    assert wiki.is_fresh("x", ["c1", "c2"]) is False  # no existe
    p.write_text(f"---\nfingerprint: {fp}\n---\n")
    assert wiki.is_fresh("x", ["c2", "c1"]) is True   # mismo set de fuentes → fresh
    assert wiki.is_fresh("x", ["c1"]) is False         # fuentes distintas → recompilar