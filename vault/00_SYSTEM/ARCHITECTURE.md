# ARCHITECTURE — Hermes Knowledge OS (Fase 2)

> Diseño de referencia del sistema. La implementación concreta vive en `src/` y se alinea con este documento.
> Principios rectorados: §1 (multicapa, responsabilidad única), §47 (source of truth vs índices derivados), §62 (sin sobreingeniería).

---

## 1. Principio fundamental

**Hermes Knowledge OS ≠ carpeta de documentos, ≠ vector DB, ≠ knowledge graph, ≠ Obsidian.**
Es una **arquitectura multicapa** donde cada componente tiene responsabilidad única y los índices se derivan de una fuente de verdad:

```
                HERMES (agente)
                    │
            QUERY / MEMORY ROUTER   (src/routing)
                    │
      ┌─────────────┼──────────────────┐
      ▼             ▼                  ▼
  LIGHTRAG     GRAPHIFY (lib)       WIKI COMPILER
 (retrieval)   (grafo estructural)  (conocimiento compilado)
      │             │                  │
      ▼             ▼                  ▼
  Hybrid Retrieval  Paths/Explain   Markdown Wiki
      │             │                  │
      └─────────────┼──────────────────┘
                    ▼
           SOURCE EVIDENCE (MinIO + PG)
                    ▼
              HERMES LLM → ANSWER con CITAS
```

## 2. Capas físicas (fuente de verdad → índices)

| Capa | Componente | Rol | ¿Source of truth? |
|---|---|---|---|
| Objetos (fuentes inmutables) | **MinIO** (S3) | bytes originales: books/papers/webs/videos/… | ✅ |
| Control/metadatos | **PostgreSQL 17 (pgvector)** | documents, versions, chunks, jobs, hashes, provenance, costos | ✅ |
| Vectores | **Qdrant 1.19** | embeddings chunks/entidades — índice derivado | ❌ derivado |
| Grafo estructural | **Graphify** (lib + salida `graph.json`) | nodos/relaciones EXTRACTED/INFERRED + paths | ❌ derivado |
| Grafo RAG interno | LightRAG NetworkXStorage (JSON) | KG entidades de LLM del propio LightRAG | ❌ cache/derivado |
| Retrieval orchestration | **LightRAG 1.5.6** | hybrid (vector+KV+LLM) retrieval, doc status, cachés | — |
| Conocimiento compilado | **Wiki (Markdown)** | síntesis LLM con lineage → fuente | ❌ derivado |
| Interfaz humana | **Obsidian vault** | vista navegable, dashboards, notas humanas | ❌ vista |
| Memoria del agente | **PG + textos en vault** | 4 tipos, scoring, dedup (src/memory) | ✅ agente |

**Nunca** se mantiene el mismo contenido completo duplicado: MinIO conserva el original; PG guarda *referencias + metadatos + hashes*; Qdrant guarda *vectores + payload* (no texto) con lineage a `chunk_id → doc_id → source_id`; Graphify guarda *solo grafo*; Wiki guarda *síntesis* con citas a chunk IDs; Obsidian presenta enlaces.

## 3. Flujo de ingesta (§17, §21)

```
SOURCE(fs/S3) → DETECT → PARSE (PDF/MD/HTML/code/transcript) → NORMALIZE
  → DEDUP (SHA256+canonical URL+fingerprint; clasifica duplicate|near_duplicate|new_version|translation|mirror)
  → CHUNK (estructurado por encabezados, tokens; metadata)
  → METADATA (idioma/dominio/autor/licencia → PG)
  → EMBED (bge-m3 vía Ollama/API; X-y PGBatch in PG ledger)
  → GRAPH (Graphify AST para código local; extractor LLM propio para docs; merge a graph.json)
  → KNOWLEDGE COMPILE (wiki por unidades de conocimiento; diff escucha para no recompilar lo que no cambió)
  → INDEX (Qdrant upsert + grafos + cachés LightRAG)
  → VALIDATE (conteo, hashes, prueba de recuperación) → READY (docstatus)
```

Cada etapa: **reanudable, idempotente, observable (log structured + PG), cacheable, incrementa, versionada** (§17). Si una etapa falla, NO se repite el pipeline completo — reanuda desde el stage fallido (tabla `processing_jobs`).

## 4. Flujo de consulta (§25–27)

1. **Router** clasifica la pregunta: A factual → LightRAG RAG; B conceptual → RAG+Wiki; C relación → Graphify `query`; D path → Graphify `path`; E síntesis global → Graph+RAG+Wiki; F verificación de fuente → RAG→evidencia original (chunk→doc→source); G memoria agente → índices de memoria; H educativa → KG + prerrequisitos + currículo + RAG.
2. **Retrieve** (top-50/100) → **dedupe** → **rerank** (opcional, top-5/10) → **compress** → **evidencia selectiva** → **contexto ensamblado** (cada fragmento con source/chunk/relevance/confidence/timestamp) → HERMES.
3. El prompt final **delimita contenido externo** `<external_source>…</external_source>` (defensa §33) y las respuestas citan `[Source: doc_id] [Chunk: chunk_id] [Page: n] [URL]`.

## 5. Flujo de memoria (§12, §13 separación)

```
conversación/Hermes-actions → candidates → importance score → dedupe → validar (LLM local) → persist (PG + vault/05_MEMORY/*)
```
- **Episódica**: eventos (qué hizo/investigó/descubrió Hermes).
- **Semántica**: hechos estables adquiridos. — **Procedural**: procedimientos (para X → pasos).
- **Decisiones**: Decisión+Razón+Alternativas+Fecha+Contexto+Resultado (ADR).
No se archiva cada conversación completa automáticamente.

**Separación crítica**: `world knowledge` (dominios) y `agent memory` (Hermes) viven en **espacios lógicos distintos** (namespace `tenant.agent` vs `tenant.world` en los índices; carpetas `00…` vs `05_MEMORY` en el vault) pero consultables simultáneamente.

## 6. Provenance y truth-status (§14/§51/§52)

Línea de evidencia `CLAIM → EVIDENCE → CHUNK → DOCUMENT → SOURCE`, con `status ∈ {EXTRACTED, INFERRED, SYNTHESIZED, HUMAN_VERIFIED}`.
- EXTRACTED = literal del source; INFERRED = deducción razonada; SYNTHESIZED = compilación LLM sobre múltiples fuentes (jamás presentada como cita directa); HUMAN_VERIFIED = revisada por humano.
- Conflictos: PG guarda claims competidores con `publication_date`, `confidence`, `context`; el sistema responde «Las fuentes difieren» sin forzar reconciliación (§15).

## 7. Flujo de backups (§34)

```
pg_dump (pgvector) → MinIO/vault 00_SYSTEM/backups/ ; `q.svg back snapshots` ; MinIO `mc mirror` ; graph.json + wiki (git tag); script restore hace: drop+restore PG, crear colección qdrant y re-importar vectores (o snap), restaura objetos MinIO, vuelve a generar wiki desde fuentes. Documentado en BACKUPS.md; test de DR en tests/.
```

## 8. Estructura de implementación

```
hermes-knowledge-os/
├── vault/            # Obsidian (UI humana)
├── src/  (config, db, s3, llm, embed, chunk, dedupe, graph (graphify wrapper), memory, wiki, routing, retrieval, provenance, observability, security)
├── workers/          # parser, embedder, graph, wiki, validation (esqueleto worker genérico)
├── scripts/          # helpers (seed, dashboard, backup, restore)
├── tests/
├── config/, docs/, data/(raw/staging/processed)
└── docker-compose.yml, Makefile, .env, .gitignore
```

## 9. Escalado (sin rediseño — ver docs/scaling/SCALING.md)

- Multi-worker local (MVP) → `workers/` con `__main__` y cola en PG → Redis/Celery (interfaz estable `JobQueue` en `src/jobs`).
- Vertical (más RAM/GPU) → mismo código; local-LLM opcional; embeddings en bach.
- Distribuido (10⁵⁺) → Qdrant clustering, PG replica, MinIO architecture, Graphify por dominios (múltiples `graph.json`), wiki por particiones.
- Cada hito 1K/10K/100K/1M/10M/100M: qué cambia (ver SCALING.md) y qué NO (IDs estables, versionado, colas, tenancy payloads).

## 10. Stack versionado (al momento de este diseño)

| Componente | Versión | Licencia |
|---|---|---|
| lightrag-hku | 1.5.6 | MIT |
| graphifyy | 0.9.36 | Apache-2.0 |
| Qdrant | 1.19.0 server | Apache-2.0 |
| PostgreSQL+pgvector | 17 | PostgreSQL |
| MinIO | latest (repo archivado) | AGPL-3.0 |
| Ollama | 0.32.6 | MIT (client) |
| qwen2.5:7b | (Ollama model) | Apache-2.0 |
| bge-m3 | (Ollama model) | MIT |
| Python | 3.12 (uv) | PSF |

*Fuente de verdad de versiones en vivo: `00_SYSTEM/VERSIONS.md`.*