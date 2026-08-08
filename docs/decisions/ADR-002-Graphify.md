# ADR-002 — Graphify como Knowledge Graph estructural
**Estado**: aceptado · **Fecha**: 2026-08-08

## Contexto
El RAG semántico no responde bien preguntas relacionales (paths, dependencias,
prerrequisitos). Se necesita un grafo estructural con procedencia.

## Decisión
`graphifyy 0.9.36` (Apache-2.0/MIT) como Knowledge Graph estructural:
- Código → AST determinista local (tree-sitter, 25 lenguajes), sin LLM.
- Documentos → extracción de entidades/relaciones con LLM local (qwen2.5:7b)
  emitiendo el mismo schema `{nodes, edges}` con confidence
  EXTRACTED/INFERRED/AMBIGUOUS.
- Merge → Leiden clustering → export: `graph.json`, vault Obsidian, HTML/SVG,
  GRAPH_REPORT.md.

## Alternativas
- Neo4j: infraestructura extra sin justificar en una máquina (§35).
- LightRAG graph interno: sirve para retrieval, no como KG consultable.

## Tradeoffs
- El extractor LLM local es lento en CPU pero coste 0 y reanudable (SHA256 cache).
