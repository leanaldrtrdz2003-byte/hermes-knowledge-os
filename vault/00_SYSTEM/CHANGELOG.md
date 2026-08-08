# CHANGELOG — Hermes Knowledge OS

> Registro de cambios estructurales (§54). El estado de cada fase está en
> `ROADMAP.md`; este documento registra el *historial* de lo construido.

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
  OPERATIONS, SECURITY, COST_MODEL, MODEL_SELECTION, VERSIONS, ROADMAP.
- **Tests**: suite pytest (14 tests) verde.
- **Corpus de prueba**: 4 docs multi-dominio (física, informática, matemáticas, programación) —
  **eliminados el 2026-08-08** para dejar el sistema en limpio (ver "Limpieza").

### LLM y embeddings (evolución)
- **V1**: LLM local qwen2.5:7b en CPU (2-5 min/doc — lento pero sin coste).
- **V2 (final)**: LLM generativo remoto barato `deepseek-v4-flash-free` vía
  endpoint OpenAI-compatible (opencode.ai zen/v1) con **fallback**
  `deepseek-v4-flash` (zen/go/v1); **embeddings 100% locales** con Ollama bge-m3
  (URL separada por diseño, nunca hereda la del LLM).

### Verificado (smoke end-to-end)
- **LightRAG 1.5.6** inicializa con PG KV/DocStatus + Qdrant + NetworkX;
  inserta un documento, extrae entidades/relaciones y responde con referencias.
- **MinIO**: bucket + objeto versionado subido; Qdrant colección creada.
- **Fallback LLM**: probado en vivo forzando un 401 → responde el modelo de respaldo.
- **Automatización**: `scripts/autopilot.sh` probado E2E (ingesta → worker →
  wiki/grafo/dashboard → backup, EXIT=0); timer systemd `kos-autopilot.timer`
  habilitado a las 03:30 con dedupe por hash SHA-256 (solo novedades).

### Conocido / limitaciones
- Extracción de entidades con LLM remoto: ~20 s/doc (vs 2-5 min local).
- Qdrant sin auth (local); documentado para exponerlo.
- La extracción de grafos depende del LLM: si devuelve JSON inválido se debe
  reintentar (validación añadida en Fase A2).

### 2026-08-08 — Limpieza del corpus de prueba
- **Eliminados** los 4 documentos de ejemplo y **todo lo generado con ellos**:
  filas de PG (sources, documents, chunks, entities, relations, hashes, jobs,
  queries_log, costes, caches LightRAG), colecciones Qdrant, artefactos del
  vault (wiki generada, exports del grafo, dashboard, benchmark, memoria
  semántica), staging, backups y caches. El sistema queda **en limpio**,
  esperando el corpus real del usuario.

## 2026-08-08 — Fases de mejora A/B/C

- **A1 — Docs al día**: ROADMAP/CHANGELOG reflejan el estado real (F11 + plan);
  artefactos duplicados del grafo eliminados en la limpieza.
- **A2 — Extracción robusta**: `graph.py` con retry (`MAX_LLM_RETRIES=2`) y
  validación estricta de JSON (retries; edges huérfanos e ids vacíos
  descartados).
- **A3 — CI**: `.github/workflows/ci.yml` (pytest sin infra + `bash -n` +
  `systemd-analyze verify`); `pytest.ini` con marker `integration`.
- **B1 — Escala**: `ingest --limit N` (backpressure) y `worker --concurrency N
  --rate-limit S` (paralelismo con semáforo + pausa opcional).
- **B2 — Eficiencia**: autopilot con regeneración selectiva: wiki/grafo/
  dashboard solo si hubo documentos nuevos.
- **B3 — Dominios**: grafo anotado con `domain` por nodo (carpeta de `data/raw`)
  + `domains.json` de resumen.
- **C1 — API HTTP**: `src/kos/server.py` (stdlib) — `GET /health`, `GET /stats`,
  `POST /query {"question","mode","session_id"}`; los agentes consultan sin CLI.
- **C2 — Sesión + salud**: memoria conversacional por `session_id` (últimos 6
  turnos inyectados al prompt) y `scripts/watchdog.sh` + timer systemd 07:45
  (alerta si el autopilot falla o el corpus vacío).
