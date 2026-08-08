"""Integración Graphify (§8) — Knowledge Graph estructural.

- Código: extracción AST determinista local (tree-sitter, 25 lenguajes).
- Docs: extracción de entidades/relaciones con LLM local (fragmento
  {nodes, edges} compatible con el schema de Graphify).
- Merge → NetworkX → cluster (Leiden) → export (graph.json, Obsidian vault,
  HTML/SVG, GRAPH_REPORT.md).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from graphify import extract as gx_extract
from graphify.build import build as gx_build
from graphify.cluster import cluster as gx_cluster
from graphify.export import to_json, to_obsidian, to_svg, to_html

from kos.config import settings
from kos.llm import complete

log = logging.getLogger("kos.graph")

EXTRACTION_SCHEMA = {
    "nodes": [{"id": str, "label": str, "source_file": str, "source_location": str}],
    "edges": [{"source": str, "target": str, "relation": str, "confidence": str}],
}


async def extract_code(corpus_dir: Path, cache_root: Path | None = None) -> dict:
    """Paso 1 — estructura de código (determinista, sin LLM)."""
    files = gx_extract.collect_files(corpus_dir)
    if not files:
        return {"nodes": [], "edges": []}
    extraction = gx_extract.extract(
        files, cache_root=cache_root, parallel=True, root=corpus_dir
    )
    log.info("graphify: %d nodos, %d edges (código)", len(extraction.get("nodes", [])), len(extraction.get("edges", [])))
    return extraction


async def extract_docs_llm(title: str, text: str) -> dict:
    """Paso 2 — entidades/relaciones de documentos vía LLM local (§22 cheap)."""
    sys_prompt = (
        "Eres un extractor de conocimiento. RESPUESTA: ÚNICAMENTE un objeto JSON "
        "válido, sin markdown, sin explicación, sin texto fuera del JSON."
    )
    prompt = f"""Extrae del documento siguiente entidades y relaciones como JSON.
    Devuelve SOLO JSON con este schema:
    {{"nodes":[{{"id":"id_unico","label":"nombre humano","source_file":"{title}","source_location":"L1"}}],
     "edges":[{{"source":"id_a","target":"id_b","relation":"prerequisite_of|requires|teaches|explains|example_of|application_of|contradicts|extends|related_to|part_of|uses","confidence":"EXTRACTED|INFERRED|AMBIGUOUS"}}]}}
    Reglas: ids estables tipo slug (p.ej. "calculo_integral"); max 25 nodos; solo relaciones con base en el texto.
    DOCUMENTO:
    {text}"""
    raw = await complete(prompt, system=sys_prompt, max_tokens=2000)
    frag = _parse_fragment(raw, title)
    return frag


def _parse_fragment(raw: str, title: str) -> dict:
    """Parseo tolerante del JSON del LLM; ante fallo devuelve fragmento vacío."""
    try:
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("sin JSON")
        data = json.loads(raw[start : end + 1])
        nodes = []
        for n in data.get("nodes", [])[:30]:
            nodes.append(
                {
                    "id": str(n.get("id", "")).strip() or "unknown",
                    "label": str(n.get("label", n.get("id", "")))[:200],
                    "source_file": str(n.get("source_file", title)),
                    "source_location": str(n.get("source_location", "L1")),
                }
            )
        edges = []
        for e in data.get("edges", [])[:60]:
            conf = str(e.get("confidence", "INFERRED")).upper()
            if conf not in {"EXTRACTED", "INFERRED", "AMBIGUOUS"}:
                conf = "INFERRED"
            edges.append(
                {
                    "source": str(e.get("source", "")),
                    "target": str(e.get("target", "")),
                    "relation": str(e.get("relation", "related_to"))[:80],
                    "confidence": conf,
                }
            )
        return {"nodes": nodes, "edges": edges}
    except Exception:  # noqa: BLE001
        log.warning("fragmento LLM no parseable para %s", title)
        return {"nodes": [], "edges": []}


async def build_graph(corpus_dir: Path, *, cache_root: Path | None = None,
                      doc_extractions: list[dict] | None = None) -> object:
    """Paso 3 — merge + grafo NetworkX."""
    extractions = []
    code = await extract_code(corpus_dir, cache_root)
    if code.get("nodes"):
        extractions.append(code)
    extractions.extend(doc_extractions or [])
    if not extractions:
        raise ValueError("sin extracciones")
    return gx_build(extractions, directed=False, dedup=True, root=str(corpus_dir))


def export_graph(G, out_dir: Path) -> dict:
    """Paso 4 — artefactos: graph.json, vault Obsidian, HTML/SVG, reporte."""
    out_dir.mkdir(parents=True, exist_ok=True)
    communities = gx_cluster(G)  # dict[int, list[str]]; G ya lleva atributo de comunidad
    to_json(G, communities, str(out_dir / "graph.json"))
    reports = {}
    try:
        to_obsidian(G, communities, str(out_dir))
        reports["obsidian"] = "ok"
    except Exception as exc:  # noqa: BLE001
        log.warning("export obsidian: %s", exc)
        reports["obsidian"] = str(exc)[:120]
    try:
        to_svg(G, communities, str(out_dir / "graph.svg"))
        to_html(G, communities, str(out_dir / "graph.html"))
        reports["viz"] = "ok"
    except Exception as exc:  # noqa: BLE001
        log.warning("export viz: %s", exc)
        reports["viz"] = str(exc)[:120]
    return reports


def graph_stats(graph_path: Path) -> dict:
    """Nodos/edges/comunidades para dashboard y validación."""
    data = json.loads(graph_path.read_text())
    nodes = data.get("nodes", [])
    edges = data.get("links", data.get("edges", []))
    communities = len({n.get("community", -1) for n in nodes if n.get("community") is not None})
    return {"nodes": len(nodes), "edges": len(edges), "communities": communities}


def vault_dir() -> Path:
    return settings.vault_path / "04_GRAPH" / "exports"