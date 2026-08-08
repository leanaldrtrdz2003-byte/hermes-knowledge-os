# IMPLEMENTATION_COMPLETE — Knowledge OS

Fecha: 2026-08-08 · Estado: **COMPLETO** (F1–F11)

## Resumen del sistema

Knowledge OS (KOS) es un sistema de conocimiento externo de producción: ingesta
inmutable + control plane + índices + RAG híbrido + grafo de conocimiento +
wiki + interfaz Obsidian. Todo LLM generativo corre en **opencode-zen
(deepseek-v4-flash-free)** con **fallback opencode-go (deepseek-v4-flash)**;
los embeddings quedan **100 % locales (Ollama bge-m3)**.

## Arquitectura (capas)

| Capa | Tecnología | Almacena |
|---|---|---|
| Store inmutable | MinIO/S3 (kos-minio) | fuentes originales, verificadas por hash |
| Control plane | PostgreSQL + pgvector (kos-postgres) | jobs, docs, chunks, grafo, costes, status |
| Índices vectoriales | Qdrant (kos-qdrant) | 21 chunks embebidos (bge-m3) |
| Grafo | NetworkX + Graphify (export Obsidian) | 4 comunidades, entidades/relaciones en PG |
| RAG híbrido | LightRAG 1.5.6 (PG+Qdrant+NetworkX) + router propio | respuestas con `[Source] [Chunk]` |
| GUI humana | Obsidian vault (`vault/`) | wiki compilada, grafo, dashboard, benchmark |

## Pipeline (24/24 jobs)

```
ingest (hash dedupe) → parse → chunk → embed (bge-m3) → index (Qdrant)
   → graph (modelo remoto) → wiki (modelo remoto) → dashboard → backup
```

Todo orquestado por `ingestion_jobs` en PG; los workers consumen la cola y
registran `processing_costs` por llamada LLM (§31).

## Decisiones de implementación clave

- **LLM remoto en todo el proceso** (§22): graph, wiki, router y LightRAG
  usan `llm.complete()` o el wrapper `_zen_complete` → zen; solo los embeddings
  son locales (`embedding_base_url` separado de `llm_base_url`).
- **Fallback de proveedor replicado de Hermes Agent**: `config.yaml` define
  fallback_providers `opencode-go/deepseek-v4-flash`; el KOS usa las vars
  `LLM_FALLBACK_*` en `llm.py` y `lightrag_engine.py` (verificado E2E: fallo
  primario → go responde).
- **Cache LightRAG**: tabla `lightrag_llm_cache` evita re-LLM; las respuestas
  vacías cacheadas se purgan (`DELETE FROM lightrag_llm_cache`) para re-intentos.
- **PK de ingesta** `ingestion_status(doc_id)` con ON CONFLICT DO UPDATE — los
  workers no abortan por re-ingesta.
- **Inmutabilidad**: hash SHA-256 por documento; re-ingest de lo mismo = skip.

## Escalado (F11)

- **Más workers**: la cola es PostgreSQL — `N` procesos `worker --worker-id wX`
  consumen en paralelo (probado con 12+ workers en fases previas).
- **Embeddings**: bge-m3 local es el cuello si el corpus crece → mover a un
  servicio remoto cambiando `EMBEDDING_BASE_URL` (API compatible /api/embed).
- **Automatización**: `scripts/autopilot.sh` (ingesta + worker + wiki/graph +
  backup) — un cron diario mantiene el KOS al día sin intervención.
- **Índices**: pgvector y Qdrant se sobreviven sin tuning hasta ~100k chunks;
  el runner de benchmarks (`vault/00_SYSTEM/BENCHMARK.md`) guía cuándo escalar.
- **3 contenedores** (minio/postgres/qdrant) corren vía docker compose con
  healthchecks; `docker compose config --quiet` valida la interpolación.

## Estado de fases

| Fase | Estado |
|---|---|
| F1 store inmutable (MinIO) | ✅ |
| F2 control plane (PG+pgvector) | ✅ |
| F3 pipeline completo | ✅ |
| F4 graph (Graphify→Obsidian export) | ✅ |
| F5 LightRAG híbrido | ✅ |
| F6 workers/pipeline 24/24 | ✅ |
| F7 query router con citas | ✅ |
| F8 wiki + dashboard | ✅ |
| F9 backup/restore | ✅ |
| F10 benchmark 3 estrategias | ✅ |
| F11 scaling + docs | ✅ (este documento) |

## Derivados en disco

- `vault/` — wiki compilada, dashboard, gráfico Obsidian, benchmark
- `scripts/autopilot.sh` — automatización E2E del ciclo
- `.env` — credenciales reales (MinIO/PG/Qdrant/LLM) — **no versionar**