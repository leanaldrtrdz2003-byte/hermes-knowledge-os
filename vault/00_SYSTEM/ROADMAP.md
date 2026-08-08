# ROADMAP — Hermes Knowledge OS

> Fases de implementación (§59). Estado: en curso — Fase 6 (pipeline).

## F1 — Auditoría ✅
- Entorno inspeccionado (§65), componentes verificados en sus repos oficiales.
- Entregable: `AUDIT.md`.

## F2 — Arquitectura ✅
- Entregables: `ARCHITECTURE.md`, `DATA_MODEL.md`.

## F3 — Infraestructura ✅
- Docker Compose: PostgreSQL+pgvector, Qdrant 1.19.0, MinIO — **healthy**.
- Ollama 0.32.6 (daemon systemd) + modelos `qwen2.5:7b` y `bge-m3`.

## F4 — Graphify 🔄
- Skill instalada; librería integrada en `src/kos/graph.py`.
- Pendiente: grafo del corpus completo + export Obsidian (`make graph`).

## F5 — LightRAG ✅
- Motor operativo end-to-end: PG KV/DocStatus + Qdrant + NetworkX + Ollama.
- Verificado con consulta real con referencias (ver CHANGELOG).

## F6 — Pipeline 🔄
- Módulos: jobs, dedupe, chunk, embed, graph, wiki, memory, router, cli.
- Workers procesando el corpus de prueba (4 documentos multi-dominio).

## F7 — Hermes (router + citas) 🔄
- Router A–H + fence anti-inyección + citas implementados (`router.py`).
- Pendiente: validación con corpus completo.

## F8 — Obsidian
- Estructura del vault creada; pendiente: dashboards vivos y navegación.

## F9 — Tests
- Unitarios (7) verdes; integración escritos; pendiente: ejecución completa.

## F10 — Benchmark
- Pendiente: LightRAG vs Graphify vs híbrido sobre el corpus.

## F11 — Escalabilidad + docs
- Pendiente: pruebas de escala sintética, `IMPLEMENTATION_COMPLETE.md`.

## Próximos hitos
1. Worker termina el corpus → `kos query` con citas.
2. `make graph` → grafo estructural + vault Obsidian navegable.
3. Benchmark F10 y docs finales.
