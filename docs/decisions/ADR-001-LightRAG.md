# ADR-001 — LightRAG como motor RAG
**Estado**: aceptado · **Fecha**: 2026-08-08

## Contexto
Necesitamos un motor de retrieval-augmented generation con dual-level retrieval
(local + global), actualización incremental y backends de producción.

## Decisión
`lightrag-hku 1.5.6` (MIT) con:
- KV + DocStatus → PostgreSQL (`PGKVStorage`/`PGDocStatusStorage`)
- Vectores → Qdrant (`QdrantVectorDBStorage`)
- Grafo interno → `NetworkXStorage` (JSON; el KG estructural es Graphify)
- LLM/embeddings → Ollama local (qwen2.5:7b / bge-m3)

## Alternativas
- RAG naive con Qdrant solo: sin dual-level ni entidades/relaciones.
- GraphRAG de Microsoft: más pesado y pensado para pipeline offline.

## Tradeoffs
- CPU local: lento en generación (minutos/doc) pero coste 0.
- `lightrag.llm.ollama` (módulo) no importa en 1.5.6 → usamos las funciones
  `ollama_model_complete`/`ollama_embed` directamente (verificado E2E).
