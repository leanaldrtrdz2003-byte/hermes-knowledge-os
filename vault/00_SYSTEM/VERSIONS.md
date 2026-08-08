# VERSIONS — Versiones de componentes (§16/§54)

> Registro de versiones activas. `kos versions` lee la tabla `pipeline_versions`.
> Toda actualización estructural se anota aquí y en CHANGELOG.md.

## Stack activo (2026-08-08)

| Componente         | Nombre           | Versión        | Notas                          |
|--------------------|------------------|----------------|--------------------------------|
| OS                 | CachyOS (Linux)  | 7.1.5-2        | x86_64, 16 cores, 14 GB RAM    |
| Python (venv)      | CPython          | 3.12.13        | uv-managed                     |
| LLM local          | Ollama           | 0.32.6         | daemon systemd, 127.0.0.1:11434 |
| LLM modelo         | qwen2.5          | 7b             | 4.7 GB                         |
| Embeddings         | bge-m3           | latest         | 1024 dims, 1.2 GB              |
| RAG                | lightrag-hku     | 1.5.6          | PG KV/DocStatus + Qdrant + NetworkX |
| Grafo estructural  | graphifyy        | 0.9.36         | tree-sitter 25 lenguajes       |
| PostgreSQL         | pgvector/pg17     | compose        | control plane + vectores de LightRAG |
| Qdrant             | qdrant/qdrant    | 1.19.0         | colección kos_chunks           |
| MinIO              | minio            | latest         | bucket kos-sources             |
| Python S3 client   | minio (PyPI)      | —              | —                              |
| Driver async       | asyncpg          | —              | —                              |
| Parser PDF         | pypdf            | pendiente      | instalar si ingiere PDF        |

## Commit/LightRAG
- LightRAG: instalado vía PyPI `lightrag-hku==1.5.6` (sin checkout git dedicado;
  si se requiere pin a commit exacto, ver `docs/decisions/ADR-001`).

## Reglas de actualización
1. `kos versions` antes y después de tocar componentes.
2. Registrar en `pipeline_versions` vía `db.record_version`.
3. Cambios de embedding → colección nueva (§16), nunca borrado in-place.
4. Cambios de schema → migración idempotente en `apply_schema()`.