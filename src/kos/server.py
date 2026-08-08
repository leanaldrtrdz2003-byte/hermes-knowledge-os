#!/usr/bin/env python
"""Servidor HTTP del Knowledge OS — consultas sin CLI (Fase C).

Alternativa estable a ``subprocess`` para que agentes (Hermes, Claude, otros)
consulten el KOS por HTTP. API:

  GET  /health          → estado del sistema (docs, chunks, cola)
  GET  /stats           → métricas del dashboard
  POST /query           → cuerpo JSON {"question": "...", "mode": "hybrid"}
  GET  /               → índice humano (HTML mínimo)

Uso:
  .venv/bin/python src/kos/server.py --host 127.0.0.1 --port 8747

Sin dependencias externas: stdlib (http.server + asyncio).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Añade src/ al path (funciona desde cualquier cwd: repo root o python -m)
_SRC = Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

log = logging.getLogger("kos.server")

# Loop compartido: el hilo del servidor mantiene un event loop vivo y cada
# request programa su corrutina en él (run_coroutine_threadsafe).
LOOP: asyncio.AbstractEventLoop | None = None

# Memoria de sesión: session_id → lista de turnos {role, content}.
# Volátil (por proceso); la memoria a largo plazo vive en PG (agent_memory).
SESSIONS: dict[str, list[dict]] = {}
MAX_SESSION_TURNS = 20


def _session_history(session_id: str | None) -> list[dict]:
    if not session_id:
        return []
    return SESSIONS.setdefault(session_id, [])[-6:]


def _remember(session_id: str | None, user_q: str, answer: str) -> None:
    if not session_id:
        return
    turns = SESSIONS.setdefault(session_id, [])
    turns.append({"role": "user", "content": user_q})
    turns.append({"role": "assistant", "content": answer[:800]})
    if len(turns) > MAX_SESSION_TURNS:
        del turns[: len(turns) - MAX_SESSION_TURNS]


def _run(loop: asyncio.AbstractEventLoop | None, coro):
    """Ejecuta una corrutina en el loop compartido desde un hilo de request."""
    if loop is None:
        raise RuntimeError("loop no inicializado — llama a serve() primero")
    fut = asyncio.run_coroutine_threadsafe(coro, loop)
    return fut.result(timeout=600)


def _json(h, code: int, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    h.send_response(code)
    h.send_header("Content-Type", "application/json; charset=utf-8")
    h.send_header("Content-Length", str(len(body)))
    h.end_headers()
    h.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    server_version = "kos-server/1.0"

    # ── helpers ────────────────────────────────────────────────────────────
    def _read_body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        if n <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    # ── rutas ──────────────────────────────────────────────────────────────
    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            _json(self, 200, self._health())
        elif self.path == "/stats":
            _json(self, 200, self._stats())
        elif self.path in ("/", "/index.html"):
            _json(self, 200, {"service": "kos-server", "endpoints": ["/health", "/stats", "/query (POST)"]})
        else:
            _json(self, 404, {"error": "no encontrado", "path": self.path})

    def do_POST(self):  # noqa: N802
        if self.path == "/query":
            body = self._read_body()
            q = (body.get("question") or "").strip()
            if not q:
                _json(self, 400, {"error": "campo 'question' requerido"})
                return
            mode = str(body.get("mode") or "hybrid")
            sid = str(body.get("session_id") or "")[:64] or None
            try:
                from kos import router

                hist = _session_history(sid)
                res = _run(LOOP, router.answer(q, mode=mode, history=hist))
                _remember(sid, q, res.get("answer", ""))
                if sid:
                    res["session_id"] = sid
                _json(self, 200, res)
            except Exception as exc:  # noqa: BLE001
                log.exception("query falló: %s", exc)
                _json(self, 500, {"error": str(exc)[:300]})
            return
        _json(self, 404, {"error": "no encontrado", "path": self.path})

    # ── datos ──────────────────────────────────────────────────────────────
    def _health(self) -> dict:
        try:
            from kos import db

            async def _q():
                pool = await db.get_pool()
                docs = await pool.fetchval("SELECT COUNT(*) FROM documents")
                queue = await pool.fetchval(
                    "SELECT COUNT(*) FROM ingestion_jobs WHERE status IN ('queued','running')")
                return {"db": "ok", "documents": int(docs or 0), "queue": int(queue or 0)}

            st = _run(LOOP, _q())
            st.update({"server": "ok"})
            return st
        except Exception as exc:  # noqa: BLE001
            log.warning("health: %s", exc)
            return {"server": "ok", "db": f"error: {str(exc)[:120]}"}

    def _stats(self) -> dict:
        try:
            from kos import db

            async def _q() -> dict:
                return await db.dashboard_stats()

            return _run(LOOP, _q())
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)[:200]}

    def log_message(self, format, *args) -> None:  # noqa: A003
        log.info("%s %s", self.address_string(), format % args)


def serve(*, host: str, port: int) -> None:
    global LOOP
    LOOP = asyncio.new_event_loop()
    t = threading.Thread(target=LOOP.run_forever, daemon=True, name="kos-loop")
    t.start()

    httpd = ThreadingHTTPServer((host, port), Handler)
    log.info("kos-server escuchando en http://%s:%d (querías /health, POST /query)", host, port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        LOOP.call_soon_threadsafe(LOOP.stop)
        httpd.server_close()
        log.info("kos-server detenido")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(prog="kos-server", description="API HTTP del Knowledge OS")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8747)
    args = ap.parse_args()
    serve(host=args.host, port=args.port)


if __name__ == "__main__":
    main()