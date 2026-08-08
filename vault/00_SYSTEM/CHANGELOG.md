# CHANGELOG — Hermes Knowledge OS

> Registro de cambios estructurales (§54).

## 2026-08-08 — Fundación y pipeline v0.1

### Añadido
- **Infraestructura**: docker-compose (PostgreSQL+pgvector, Qdrant 1.19.0, MinIO) healthy; red `kos-net`.
- **Ollama 0.32.6**: instalación determinista (`/usr/local/bin/ollama`), daemon systemd,
  modelos `qwen2.5:7b` + `bge-m3` (fix `/var/lib/ollama`).
- **Código `src/kos/`**: config, db (schema+job queue), s3 (MinIO inmutable),
  qdrant, llm (router de proveedores), embed, chunk, dedupe, graph (Graphify),
  wiki (compilador incremental), memory (pipeline agente), security (fence
  anti-inyección), lightrag_engine (PG+Qdrant+NetworkX+Ollama), pipeline (6 etapas),
  router (A–H + citas), cli.
- **CLI/Makefile**: setup / ingest / worker / query / memory / wiki / graph /
  versions / dashboard / backup / restore.
- **Docs del sistema** (vault/00_SYSTEM/): AUDIT, ARCHITECTURE, DATA_MODEL,
  OPERATIONS, SECURITY, COST_MODEL, MODEL_SELECTION, VERSIONS, DASHBOARD, ROADMAP.
- **Tests**: 7 unitarios verdes; integración escrita (PG+Qdrant+memoria+wiki).
- **Corpus de prueba**: 4 docs multi-dominio (física, informática, matemáticas, programación).

### Verificado (smoke end-to-end)
- **LightRAG 1.5.6** inicializa con PG KV/DocStatus + Qdrant + NetworkX + Ollama;
  inserta un documento, extrae entidades/relaciones y responde con referencias.
- **MinIO**: bucket + objeto versionado subido; Qdrant colección creada.

### Conocido / limitaciones
- LightRAG en CPU: ~2-5 min/doc (primera generación qwen2.5:7b).
- `lightrag.llm.ollama` (módulo) no importa; se usa la vía verificada (funciones
  `ollama_model_complete`/`ollama_embed` — funcionan).
- Qdrant sin auth (local); documentado para exponerlo.

### 2026-08-08 Fase de pipeline en curso
- Worker corriendo sobre el corpus (6 etapas por doc).