# ROADMAP — Hermes Knowledge OS

> Estado real por fase (§59). **Actualizado 2026-08-08**: todas las fases
> implementadas y verificadas. El corpus de prueba fue eliminado; queda
> pendiente alimentar el corpus real del usuario.

## F1 — Auditoría ✅
- Entorno inspeccionado (§65), componentes verificados en sus repos oficiales.
- Entregable: `AUDIT.md`.

## F2 — Arquitectura ✅
- Entregables: `ARCHITECTURE.md`, `DATA_MODEL.md`.

## F3 — Infraestructura ✅
- Docker Compose: PostgreSQL+pgvector, Qdrant, MinIO — **healthy**.
- Ollama (daemon systemd) + modelo de embeddings `bge-m3` (el LLM generativo
  es remoto por diseño; los embeddings son 100% locales).

## F4 — Graphify ✅
- Librería integrada en `src/kos/graph.py`; export a Obsidian con
  **comunidades** (clustering) — `graph.json` + notas + SVG/HTML.
- **Mejora Fase A2**: retry + validación de JSON del LLM en la extracción.

## F5 — LightRAG ✅
- Motor operativo end-to-end: PG KV/DocStatus + Qdrant + NetworkX.
- Wrapper async `_zen_complete` (firma compatible LightRAG↔openai, ignora
  kwargs extra) con **fallback** al segundo modelo.
- Embeddings locales vía Ollama bge-m3 (`EMBEDDING_BASE_URL` separada).

## F6 — Pipeline ✅
- Módulos: jobs, dedupe, chunk, embed, graph, wiki, memory, router, cli.
- Workers concurrentes con cola en PostgreSQL; flag `--once` para
  automatización (termina al vaciar la cola).

## F7 — Router con citas ✅
- Router A–H + fence anti-inyección + citas verificables (`[Source:]` `[Chunk:]`).

## F8 — Obsidian y observabilidad ✅
- Vault con estructura completa; wiki compilada; dashboard con métricas;
  benchmark documentado (3 estrategias comparadas en `BENCHMARK.md` — el
  benchmark de prueba fue limpiado; se regenerará con el corpus real).

## F9 — Tests ✅
- Suite pytest **14/14 verde** (`make test`), verificada tras cada cambio.

## F10 — Benchmark ✅
- Comparativa vectorial / lightrag / router híbrido sobre el corpus de prueba
  (vectorial 0.4 s · score ~1.0; router con citas 8-22 s). A re-medir con el
  corpus real.

## F11 — Automatización + docs ✅
- `scripts/autopilot.sh` (idempotente: backup → ingesta incremental → worker →
  wiki/grafo/dashboard), timer systemd diario 03:30, `worker --once`.
- Docs: `IMPLEMENTATION_COMPLETE.md`, `GUIA_DE_USO.md`, README público.

## Mejoras post-F11 (fases A/B/C — 2026-08-08)
- **A1**: ROADMAP/CHANGELOG al día; limpieza de artefactos duplicados. ✅
- **A2**: retry + validación JSON en extracción de entidades. ✅
- **A3**: CI mínimo (GitHub Actions: pytest + bash -n + systemd-analyze). ✅
- **B1**: ingesta batch con control de concurrencia. ✅
- **B2**: regeneración selectiva de wiki/grafo solo si hubo novedades. ✅
- **B3**: grafo por dominios. ✅
- **C1**: endpoint HTTP de consulta (sin depender del CLI/agente). ✅
- **C2**: memoria de sesión de consultas + watchdog de salud. ✅

## Pendiente
- **Corpus real**: el usuario aportará sus documentos (PDFs, notas, proyectos);
  la próxima ingesta generará wiki/grafo/dashboard con datos reales.
- Eval formal de retrieval con preguntas golden (oportunidad futura).