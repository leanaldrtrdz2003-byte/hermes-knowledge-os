"""Tests de integración ligeros: S3 (MinIO) y query log (sin LLM)."""
import asyncio
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kos import db, s3  # noqa: E402

pytestmark = pytest.mark.integration


from conftest import _KOS_LOOP as _LOOP


def _run(coro):
    return _LOOP.run_until_complete(coro)


def test_s3_upload_roundtrip():
    sid = f"test-{uuid.uuid4().hex[:8]}"
    data = b"contenido de prueba\n" * 10
    key = s3.upload(sid, "test", 1, ".md", data)
    assert key == f"sources/test/{sid}/v1.md"
    assert s3.download(sid, "test", 1, ".md") == data
    # version 2: objeto nuevo, v1 intacto
    s3.upload(sid, "test", 2, ".md", b"v2\n" * 50)
    assert s3.download(sid, "test", 2, ".md") == b"v2\n" * 50
    assert s3.download(sid, "test", 1, ".md") == data  # inmutabilidad (§5)


def test_query_log_registra():
    async def _t():
        await db.apply_schema()
        await db.log_query("pregunta de prueba", "hybrid", 42, 123, "ollama", "qwen2.5:7b")
        pool = await db.get_pool()
        n = await pool.fetchval("SELECT COUNT(*) FROM queries_log")
        return n
    assert _run(_t()) >= 1