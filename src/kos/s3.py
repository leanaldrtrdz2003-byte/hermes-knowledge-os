"""Capa de objetos inmutable (MinIO/S3) — fuentes originales (§5).

Los assets se guardan como `sources/<kind>/<source_id>/v<version>.<ext>`.
Nunca se sobrescribe una versión: al alterarse el contenido se crea vN+1.
"""
from __future__ import annotations

import hashlib
import logging
from io import BytesIO
from pathlib import Path

from minio import Minio
from minio.error import S3Error

from kos.config import settings

log = logging.getLogger("kos.s3")


def client() -> Minio:
    ep = settings.s3_endpoint.strip()
    ep = ep.split("://")[-1].rstrip("/")  # el cliente minio no admite scheme ni ruta
    return Minio(
        ep,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        secure=settings.s3_secure,
    )


def ensure_bucket() -> None:
    c = client()
    if not c.bucket_exists(settings.s3_bucket):
        c.make_bucket(settings.s3_bucket)
        log.info("Bucket %s creado", settings.s3_bucket)
    for kind in ("books", "papers", "websites", "wikipedia", "documentation",
                 "videos", "transcripts", "datasets", "code", "archives"):
        c.make_bucket(f"{settings.s3_bucket}-{kind}") if not c.bucket_exists(f"{settings.s3_bucket}-{kind}") else None


def sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def upload(source_id: str, source_kind: str, version: int, suffix: str, data: bytes) -> str:
    """Sube bytes inmutables; retorna object_key."""
    key = f"sources/{source_kind}/{source_id}/v{version}{suffix}"
    c = client()
    c.put_object(
        settings.s3_bucket, key, BytesIO(data), length=len(data),
        part_size=10 * 1024 * 1024,
    )
    # sidecar del hash
    c.put_object(
        settings.s3_bucket, key + ".sha256",
        BytesIO(sha256_of_bytes(data).encode()), length=64,
    )
    log.info("objeto subido: %s (%d bytes)", key, len(data))
    return key


def download(source_id: str, source_kind: str, version: int, suffix: str) -> bytes:
    key = f"sources/{source_kind}/{source_id}/v{version}{suffix}"
    resp = client().get_object(settings.s3_bucket, key)
    try:
        return resp.read()
    finally:
        resp.close()
        resp.release_conn()


def object_exists(key: str) -> bool:
    try:
        client().stat_object(settings.s3_bucket, key)
        return True
    except S3Error:
        return False