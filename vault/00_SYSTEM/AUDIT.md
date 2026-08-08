# AUDIT — Hermes Knowledge OS (Fase 1)

> Auditoría técnica del entorno y de los componentes candidatos realizada el **2026-08-08** antes de implementar.
> Regla de misión §65: inspeccionar antes de instalar. Fuentes primarias: repositorios oficiales + docs actuales + inspección real de paquetes instalados.

---

## 1. Entorno de ejecución

| Ítem | Valor | Notas |
|---|---|---|
| SO | CachyOS (Arch Linux), kernel `7.1.5-2-cachyos` | rolling release |
| CPU | 16 cores | |
| RAM | 16 GiB (≈14.6 GiB usable) | margen justo para modelos locales 7B + servicios |
| Disco | ~198 GiB libres | suficiente para corpus de decenas de GB |
| GPU | NVIDIA presente, **driver no disponible** | `nvidia-smi` sin driver → TODO cómputo en **CPU** |
| Python sistema | 3.14.6 | `/usr/bin/python3` |
| Python Hermes | 3.11 (venv propio de Hermes) | |
| Python proyecto | **3.12** (venv `uv`) | compatibilidad real verificada con Graphify ≥3.10 y LightRAG ≥3.10 |
| `uv` | 0.11.31 | gestor de entornos del proyecto |
| Docker | instalado + **servicio arrancado** (`systemctl`) | compose plugin OK |
| Git | 2.x | repo inicializado |
| Internet | OK (PyPI, GitHub, Ollama registry) | |
| Ollama | 0.32.6 (systemd, `127.0.0.1:11434`) | modelo preexistente `gemma3:1b` |

**Hallazgo operativo**: el entorno hereda `PYTHONPATH` del venv de Hermes que contamina las importaciones del venv del proyecto → todos los comandos python del proyecto usan `env -u PYTHONPATH .venv/bin/python`.

**Servicios que quedan en puertos** (tras `docker compose up -d`):
`5432` PostgreSQL pgvector · `6333/6334` Qdrant · `9000/9001` MinIO.

## 2. Auditoría de componentes (estado real a 2026-08-07)

### 2.1 Graphify — v8 (paquete PyPI `graphifyy`)
- **Repo**: `github.com/Graphify-Labs/graphify` (104k★) · rama `v8` · 1.354 commits · versión actual **0.9.36** (bump skill Windows, 2026-08-07).
- **Licencias**: Apache-2.0 + MIT (doble licencia; se mantiene `LICENSE` y `LICENSE-MIT`). Compatible uso comercial.
- **Instalación oficial**: `uv tool install graphifyy` (instalado → `~/.local/bin/graphify` + `graphify-mcp`). Requiere Python ≥3.10.
- **Integración Hermes**: existe `graphify install --platform hermes` — **ejecutado y verificado**; skill instalada en `~/.hermes/skills/graphify/SKILL.md` y `references/` (Hermes la detecta; cargada y validada).
- **Arquitectura** (ARCHITECTURE.md oficial): pipeline `detect → extract → build_graph → cluster (Leiden) → analyze → report → export`; sin estado compartido; salidas en `graphify-out/`.
- **Cómo funciona** (how-it-works.md oficial): 3 pases — (1) código por AST/tree-sitter **local y gratis** (25 lenguajes + SQL determinista), (2) vídeo/audio con faster-whisper **local**, (3) docs/papers/imágenes **subagentes Claude** (coste tokens, exige API Anthropic/Gemini).
- **Valores clave**: confianza `EXTRACTED | INFERRED | AMBIGUOUS` + `confidence_score` discreto (0.55–0.95); procedencia por `source_file`/`source_location`; caché SHA256 (re-runs saltan inaltered); grafo en `graph.json` (node-link de NetworkX); export a **Obsidian vault**, `graph.html`, `graph.svg`, **wiki Markdown**; servidor **MCP** stdio; `graphify query|path|explain|update`; reducción de tokens 71.5× en corpus mixto.
- **Decisión de arquitectura**: Graphify = **knowledge graph estructural**. Para pase 3 (semántico) **no** se depende de subagentes Claude/Gemini: nuestro pipeline genera fragmentos de extracción con la misma estructura `{nodes, edges}` (schema validado por `validate_extraction`) usando el **router LLM propio** (Ollama local / OpenAI-compatible), y se fusionan vía `build_graph()` de la librería. → garantiza independencia de proveedor y cero coste.

### 2.2 LightRAG — paquete `lightrag-hku`
- **Repo**: `github.com/HKUDS/LightRAG` · rama `main` · 9.438 commits — merges del 05–06 ago 2026 · **EMNLP2025** · paper arXiv `2410.05779v3`.
- **Licencia**: MIT. Compatible uso comercial.
- **Versión instalada**: **1.5.6** (PyPI). Requiere Python ≥3.10.
- **Storage real** (inspeccionado en `lightrag/kg/`, NO unicamente según docs): hay implementaciones `postgres_impl.py` (KV+DocStatus+Vector vía `asyncpg` + `pgvector`), `qdrant_impl.py`, `networkx_impl.py`, `neo4j_impl.py`, `mongo_impl.py`, `milvus_impl.py`, `faiss_impl.py`, `redis_impl.py`, `opensearch_impl.py`, `pgtable_impl.py` (grafo Apache AGE), `nano_vector_db_impl.py`, `json_*_impl.py`.
- **Extras PyPI**: `offline-storage` (asyncpg, pgvector, qdrant-client, faiss-cpu, redis, neo4j, pymilvus, pymongo, opensearch-py); `offline-llm` (voyageai) — **aquí NO** se instalan extras masivos; se instalaron solo conductores: `qdrant-client==1.19.0`, `asyncpg`, `pgvector`, `openai`, `ollama`.
- **LLM funcional (verificado por import)**: `lightrag.llm.ollama: ollama_model_complete, ollama_embed`, `lightrag.llm.openai: openai_complete_if_cache`.
- **Observabilidad**: cache LLM, doc status, pipeline con dedup y concurrencia (docs oficiales "FileProcessingPipeline", cap. 7 y 8) — reaprovechable.
- **Decisiones de backends** (§7, §47):
  - Vectores → **QdrantVectorDBStorage** contra el servidor Qdrant dedicado (elegido tras análisis: v1.19.0, payload-filtering, multi-tenancy, apunta colección por tenant/dominio en payload).
  - KV + DocStatus → **PostgreSQL** (lightrag `postgres_impl` con `asyncpg`+`pgvector`), cumpliendo "PostgreSQL backend unificado".
  - Grafo interno LLM-based → **NetworkXStorage** JSON en disco derivado (el grafo *concepto* de producción es Graphify); camino a `PGTableGraphStorage` (AGE) documentado en SCALING.
  - Nada de Neo4j/Redis/Kafka en esta fase (§62: sin carga que lo justifique).

### 2.3 Qdrant
- Repo `github.com/qdrant/qdrant` · versión **1.19.0** (bump 2026-08-04) · **Apache-2.0** · Rust.
- Servidor healthy en `:6333`. Colección única inicial → **particionado por tenant/dominio/idioma vía payload** (no colecciones gigantes sin estrategia — §7).

### 2.4 PostgreSQL (pgvector)
- `github.com/postgres/postgres` master (2026-08-07) · **PostgreSQL License** (permisiva).
- Imagen `pgvector/pgvector:pg17` (pgvector + AGE disponible si se quisiera). Genera el metadatan/control plane del KOS.

### 2.5 MinIO
- ⚠️ **Hallazgo**: el repo GitHub `minio/minio` está **country](archivado el 2026-04-25 — read-only**, "source only releases"). El proyecto sigue vivo (web `min.io`, docs, imagen Docker y clientes `mc`; solo cambió la política de release: fuente-only en GitHub).
- Licencia **AGPL-3.0** (repo) — **NOTA LEGAL**: AGPL afecta a re-distribución/servicio de software derivado; para uso interno en el KOS no es problema, pero se registra como decisión (ADR-005) y alternativa (SeaweedFS/S3 provider) documentada para una salida posterior si fuese necesario.
- Servidor Docker healthy en `:9000` + consola `:9001`.

### 2.6 Obsidian
- **No instalado** como app en este entorno (interfaz humana desktop). El **vault es una carpeta de Markdown** — la generamos, poblamos y dejamos lista; el usuario la abre con Obsidian en su máquina. Sin backend de verdad: nunca es fuente de verdad (§4).
- Plugins recomendados en docs (Dataview/Templater/Graph view) — NO se automatizan (no se requiere; el vault funciona sin ellos).

### 2.7 Embeddings / modelos (decisión inicial → ADR-007)
- **bge-m3** (BAAI, MIT, 1024 dim, multilingüe ++, razonamiento científico/código) → elegido para embeddings.
- **qwen2.5:7b** (Apache-2.0) → LLM local por defecto para extracción/compilación (coste 0, CPU). Intercambiable por OPENAI-compatible barato vía env (§22).
- Ejecución: **Ollama 0.32.6** (API local: `/api/embed`, `/api/chat`). Licencias Apache-2.0 (qwen2.5) y MIT (bge-m3) — compatibles.

### 2.8 Dependencias/otros
- `jq`, `ffmpeg`, `git` disponibles. `tree-sitter` vía Graphify. `psql` cliente no requerido (drivers asyncpg).
- Puertos libres verificados antes de lanzar containers.
- Elasticsearch/OpenSearch: opción redundante descartada (sin necesidad en MVP).

## 3. Decisiones de arquitectura adoptadas (resumen)

| # | Decisión | Justificación |
|---|---|---|
| A1 | LightRAG = motor RAG-orchestration (Qdrant vectores + PG KV/docstatus) | §3, análisis actual ver §5 |
| A2 | Graphify = grafo estructural + paths + provenance; **nunca RAG** | §2 |
| A3 | PostgreSQL = source of truth de metadatos/control | §6 |
| A4 | MinIO = capa de objetos inmutable (fuentes originales) | §5 —decidido pese a "repositorio archivado" |
| A5 | Qdrant = vector storage | §7, versión 1.19.0 verificada |
| A6 | Obsidian = vista humana (nunca la BD) | §4 |
| A7 | LLM local (Ollama) por defecto; multi-proveedor (openai-compatible) | §22/§23 |
| A8 | Embeddings bge-m3 | §23 multilingüe/español |
| A9 | Jobs en PostgreSQL (tabla de colas) para MVP; interfaz migrable a Redis/Celery/NATS | §20/§21 |
| A10 | Sin Redis/Kafka/Neo4j/Prometheus/Grafana en MVP | §35/§62 |

## 4. Brechas y riesgos detectados (para OPERATIONS/TROUBLESHOOTING)

1. **Sin GPU driver** → inferencia de LLM en CPU: ingesta de 7B lenta (ver BENCHMARK); estrategia: pipelines de embeddings/ingesta sin LLM por defecto; extracción LLM en lotes pequeños/reanudable.
2. **Pulls de modelos** dependientes del repositorio de Ollama (red). Marcado de fallback: `LLM_PROVIDER=openai` con endpoint propio.
3. **`graphify install`** detectó Hermes; revisar periódicamente updates.
4. **PYTHONPATH heredado** — patrón `env -u PYTHONPATH` documentado.
5. **MinIO repo archivado** — seguimiento vía docker images/min.io releases; drive alternativo documentado.
6. Postgres puerto 5432 puede chocar con otros servicios locales — documentado en TROUBLESHOOTING.

## 5. Pruebas realizadas en esta fase

- `graphify install --platform hermes` → skill detectada en `~/.hermes/skills/graphify` ✓
- Import de backends LightRAG (qdrant/postgres/networkx) ✓
- `docker compose up -d` → 3 servicios **healthy** ✓
- Ollama daemon vía systemd ✓ (reparado `/var/lib/ollama` ownership)
- Conexión a internet, git commit OK.

---

*Continúa en `ARCHITECTURE.md`. Versión: 1.0 · Fecha: 2026-08-07.*