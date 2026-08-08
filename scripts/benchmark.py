"""Benchmark F10 — calidad y latencia de recuperación.

Compara 3 estrategias de recuperación sobre COSAS que el corpus ya conoce:
  naive  → solo búsqueda vectorial en Qdrant (lineal)
  local  → LightRAG local retrieval (fragmentos relevantes)
  hybrid → router del KOS: fiesta de contextos (RAG + grafo/vía) (§25)

uso: env -u PYTHONPATH .venv/bin/python scripts/benchmark.py [--questions N]

Salida: tabla Markdown → vault/00_SYSTEM/BENCHMARK.md
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kos import config, db, lightrag_engine as le, qdrant, router  # noqa: E402
from kos.embed import embed_texts  # noqa: E402

settings = config.settings

PREGUNTAS = [
    ("¿Qué es la entropía y qué mide?", "termodinámica"),
    ("¿Qué modelo añadió self-attention y cuándo se publicó?", "informática"),
    ("¿Para qué se usa la integral definida?", "matemáticas"),
    ("¿Qué tipos de datos básicos ofrece Python?", "programación"),
]


def _score_answers(answer: str, domain: str) -> tuple[float, int]:
    """Heurística simple: espera encontrar palabras del dominio en la respuesta."""
    lexicon = {
        "termodinámica": ["entropía", "energía", "calor", "microestado", "segunda ley", "desorden"],
        "informática": ["atención", "transformer", "neural", "query", "vector", "vaswani"],
        "matemáticas": ["área", "límite", "derivada", "riemann", "fundamental", "integral"],
        "programación": ["lista", "diccionario", "conjunto", "tupla", "mutable"],
    }
    hits = sum(1 for w in lexicon.get(domain, []) if w.lower() in answer.lower())
    return hits / max(len(lexicon.get(domain, [])), 1), hits


async def _retrieve_vectorial(question: str) -> tuple[float, str]:
    t0 = time.time()
    vec = await embed_texts([question])
    hits = qdrant.search(vec[0], top_k=5)
    # texto plano de los chunks recuperados (la puntuación va sobre él)
    text = "\n".join(str(h.get("body") or h.get("content") or "")[:600] for h in hits)
    return time.time() - t0, text


async def _retrieve_lightrag(question: str) -> tuple[float, str]:
    t0 = time.time()
    r = await le.query(question, mode="hybrid", top_k=5)
    return time.time() - t0, r.get("answer") or r.get("response") or ""


async def _retrieve_kos(question: str) -> tuple[float, str]:
    t0 = time.time()
    r = await router.answer(question, mode="hybrid")
    return time.time() - t0, r.get("answer") or r.get("response") or ""


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", type=int, default=len(PREGUNTAS))
    args = ap.parse_args()
    rows = []
    for q, domain in PREGUNTAS[: args.questions]:
        row = {"pregunta": q, "dominio": domain}
        for name, fn in (("qdrant", _retrieve_vectorial), ("lightrag", _retrieve_lightrag), ("kos_hybrid", _retrieve_kos)):
            try:
                dt, text = await fn(q)
                score, n = _score_answers(text, domain)
                row[name] = {"latencia_s": round(dt, 1), "lexico_hits": n, "score": score, "chars": len(text)}
            except Exception as exc:  # noqa: BLE001
                row[name] = {"error": str(exc)[:120]}
        rows.append(row)
        print(".", flush=True)
    out = {
        "generado": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "modelo": f"{settings.llm_model} + {settings.embedding_model}",
        "estrategias": ["vectorial(Qdrant)", "lightrag(hybrid)", "kos(router A-H)"],
        "resultados": rows,
    }
    dest = Path(__file__).resolve().parents[1] / "vault/00_SYSTEM/BENCHMARK.md"
    dest.write_text("```json\n" + json.dumps(out, ensure_ascii=False, indent=2) + "\n```\n")
    print(f"\nOK: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))