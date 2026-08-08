# ADR-003 — PostgreSQL como control plane único
**Estado**: aceptado · **Fecha**: 2026-08-08

Fuente de verdad de metadatos: documentos, fuentes, chunks, entidades,
relaciones, claims, memoria, jobs, costes, errores, versiones (§6/§47).
Con pgvector disponible como reserva; los embeddings principales viven en Qdrant.

# ADR-004 — Qdrant como índice vectorial
**Estado**: aceptado · **Fecha**: 2026-08-08

Colecciones: `kos_chunks` (payload: doc_id, chunk_id, source_id, language,
domain, tenant, knowledge_type) para filtrado multi-tenant (§7). LightRAG usa su
propia colección con workspace por defecto. Apache-2.0, alto rendimiento Rust.

# ADR-005 — MinIO como capa de objetos inmutable
**Estado**: aceptado · **Fecha**: 2026-08-08

`sources/<kind>/<source_id>/v<N>.<ext>` — las versiones nunca se sobrescriben
(§5). AGPLv3 (self-hosted OK para uso interno).