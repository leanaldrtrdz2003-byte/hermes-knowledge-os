# ADR-006 — Obsidian como vista humana (no backend)
**Estado**: aceptado · **Fecha**: 2026-08-08

El vault es una proyección navegable: wiki generada (02_WIKI), grafo (04_GRAPH),
memoria (05_MEMORY), docs del sistema (00_SYSTEM). Hermes nunca depende de
Obsidian; los datos viven en PG/Qdrant/MinIO (§4).

# ADR-007 — Modelos locales (qwen2.5:7b + bge-m3)
**Estado**: aceptado · **Fecha**: 2026-08-08

CPU-only (sin GPU): bge-m3 (1024 dims, multilingüe) + qwen2.5:7b. Coste 0,
privacidad total. Ver MODEL_SELECTION.md para el routing por tarea (§23).

# ADR-008 — Routing LLM por tarea
**Estado**: aceptado · **Fecha**: 2026-08-08

embedding dedicado (bge-m3), extracción barata (qwen2.5:7b), wiki/síntesis con
el mismo modelo local por defecto; el router final puede apuntar a proveedores
OpenAI-compatibles mediante `LLM_PROVIDER` (configurable, nunca hardcoded) (§22).