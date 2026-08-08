#!/usr/bin/env bash
# Autopiloto del Knowledge OS — ciclo completo de ingesta automática.
#
# 1) Ingesta: vuelca data/raw (y carpetas extra pasadas como args) al store inmutable.
#              Idempotente por hash SHA-256: sólo los archivos nuevos entran.
# 2) Procesa:  lanza un worker que consume la cola (parse→chunk→embed→index→graph→wiki).
# 3) Re-export: regenera wiki faltante, grafo Obsidian y dashboard.
# 4) Respaldo:  pg_dump + tar.gz de artefactos (ADR-009).
#
# Uso:   scripts/autopilot.sh [--no-backup] [dir_extra1 dir_extra2 ...]
# Cron:  con crontab del usuario (ver GUIA_DE_USO.md).

set -euo pipefail
cd "$(dirname "$0")/.."

LOG=/tmp/kos-autopilot.log
PY=(env -u PYTHONPATH .venv/bin/python)

# Filtra --no-backup; el resto son carpetas extra para ingest.
EXTRA=()
DO_BACKUP=1
for a in "$@"; do
  if [ "$a" = "--no-backup" ]; then DO_BACKUP=0; else EXTRA+=("$a"); fi
done

echo "[autopilot $(date +%H:%M:%S)] ingesta: data/raw ${EXTRA[*]:-}" >> "$LOG"

# Conteo de docs ANTES (para regeneración selectiva de wiki/grafo/dashboard)
N_DOCS_ANTES=$("${PY[@]}" - <<'PYEOF' 2>> "$LOG" || echo 0
import asyncio, sys
sys.path.insert(0, "src")
from kos import db
async def main():
    pool = await db.get_pool()
    return await pool.fetchval("SELECT COUNT(*) FROM documents")
print(asyncio.run(main()) or 0)
PYEOF
)

"${PY[@]}" src/kos/cli.py ingest data/raw "${EXTRA[@]}" >> "$LOG" 2>&1 || true

# ¿Hubo docs nuevos? (regeneración selectiva: wiki/grafo/dashboard solo si cambió algo)
NOVEDADES=$("${PY[@]}" - "$N_DOCS_ANTES" <<'PYEOF' 2>> "$LOG" || echo 0
import asyncio, sys
sys.path.insert(0, "src")
from kos import db
async def main():
    pool = await db.get_pool()
    now = await pool.fetchval("SELECT COUNT(*) FROM documents")
    return 1 if now > int(sys.argv[1]) else 0
print(asyncio.run(main()))
PYEOF
)
echo "[autopilot $(date +%H:%M:%S)] worker iniciado" >> "$LOG"

# El worker procesa la cola y termina cuando queda vacía (bucle de guardia).
for i in $(seq 1 12); do
  "${PY[@]}" src/kos/cli.py worker --worker-id autopilot --once >> "$LOG" 2>&1 || true
  PENDIENTES=$("${PY[@]}" - <<'PYEOF' 2>> "$LOG" || echo 0
import asyncio, sys
sys.path.insert(0, "src")
from kos import db
async def main():
    pool = await db.get_pool()
    print(await pool.fetchval("SELECT COUNT(*) FROM ingestion_jobs WHERE status IN ('queued','running')"))
asyncio.run(main())
PYEOF
  )
  [ "${PENDIENTES:-0}" -eq 0 ] && break
  sleep 10
done

# Regeneración selectiva: wiki/grafo/dashboard solo si hubo documentos nuevos
# (ahorra LLM y no toca artefactos si nada cambió — el dedupe por hash decide).
if [ "${NOVEDADES:-0}" -eq 1 ]; then
  "${PY[@]}" src/kos/cli.py wiki >> "$LOG" 2>&1 || true
  "${PY[@]}" src/kos/cli.py graph --dir vault/04_GRAPH >> "$LOG" 2>&1 || true
  "${PY[@]}" scripts/dashboard_md.py >> "$LOG" 2>&1 || true
else
  echo "[autopilot $(date +%H:%M:%S)] sin novedades — wiki/grafo/dashboard intactos" >> "$LOG"
fi

if [ "$DO_BACKUP" -eq 1 ]; then
  "${PY[@]}" src/kos/cli.py backup >> "$LOG" 2>&1 || true
fi

echo "[autopilot $(date +%H:%M:%S)] OK — resumen:" >> "$LOG"
tail -4 "$LOG"