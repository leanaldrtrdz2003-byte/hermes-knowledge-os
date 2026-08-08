# Hermes Knowledge OS

> **Una biblioteca de conocimiento externa para agentes de IA** — ingesta inmutable,
> RAG híbrido (vectorial + gráfico), knowledge graph con export a Obsidian,
> wiki compilada y memoria de agente persistente. Pensado como segunda memoria
> de cualquier agente (Hermes, Claude, Codex, el que sea): el agente consulta,
> el KOS responde con citas verificables.

[![Estado](https://img.shields.io/badge/estado-producci%C3%B3n-2ea44f)](#)

---

## Tabla de contenidos

1. [Qué es y qué resuelve](#qué-es-y-qué-resuelve)
2. [Arquitectura](#arquitectura)
3. [Requisitos](#requisitos)
4. [Instalación (5 minutos)](#instalación)
5. [Configuración](#configuración)
6. [Uso: indexar contenido](#uso-indexar-contenido)
7. [Uso: consultar](#uso-consultar)
8. [Automatización (cron)](#automatización)
9. [Obsidian GUI](#obsidian-gui)
10. [Mantenimiento y backup](#mantenimiento)
11. [Solución de problemas](#solución-de-problemas)
12. [Escalado y rendimiento](#escalado)
13. [Roadmap / fases](#roadmap)
14. [Integrar con tu agente](#integrar-con-tu-agente)
15. [Licencia](#licencia)

---

## Qué es y qué resuelve

Los LLM olvidan y alucinan. KOS es una **memoria externa de producción**: guarda
tus fuentes (documentos, PDFs, código, notas), las indexa en vectores *y* en un
grafo de conocimiento, y responde a tu agente con **citas verificables**
(`[Source:…] [Chunk:…]`) en lugar de inventarse nada.

Se usa igual que una base de datos: el agente (o tú, desde CLI) hace una
pregunta, y el KOS devuelve una síntesis fundamentada **sobre tu propio corpus**.

### Ventajas frente a un RAG casero

| | RAG simple | KOS |
|---|---|---|
| Deduplicación | none | SHA-256 inmutable (re-ingesta = skip) |
| Indexación | vectorial | vectorial + **grafo** + wiki |
| Fuentes | en memoria | **MinIO/S3 inmutable** |
| Citación | opcional | **obligatoria en el router** |
| GUI humana | — | **Obsidian** (wiki + grafo) |
| Automatización | manual | `autopilot` + cron diario |
| Trazabilidad | — | costes/tokens registrados en PG |

---

## Arquitectura

```
            ┌────────────────────────────────────────────────────┐
            │                 TU AGENTE (Hermes, etc.)           │
            └───────────────┬────────────────────────────────────┘
                            │ query / memory
                            ▼
   ┌─────────────────────────────────────────────────────────────────┐
   │               Hermes Knowledge OS  (el "cerebro de datos")     │
   │                                                                 │
   │  cli.py  ── router ──┬─ vectorial (Qdrant)                      │
   │         │            ├─ gráfico (LightRAG: PG+Qdrant+NetworkX)  │
   │         │            └─ factual con citas [Source][Chunk]       │
   │         │                                                       │
   │  pipeline: ingest → parse → chunk → embed → index → graph → wiki│
   └──────┬──────────┬──────────┬──────────┬──────────┬──────────────┘
          │          │          │          │          │
     ┌────▼───┐ ┌────▼────┐ ┌───▼───┐ ┌────▼────┐ ┌──▼────────┐
     │ MinIO  │ │PostgreSQL│ │ Qdrant │ │ NetworkX│ │ vault/   │
     │ (fuentes)│ │+pgvector │ │ (vectores)│ │ (grafo) │ │ (Obsidian)│
     └────────┘ └─────────┘ └───────┘ └─────────┘ └───────────┘
```

**Capas**

| Capa | Tecnología | Guarda |
|---|---|---|
| Store inmutable | MinIO/S3 (`docker compose`) | fuentes originales, versiones |
| Control plane | PostgreSQL + pgvector (`docker compose`) | jobs, docs, chunks, grafo, costes |
| Índice vectorial | Qdrant (`docker compose`) | embeddings por chunk |
| Grafo | NetworkX + Graphify | entidades, relaciones, comunidades |
| RAG híbrido | LightRAG 1.5.6 + router propio | respuestas con citas |
| GUI humana | Obsidian (vault local) | wiki compilada, dashboard, grafo |

---

## Requisitos

- Linux/macOS (WSL en Windows)
- Docker y Docker Compose
- Python 3.12+ con **uv** (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Ollama (para embeddings locales; opcional si usas API)
- Node? No: Obsidian es opcional (solo GUI)

---

## Instalación

```bash
# 1. Clona
git clone https://github.com/leanaldrtrdz2003-byte/hermes-knowledge-os.git
cd hermes-knowledge-os

# 2. Entorno Python con uv
uv venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt

# 3. Configura (ver siguiente sección)
cp .env.example .env
$EDITOR .env

# 4. Infra (MinIO + PostgreSQL + Qdrant) — primera vez
docker compose up -d

# 5. Inicializa esquema, buckets, colecciones
make setup        # = python src/kos/cli.py setup

# 6. Comprueba: `make test` debe dar verde
make test
```

---

## Configuración

Copia `.env.example → .env` y rellena al menos:

| Variable | Qué es |
|---|---|
| `POSTGRES_PASSWORD` | password del PG del control plane |
| `S3_SECRET_KEY`, `MINIO_ROOT_PASSWORD` | credenciales del store de objetos |
| `LLM_API_KEY` | API key del modelo generativo (OpenAI-compatible) |
| `LLM_FALLBACK_API_KEY` | API key del proveedor de *fallback* |

**LLM generativo**: todo el pipeline (graph, wiki, router, LightRAG) usa un
único proveedor compatible con OpenAI:

```dotenv
LLM_PROVIDER=openai
LLM_MODEL=deepseek-v4-flash-free
LLM_BASE_URL=https://opencode.ai/zen/v1
LLM_API_KEY=tu_clave
LLM_TIMEOUT=1200
```

**Embeddings**: por defecto locales con Ollama (sin GPU):

```dotenv
EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=bge-m3        # descarga automática: ollama pull bge-m3
EMBEDDING_BASE_URL=http://127.0.0.1:11434
```

---

## Uso: indexar contenido

### 1. Deja tus archivos en `data/raw/`

```
data/raw/
├── historia/roma.md
├── fisica/termodinamica.pdf
└── codigo/api_docs.py
```

### 2. Ingesta — un comando

```bash
env -u PYTHONPATH .venv/bin/python src/kos/cli.py ingest data/raw
```

Hash SHA-256 por documento → **solo nuevos** (re-ingeste = skip).

### 3. Procesa la cola

```bash
env -u PYTHONPATH .venv/bin/python src/kos/cli.py worker --worker-id w1
# varios a la vez:            --worker-id w2   (segunda terminal)
```

### 4. Regenera los artefactos (opcional)

```bash
make wiki    ## wiki compilada del corpus
make graph   ## grafo Obsidian + JSON
```

---

## Uso: consultar

```bash
# Responde con citas a tus fuentes:
env -u PYTHONPATH .venv/bin/python src/kos/cli.py query "¿Qué es la entropía?"
#   → respuesta + [Source: d83bd…] [Chunk: f23e…]
```

Modo RAG híbrido (grafo + vectores) se usa desde Python:

```python
import asyncio
from kos import router

resp = asyncio.run(router.answer("¿…?", mode="hybrid"))
print(resp["answer"])          # síntesis
print(resp["evidence_n"])      # nº de chunks citados
```

### API HTTP (agentes sin CLI)

Levanta un servidor HTTP (stdlib, sin dependencias extra) para que Hermes,
Claude u otros agentes consulten el KOS sin `subprocess`:

```bash
env -u PYTHONPATH .venv/bin/python src/kos/server.py --host 127.0.0.1 --port 8747
curl http://127.0.0.1:8747/health          # estado: db, documents, queue
curl -X POST http://127.0.0.1:8747/query \
  -d '{"question":"¿…?","mode":"hybrid","session_id":"mi-sesion"}'
```

- `session_id` opcional: mantiene **memoria conversacional** (los últimos 6
  turnos se inyectan al prompt); responde con el mismo `session_id`.
- `GET /stats` expone las métricas del dashboard (JSON).

---

## Automatización

El script `scripts/autopilot.sh` hace todo el ciclo (ingesta incremental +
worker + wiki/grafo/dashboard **solo si hubo novedades** + backup). Actívalo
a diario con **systemd** o cron:

```bash
# systemd (Linux) — timer diario a las 03:30
mkdir -p ~/.config/systemd/user
# (copia scripts/systemd/kos-autopilot.* si lo prefieres, o crea tu .timer)
systemctl --user enable --now kos-autopilot.timer

# o cron clásico
crontab -e   # →  0 3 * * * ~/hermes-knowledge-os/scripts/autopilot.sh >> /tmp/kos-cron.log 2>&1
```

**Watchdog de salud** (`scripts/watchdog.sh`): comprueba que el autopilot
corrió en las últimas 26 h y que el corpus no esté vacío; sale con código 1 y
lista los problemas. Útil como segundo timer (07:45):

```bash
cp scripts/systemd/kos-watchdog.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now kos-watchdog.timer
```

---

## Obsidian GUI

1. Instala Obsidian (`paru -S obsidian-bin` en Arch, o [obsidian.md](https://obsidian.md))
2. Abre el **vault** en `~/hermes-knowledge-os/vault`
3. Acepta "Trust author" (es tu carpeta)
4. Verás:
   - `02_WIKI/` — wiki compilada de todo tu corpus
   - `04_GRAPH/exports/README.md` — grafo con comunidades
   - `00_SYSTEM/DASHBOARD.md` — métricas en vivo
   - `00_SYSTEM/BENCHMARK.md` — comparativa de estrategias

---

## Mantenimiento

```bash
make test          # suite pytest (14 tests)
make backup        # pg_dump + tar.gz de artefactos → data/backups/
make restore F=<backup_id>   # restaurar
docker compose ps  # estado de MinIO/PG/Qdrant
```

Los backups también se generan solos cada carrera del autopilot.

---

## Solución de problemas

| Síntoma | Causa / fix |
|---|---|
| Query responde vacío | `DELETE FROM lightrag_llm_cache` (cache con respuesta vacía previa) |
| `ingest` informa 0 | Es dedupe: ya está indexado (hash SHA-256) |
| `ENOENT` python | Activa venv: `source .venv/bin/activate` o `.venv/bin/python` |
| Ollama caído | `systemctl start ollama` / `ollama serve` |
| Gráfico vacío | El LLM no devolvió JSON; revisar logs del worker |
| Docker compose interpola mal | Valores en duda en `.env` (`docker compose config --quiet`) |

---

## Escalado

- Más workers: la cola de jobs está en PostgreSQL, lanza N procesadores
  `worker --worker-id` o usa `--concurrency N` dentro de un worker
  (paralelismo con semáforo). `ingest --limit N` da backpressure por corrida
  (no volcar 10k docs en una noche) y `worker --rate-limit S` espacia los jobs.
- Embeddings: mover a servicio remoto cambiando `EMBEDDING_BASE_URL`
- 1.000.000 chunks: PG + Qdrant aguantan sin tuneo previo; monitoriza con
  `make dashboard` (15 métricas)
- El benchmark (`vault/00_SYSTEM/BENCHMARK.md`) mide naive vs local vs hybrid

---

## Roadmap (fases implementadas)

| Fase | Contenido | Estado |
|---|---|---|
| F1 | Store inmutable MinIO | ✅ |
| F2 | Control plane PG+pgvector | ✅ |
| F3 | Pipeline completo | ✅ |
| F4 | Knowledge graph (Graphify→Obsidian) | ✅ |
| F5 | LightRAG híbrido | ✅ |
| F6 | Workers 24/24 | ✅ |
| F7 | Query con citas | ✅ |
| F8 | Wiki + dashboard | ✅ |
| F9 | Backup/restore | ✅ |
| F10 | Benchmark 3 estrategias | ✅ |
| F11 | Automatización + docs | ✅ |
| A/B/C | Mejoras post-F11 (CI, backpressure, dominios, API HTTP, watchdog) | ✅ |

---

## Integrar con tu agente

La vía recomendada es la **API HTTP** (servidor sin estado, sin subprocess):
```python
import httpx
def kos_query(pregunta: str, session: str | None = None) -> str:
    r = httpx.post("http://127.0.0.1:8747/query",
                   json={"question": pregunta, "mode": "hybrid",
                         "session_id": session}, timeout=600)
    return r.json()["answer"]
```
La vía simple sigue disponible: el agente usa el CLI como herramienta.

```python
# en tu proveedor de herramientas
import subprocess
def kos_query(pregunta: str) -> str:
    return subprocess.run(
        ["env", "-u", "PYTHONPATH", ".venv/bin/python", "src/kos/cli.py",
         "query", pregunta],
        capture_output=True, text=True, cwd="/ruta/a/hermes-knowledge-os",
    ).stdout
```

El KOS es agnóstico de proveedor: no sabe quién pregunta, solo responde con
evidencias. Úsalo desde Hermes (tool call), Claude Code (herramienta YAML),
Codex CLI, etc.

---

## Licencia

MIT · Proyecto abierto — fork, implementalo para tus propios agentes y
contribuye. Hecho con el stack: PostgreSQL, Qdrant, MinIO, LightRAG, Graphify,
NetworkX, Obsidian.