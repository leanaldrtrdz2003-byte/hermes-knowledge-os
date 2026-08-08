#!/usr/bin/env python3
"""Regenera vault/00_SYSTEM/DASHBOARD.md con cifras reales del control plane.
uso: env -u PYTHONPATH .venv/bin/python scripts/dashboard_md.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kos import db  # noqa: E402

ROWS = (
    ("Fuentes (sources)", "SELECT COUNT(*) FROM sources"),
    ("Documentos", "SELECT COUNT(*) FROM documents"),
    ("Chunks", "SELECT COUNT(*) FROM chunks"),
    ("Chunks embebidos", "SELECT COUNT(*) FROM chunks WHERE has_embedding"),
    ("Entidades (grafo)", "SELECT COUNT(*) FROM entities"),
    ("Relaciones (grafo)", "SELECT COUNT(*) FROM relations"),
    ("Memorias de agente", "SELECT COUNT(*) FROM agent_memory"),
    ("Jobs done", "SELECT COUNT(*) FROM ingestion_jobs WHERE status='done'"),
    ("Jobs failed", "SELECT COUNT(*) FROM ingestion_jobs WHERE status='failed'"),
    ("Jobs queued", "SELECT COUNT(*) FROM ingestion_jobs WHERE status='queued'"),
    ("Llamadas LLM", "SELECT COUNT(*) FROM processing_costs"),
    ("Queries registradas", "SELECT COUNT(*) FROM queries_log"),
)


async def main() -> int:
    pool = await db.get_pool()
    lines = [
        "# DASHBOARD — Hermes Knowledge OS",
        "",
        f"> Regenerado el {__import__('datetime').datetime.now().date().isoformat()}.",
        "> `scripts/dashboard_md.py` · datos del control plane (PostgreSQL).",
        "",
        "| Métrica | Valor |",
        "|---|---|",
    ]
    for name, sql in ROWS:
        lines.append(f"| {name} | {await pool.fetchval(sql)} |")
    out = Path(__file__).resolve().parents[1] / "vault/00_SYSTEM/DASHBOARD.md"
    out.write_text("\n".join(lines) + "\n")
    print(f"OK: {out} ({len(lines) - 4} métricas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))