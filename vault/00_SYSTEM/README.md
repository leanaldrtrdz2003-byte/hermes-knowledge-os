# 00_SYSTEM — Documentación del Knowledge OS

> Núcleo documental del sistema. Leer primero: ARCHITECTURE.

## Mapa de documentos

| Documento            | Contenido                                          |
|----------------------|----------------------------------------------------|
| AUDIT.md             | Auditoría del entorno previa a instalación (§65)   |
| ARCHITECTURE.md      | Arquitectura multicapa de referencia               |
| DATA_MODEL.md        | Modelo lógico: PG control plane + MinIO + índices  |
| OPERATIONS.md        | Arranque, ingesta, consulta, backups, troubleshooting |
| SECURITY.md          | Modelo de amenazas: secrets, prompt-injection      |
| COST_MODEL.md        | Costes por componente y optimizaciones (§46/§31)   |
| MODEL_SELECTION.md   | Modelos y embeddings: routing por tarea (§23)      |
| VERSIONS.md          | Versiones del stack y reglas de actualización      |
| DASHBOARD.md         | Métricas y cómo regenerarlas (`make dashboard`)    |
| ROADMAP.md           | Fases 1–11 y estado actual                         |
| CHANGELOG.md         | Registro de cambios estructurales (§54)            |

## Convención de citas
Toda decisión de código/documento cita la regla del brief (§N) que la motiva.

## Relación con el resto del vault
- `01_SOURCES/` → fuentes y corpus crudo.
- `02_WIKI/` → wiki compilada (§9/§13) — *nunca* editar a mano.
- `04_GRAPH/` → grafo estructural (Graphify) y navegación.
- `05_MEMORY/` → memoria del agente (separada del conocimiento mundial).
- `09_HUMAN/` → guías humanas (ingesta de libros/papers/URLs).
- `99_ARCHIVE/` → versiones antiguas y material descartado.