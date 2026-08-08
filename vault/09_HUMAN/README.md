# 09_HUMAN — Guías humanas

> Procedimientos para humanos que alimentan el KOS (y para Hermes).

## Guías
- **Injerir un libro/paper**: colocar el PDF en `data/raw/<dominio>/` → `make ingest DIR=data/raw` → `make worker`.
- **Injerir una URL**: guardar el contenido en Markdown (o extraer con el script
  de fetch) → mismo flujo.
- **Injerir un proyecto de código**: `make graph DIR=<repo>` → AST determinista.
- **Pedir respuestas con evidencia**: `make query Q="…"` → cita `[Source:…][Chunk:…]`.

## Regla editorial
Todo lo que entra al vault 00-04 es **generado**; 09 es para flujos y notas humanas
(decisión de capa, ver ADR-006).