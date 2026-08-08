# 04_GRAPH — Grafo del conocimiento

> Knowledge graph estructural (Graphify) + navegación conceptual.

## Contenido esperado (generado por `make graph`)
- `graph.json` — grafo consolidado (nodos/edges con procedencia).
- `graph.html` / `graph.svg` — visualizaciones.
- `GRAPH_REPORT.md` — estadísticas y clusters (Leiden).
- `entities/` — un archivo por entidad/módulo con sus relaciones.

## Generación

```bash
make graph DIR=data/raw   # corpus → grafo
kos graph                 # alias CLI
```

## Consultas desde Hermes
```bash
kos query "camino entre X e Y"          # tipo D (graph path)
kos query "¿qué explica X?"             # tipo C (relationship)
kos query "¿qué precede a X?"           # tipo D
```

## Notas
- Código → AST determinista (tree-sitter, sin LLM).
- Documentos → LLM local (qwen2.5:7b) con confidence EXTRACTED/INFERRED/AMBIGUOUS.
- El grafo de LightRAG es interno (retrieval); ESTE es el consultable (§8/§49).