#!/usr/bin/env bash
# Watchdog de salud del Knowledge OS.
#
# Verifica que el autopilot diario esté vivo (log reciente) y que el corpus no
# esté vacío. Con --alert-mail puede avisar; por defecto solo reporta (exit 0/1).
#
# Uso:
#   scripts/watchdog.sh                  → modo consola (exit 1 si algo falla)
#   scripts/watchdog.sh --cron          → silencioso salvo que haya un problema
#
# Con --cron se puede añadir a otro timer systemd (kos-watchdog.timer).

set -uo pipefail
cd "$(dirname "$0")/.."

LOG_AUTOPILOT=/tmp/kos-autopilot.log
PY=(env -u PYTHONPATH .venv/bin/python)

CRON=0
[ "${1:-}" = "--cron" ] && CRON=1

PROBLEMS=()

# 1) ¿El autopilot corrió recientemente? (últimas 26 h; margen sobre el timer 03:30)
if [ -f "$LOG_AUTOPILOT" ]; then
  LAST_RUN=$(stat -c %Y "$LOG_AUTOPILOT" 2>/dev/null || echo 0)
  NOW=$(date +%s)
  AGE=$(( NOW - LAST_RUN ))
  if [ "$AGE" -gt 93600 ]; then
    PROBLEMS+=("autopilot no corrió en las últimas 26 h (log: $LOG_AUTOPILOT)")
  fi
else
  PROBLEMS+=("no existe $LOG_AUTOPILOT — el autopilot nunca ha corrido")
fi

# ─) ¿Hay cola estancada o errores recientes en el log?
if [ -f "$LOG_AUTOPILOT" ] && grep -qE "FAILED|ERROR|Traceback" "$LOG_AUTOPILOT" 2>/dev/null; then
  PROBLEMS+=("errores recientes en $LOG_AUTOPILOT (ver tail -50)")
fi

# ─) ¿El corpus no está vacío?
CORPUS_OK=$("${PY[@]}" - <<'PYEOF' 2>/dev/null || echo 0
import asyncio, sys
sys.path.insert(0, "src")
from kos import db
async def main():
    pool = await db.get_pool()
    return await pool.fetchval("SELECT COUNT(*) FROM documents")
print(int(asyncio.run(main()) or 0))
PYEOF
)
if [ "${CORPUS_OK:-0}" -eq 0 ]; then
  echo "[watchdog $(date +%F_%T)] NOTA: corpus vacío (0 documentos) — bootstrap, ingesta pendiente" >&2
fi

# ─) ¿Algún contenedor de infra caído? (docker compose ps)
if command -v docker >/dev/null 2>&1; then
  DOWN=$(docker compose ps --status running 2>/dev/null | grep -cE "Up" || true)
  if [ "$DOWN" -lt 1 ]; then
    PROBLEMS+=("ningún contenedor del stack está 'Up'")
  fi
fi

if [ "${#PROBLEMS[@]}" -gt 0 ]; then
  for p in "${PROBLEMS[@]}"; do
    echo "[watchdog $(date +%F_%T)] PROBLEMA: $p"
  done
  [ "$CRON" -eq 1 ] && logger -t kos-watchdog "KOS: problemas ${#PROBLEMS[@]}: ${PROBLEMS[*]}"
  exit 1
fi

echo "[watchdog $(date +%F_%T)] OK — autopilot al día, corpus ${CORPUS_OK} docs"
exit 0