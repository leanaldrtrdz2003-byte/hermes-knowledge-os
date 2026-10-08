# Guía del contribuidor primo — Hermes Knowledge OS

> Idioma: español neutro. El código y los comentarios del repositorio están en inglés; esta guía está en español porque su audiencia es hispana.

## 1. Para quién es esta guía

Para una persona con experiencia básica en Linux y Git que quiere clonar este repositorio y dejarlo funcionando de principio a fin: infraestructura, ingesta de documentos y primera consulta. No se asume experiencia previa con RAG, vectores ni Obsidian.

## 2. Qué es Hermes Knowledge OS (en 5 líneas)

1. Es una memoria externa para agentes: guarda documentos y los convierte en conocimiento consultable.
2. Combina búsqueda híbrida (texto + vectores) con un grafo de conocimiento y páginas wiki generadas.
3. La infraestructura mínima es PostgreSQL (metadatos), Qdrant (vectores) y MinIO (fuentes inmutables).
4. Se opera con un CLI en Python (`src/kos/cli.py`), un servidor HTTP JSON (`src/kos/server.py`) y el vault de Obsidian (`vault/`).
5. Hoy no existe interfaz web: todo se hace por terminal, API JSON y Obsidian (ver sección 9).

## 3. Prerrequisitos

| Requisito | Detalle |
|---|---|
| Sistema operativo | Linux (probado en Arch; cualquier distribución moderna sirve) |
| Docker + Compose v2 | Demonio corriendo (`docker info` debe responder) |
| Python 3.12 | El proyecto usa `uv`; el intérprete del `.venv` es 3.12 |
| uv | Gestor de entornos y paquetes (`which uv`) |
| Ollama | Instalado y con el modelo `bge-m3` descargado (`ollama pull bge-m3`) |
| Obsidian (opcional) | Solo para visualizar el vault como base de conocimiento |
| Puertos libres | 5432 (PostgreSQL), 6333 (Qdrant), 9000/9001 (MinIO), 8747 (servidor KOS), 11434 (Ollama) |
| Clave de LLM | Variable `LLM_API_KEY` con valor válido (ver paso 2); sin ella las respuestas generativas fallan con 401 |

## 4. Paso 0 — Pre-chequeo (antes de clonar)

Ejecutar estos comandos y confirmar que todos responden:

```bash
python3 --version        # cualquier 3.x del sistema; el proyecto usará 3.12 en .venv
which uv docker
docker info              # el daemon debe estar corriendo
ollama list              # debe mostrar bge-m3; si no: ollama pull bge-m3
ss -ltn | grep -E '5432|6333|9000|9001|8747|11434' || echo "puertos libres"
```

Si `docker info` falla, iniciar el demonio Docker antes de continuar. Si falta `bge-m3`, descargarlo con `ollama pull bge-m3`.

## 5. Paso 1 — Clonar e instalar dependencias

```bash
git clone https://github.com/leanaldrtrdz2003-byte/hermes-knowledge-os.git
cd hermes-knowledge-os
uv venv --python 3.12
uv pip install -r requirements.txt
```

Esto crea `.venv/` con Python 3.12 y todas las dependencias. No versionar `.venv/` (ya está en `.gitignore`).

## 6. Paso 2 — Configurar variables de entorno

```bash
cp .env.example .env
chmod +x scripts/*.sh
docker compose config --quiet && echo "compose OK"
```

Editar `.env` y completar como mínimo estas variables:

| Variable | Para qué sirve | Ejemplo / valor esperado |
|---|---|---|
| `POSTGRES_PASSWORD` | Contraseña del PostgreSQL local | Generar una propia (reemplazar el `CHANGE_ME`) |
| `MINIO_ROOT_PASSWORD` | Contraseña del MinIO local | Generar una propia (reemplazar el `CHANGE_ME`) |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | Credenciales S3 que usa el pipeline contra MinIO | Deben coincidir con el usuario root de MinIO |
| `LLM_API_KEY` | Clave del proveedor generativo | Vacía = consultas generativas devuelven 401 |
| `LLM_FALLBACK_API_KEY` | Clave del modelo de respaldo | Recomendada; sin ella no hay respaldo ante fallos del primario |

`docker compose config --quiet` valida que el YAML y las variables son correctas sin levantar nada. Si falla, revisar `.env` antes de seguir. Nunca subir `.env` a git.

## 7. Paso 3 — Levantar infraestructura y preparar esquemas

```bash
docker compose up -d
docker compose ps
sleep 10
make setup
```

Notas:

- `docker compose ps` puede mostrar el contenedor MinIO como `unhealthy`: es un problema conocido (el healthcheck usa `mc`, que no existe dentro de la imagen). Ignorarlo por ahora; MinIO funciona aunque el estado diga lo contrario.
- `make setup` crea el esquema de PostgreSQL, el bucket de MinIO y la colección de Qdrant. Si falla, ir a la tabla de troubleshooting (sección 8).

## 8. Paso 4 — Verificación liviana (sin integración)

```bash
env -u PYTHONPATH .venv/bin/python -m pytest tests -q -m "not integration"
```

Por qué este comando y no `make test` completo: `make test` ejecuta `pytest tests -q` sin filtros e incluye pruebas de integración que exigen infraestructura levantada (PostgreSQL, Qdrant, Ollama/MinIO). En un clon fresco eso falla aunque el código esté bien. El filtro `-m "not integration"` ejecuta solo las 7 pruebas unitarias y confirma que la instalación es correcta. Las pruebas de integración se ejecutan después, con la infraestructura verificada.

## 9. Paso 5 — Ciclo mínimo: ingesta → consulta → servidor → Obsidian

```bash
mkdir -p data/raw/demo
echo "Hermes Knowledge OS es la memoria externa de mis agentes." > data/raw/demo/nota.md
env -u PYTHONPATH .venv/bin/python src/kos/cli.py ingest data/raw/demo
env -u PYTHONPATH .venv/bin/python src/kos/cli.py worker --once
env -u PYTHONPATH .venv/bin/python src/kos/cli.py query "¿Qué es Hermes Knowledge OS?" --mode hybrid
```

Levantar el servidor HTTP y consultar la API JSON:

```bash
env -u PYTHONPATH .venv/bin/python src/kos/server.py --host 127.0.0.1 --port 8747 &
curl -s http://127.0.0.1:8747/health
curl -s -X POST http://127.0.0.1:8747/query \
  -H 'Content-Type: application/json' \
  -d '{"question": "¿Qué es Hermes Knowledge OS?", "mode": "hybrid"}'
```

Abrir el vault en Obsidian (opcional): abrir la aplicación, elegir `Open folder as vault` y seleccionar la carpeta `vault/` del repositorio. Las páginas generadas aparecen bajo `vault/02_WIKI/`.

## 10. Troubleshooting

| Síntoma | Causa probable | Solución |
|---|---|---|
| `POSTGRES_PASSWORD is not set` al levantar compose | Falta `.env` o variable sin completar | `cp .env.example .env`, completar los `CHANGE_ME`, reintentar |
| `docker info` no responde / puertos ocupados | Demonio Docker detenido o puertos en uso | Iniciar Docker; liberar 5432/6333/9000/9001/8747/11434 |
| `No module named kos` o versiones raras | `.venv` inexistente o intérprete incorrecto | Recrear con `uv venv --python 3.12` e instalar `requirements.txt`; invocar siempre con `env -u PYTHONPATH .venv/bin/python` |
| `ollama list` no muestra `bge-m3` | Modelo de embeddings no descargado | `ollama pull bge-m3` y verificar que Ollama responde en 11434 |
| Error 401 del LLM / respuesta vacía | `LLM_API_KEY` vacía o inválida | Completar `LLM_API_KEY` (y `LLM_FALLBACK_API_KEY`) en `.env` |
| `make test` falla pero unitarias pasan | Integración sin infraestructura | Esperado: usar `-m "not integration"` hasta tener PG+Qdrant+Ollama verificados |
| `ENOENT data/raw/...` al ingerir | Ruta inexistente (`data/` está ignorada por git y no se clona) | Crear la carpeta con `mkdir -p` antes de ingerir |
| `data/raw` aparece vacío tras clonar | Correcto: `data/` está en `.gitignore` | Los documentos fuente los aporta cada usuario; nunca se versionan |
| `connection refused` a Qdrant (6333) o PG (5432) | Contenedores caídos o sin `make setup` | `docker compose up -d`, esperar 10 s, `make setup`, reintentar |
| MinIO figura `unhealthy` | Bug conocido: healthcheck invoca `mc`, ausente en la imagen | Ignorar el estado; verificar con `curl http://127.0.0.1:9000/minio/health/live` |

## 11. Interfaz gráfica (futuro, no implementado)

Hoy no existe frontend web. La operación es por CLI (`src/kos/cli.py`), API JSON sobre stdlib (`src/kos/server.py`, puerto 8747) y Obsidian sobre `vault/`. Implementar una interfaz gráfica implicaría, como mínimo:

1. Elegir stack del frontend (estático vs. framework) y su hospedaje.
2. Autenticación y autorización para exponer consultas fuera de `127.0.0.1`.
3. CORS y validación de entradas en `server.py` (hoy es un servidor de desarrollo sin estas capas).
4. Consultas con streaming (SSE/WebSocket) en lugar de JSON de respuesta única.
5. Subida de documentos desde el navegador hacia `data/raw` o directo a MinIO.
6. Visualización del grafo de conocimiento (hoy solo exportaciones generadas).

Nada de lo anterior está implementado; esta sección es solo el mapa de trabajo futuro.

## 12. Cómo contribuir

- Crear una rama por cambio (`git checkout -b tipo/descripcion`) y abrir PR contra `main`.
- Mensajes de commit convencionales en inglés (ejemplo: `fix(watchdog): ...`, `docs: ...`). Sin `Co-Authored-By`.
- No subir nunca: `.env`, `data/`, `.venv/`, `.atl/`, `vault/10_RASHIN/`, snippets personales de Obsidian ni `*.bak`.
- Verificación mínima antes de pedir revisión: `docker compose config --quiet` y `pytest -m "not integration"` en verde.
