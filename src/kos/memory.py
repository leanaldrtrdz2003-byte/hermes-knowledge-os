"""Memoria de agente (§12) — episódica, semántica, procedural, decisiones.

Pipeline: candidate → importance scoring → dedupe → validate → persist.
La memoria vive en PostgreSQL (agent_memory) y se sincroniza como notas
Markdown dentro del vault (05_MEMORY) para lectura humana en Obsidian.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from kos.config import settings
from kos.llm import extract_json

log = logging.getLogger("kos.memory")

KINDS = ("episodic", "semantic", "procedural", "decision")
IMPORTANCE_THRESHOLD = 0.55


def _slug(s: str) -> str:
    out = re.sub(r"[^a-z0-9áéíóúñü ]+", "", s.lower()).strip()
    return re.sub(r"\s+", "-", out)[:70] or "memoria"


def dedupe_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()[:200]


async def evaluate(observation: str) -> dict:
    """Valida y puntúa una memoria candidata con LLM local."""
    prompt = f"""Evalúa esta observación del agente. Responde SOLO JSON:
{{"tipo":"episodic|semantic|procedural|decision","importancia":0.0,"memoria":"texto condensado", "dedupe":"clave corta"}}
Reglas: importancia>=0.75 si es hecho de usuario, decisión de arquitectura o
procedimiento reutilizable; <0.3 si es ruido conversacional. 'memoria' debe ser
1-2 frases permanentes. 'dedupe' = clave estable para detectar duplicados.
OBSERVACIÓN: {observation}"""
    try:
        data = await extract_json(prompt)
    except Exception as exc:  # noqa: BLE001
        log.warning("fallo evaluando memoria: %s", exc)
        return {"tipo": "", "importancia": 0.0, "memoria": "", "dedupe": ""}
    try:
        importance = float(data.get("importancia", 0.0))
    except (TypeError, ValueError):
        importance = 0.0
    return {
        "tipo": data.get("tipo", ""),
        "importancia": importance,
        "memoria": data.get("memoria", observation)[:2000],
        "dedupe": data.get("dedupe", dedupe_key(observation)),
    }


async def add(observation: str, *, source_session: str | None = None) -> dict:
    """Pipeline completo de memoria para una observación."""
    from kos import db

    ev = await evaluate(observation)
    if ev["tipo"] not in KINDS or ev["importancia"] < IMPORTANCE_THRESHOLD:
        return {"saved": False, "reason": "sin importancia", "importancia": ev["importancia"]}
    row = await db.persist_memory(
        kind=ev["tipo"], text=ev["memoria"], importance=ev["importancia"],
        dedupe_key=ev["dedupe"], source_session=source_session,
    )
    if row is None:
        return {"saved": False, "reason": "duplicado", "importancia": ev["importancia"]}
    _write_note(ev["tipo"], row["memory_id"], ev["memoria"], ev["importancia"],
                ev["dedupe"], source_session)
    return {"saved": True, "memory_id": row["memory_id"], "tipo": ev["tipo"],
            "importancia": ev["importancia"]}


def _write_note(kind: str, memory_id: str, text: str, importance: float,
                dkey: str, source_session: str | None) -> Path:
    d = settings.vault_path / "05_MEMORY" / kind
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{_slug(text)}-{memory_id[:8]}.md"
    content = (
        "---\n"
        f"tipo: {kind}\n"
        f"importancia: {importance:.2f}\n"
        f"dedupe_key: {(dkey or '')[:120]}\n"
        f"session: {source_session or ''}\n"
        f"created: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n"
        "---\n\n"
        f"{text}\n"
    )
    p.write_text(content, encoding="utf-8")
    return p