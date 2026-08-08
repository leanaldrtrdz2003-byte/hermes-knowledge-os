# GUÍA DE USO — Hermes Knowledge OS

Guía práctica para indexar contenido y mantener el sistema automático.
Todos los comandos desde la raíz del proyecto (`~/hermes-knowledge-os`).

## 1. Qué hace el sistema (en 30 segundos)

1. **ingest** — copia tus archivos a MinIO (store inmutable, dedupe por hash).
2. **worker** — procesa la cola: parse → chunk → embed (bge-m3 local) → Qdrant
   → entidades/relaciones (grafo) → wiki.
3. **query** — responde con citas `[Source:…] [Chunk:…]` o con el grafo LightRAG.
4. **vault/** — Obsidian con todo: wiki, dashboard, grafo, benchmark.

LLM generativo: **deepseek-v4-flash-free** (zen) con fallback **deepseek-v4-flash**
(opencode-go). Embeddings: **Ollama bge-m3 local** (sin coste, sin red).

## 2. Indexar contenido nuevo

### Paso 1 — Deja los archivos en `data/raw/`

Soporta: `.md`, `.txt`, `.pdf`, `.py`, `.json` (y carpetas). Organización libre:
```
data/raw/
├── matematicas/entropia.md
├── fisica/termodinamica.txt
└── programacion/transformers.py
```

### Paso 2 — Ingesta (un comando)
```bash
source .venv/bin/activate
env -u PYTHONPATH python src/kos/cli.py ingest data/raw          # todo
env -u PYTHONPATH python src/kos/cli.py ingest data/raw/fisica   # solo una carpeta
```
Dedupe automático: re-ingest de lo ya indexado = `skipped`, no duplica.

### Paso 3 — Procesa la cola (worker)
```bash
env -u PYTHONPATH python src/kos/cli.py worker --worker-id w1    # procesa TODO
```
Puedes lanzar **varios workers en paralelo** (`w1`, `w2`, …) para acelerar.
Estado: `env -u PYTHONPATH python src/kos/cli.py versions`.

### Paso 4 — Regenera wiki/grafo/dashboard (opcional, tras ingesta)
```bash
env -u PYTHONPATH python src/kos/cli.py wiki
env -u PYTHONPATH python src/kos/cli.py graph --dir vault/04_GRAPH
env -u PYTHONPATH python scripts/dashboard_md.py
```

## 3. Consultar el conocimiento

```bash
# Router con citas (rápido, factual):
env -u PYTHONPATH python src/kos/cli.py query "¿Qué es la entropía y qué mide?"

# LightRAG híbrido (grafo + contexto): usa le.query (ver docs/API o tests)
```

## 4. TODO AUTOMÁTICO (cron)

El script `scripts/autopilot.sh` orquesta el ciclo completo: ingesta → worker
hasta cola vacía → wiki/grafo/dashboard → backup. Dos formas de programarlo:

### Opción A — Cron del usuario (recomendado)
```bash
crontab -e
# Añade (cada noche a las 03:00):
0 3 * * * /home/lean_rdz_2003/hermes-knowledge-os/scripts/autopilot.sh >> /tmp/kos-cron.log 2>&1
```

### Opción B — Un cron de Hermes (si prefieres que un agente lo supervise)
Puedes pedirle a Hermes: "ejecuta cada día a las 3:00 el autopilot del KOS y
resume los cambios" — se gestiona con la herramienta cron del agente.

Chequeo de salud tras cada cron: `tail -20 /tmp/kos-autopilot.log`.

## 5. Mantenimiento y recuperación

| Tarea | Comando |
|---|---|
| Backup manual | `env -u PYTHONPATH python src/kos/cli.py backup` |
| Restore | `env -u PYTHONPATH python src/kos/cli.py restore <backup_id>` |
| Vaciar/reintentar cola | `DELETE FROM ingestion_jobs WHERE status='failed'` (psql) |
| Limpiar cache LLM LightRAG | `DELETE FROM lightrag_llm_cache` (si responde vacío) |
| Ver infra | `docker compose ps` |
| Verificar integridad | `env -u PYTHONPATH python -m pytest tests/ -q` |

## 6. Infraestructura (una vez, ya hecha)

- `docker compose up -d` → MinIO, PostgreSQL(+pgvector), Qdrant (healthchecks).
- LLM/embeddings se configuran en `.env` (`LLM_*`, `EMBEDDING_*`, `LLM_FALLBACK_*`).
- Ollama local sirve embeddings (`bge-m3`); el daemon debe estar activo:
  `systemctl status ollama`.

## 7. Solución de problemas comunes

| Síntoma | Causa/fix |
|---|---|
| Query responde vacío | `DELETE FROM lightrag_llm_cache;` y repite |
| Ingsta "no hace nada" | Es dedupe: ya está indexado (hash) |
| `ENOENT` python | `source .venv/bin/activate` o usar `.venv/bin/python` |
| OLlama caído | `systemctl start ollama` |
| Gpraph 0 entidades | El LLM no devolvió JSON: revisar `graph.py` prompt (ya endurecido)