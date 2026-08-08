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

MAX_LLM_RETRIES = 2  # reintentos de extracción LLM antes de degradar a vacío

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
    """Paso 2 — entidades/relaciones de documentos vía LLM (§22 cheap).

    Con reintento: si el LLM devuelve JSON inválido o un fragmento inutilizable,
    se reintenta una vez indicando el error; al segundo fallo se degrada a un
    fragmento vacío (sin tumbar el pipeline).
    """
    sys_prompt = (
        "Eres un extractor de conocimiento. RESPUESTA: ÚNICAMENTE un objeto JSON "
        "válido, sin markdown, sin explicación, sin texto fuera del JSON."
    )
    prompt = f"""Extrae del documento siguiente entidades y relaciones como JSON.
    Devuelve SOLO JSON con este schema:
    {{"nodes":[{{"id":"id_unico","label":"nombre humano","source_file":"{title}","source_location":"L1"}}],
     "edges":[{{"source":"id_a","target":"id_b","relation":"prerequisite_of|requires|teaches|explains|example_of|application_of|contradicts|extends|related_to|part_of|uses","confidence":"EXTRACTED|INFERRED|AMBIGUOUS"}}]}}
    Reglas: ids estables tipo slug (p.ej. "calculo_integral"); max 25 nodos; solo relaciones con base en el texto; cada edge debe referenciar ids existentes en nodes.
    DOCUMENTO:
    {text}"""
    for attempt in range(1, MAX_LLM_RETRIES + 1):
        raw = await complete(prompt, system=sys_prompt, max_tokens=2000)
        frag, issues = _parse_fragment(raw, title)
        if frag is not None:
            return frag
        log.warning(
            "extract LLM inválido (intento %d/%d) para %s: %s",
            attempt, MAX_LLM_RETRIES, title, "; ".join(issues),
        )
        if attempt < MAX_LLM_RETRIES:
            prompt += (
                "\nAVISO: tu respuesta anterior NO era JSON válido o tenía "
                "edges sin nodos. Devuelve ÚNICAMENTE JSON válido según el schema "
                "y respeta los ids declarados en nodes."
            )
    return {"nodes": [], "edges": []}


def _parse_fragment(raw: str, title: str) -> tuple[dict | None, list[str]]:
    """Parseo tolerante del JSON del LLM.

    Devuelve ``(frag, errores)``: ``frag`` es ``None`` si el JSON es inválido o
    inutilizable (sin nodos), o el fragmento saneado con edges huérfanos
    descartados y límites aplicados.
    """
    errors: list[str] = []
    try:
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("sin objeto JSON")
        data = json.loads(raw[start : end + 1])
    except (ValueError, json.JSONDecodeError) as exc:
        errors.append(f"JSON inválido: {exc}")
        return None, errors

    seen_ids: set[str] = set()
    nodes = []
    for n in data.get("nodes", [])[:30]:
        nid = str(n.get("id", "")).strip()
        if not nid or nid == "unknown":
            errors.append("nodo sin id descartado")
            continue
        if nid in seen_ids:
            errors.append(f"nodo duplicado descartado: {nid}")
            continue
        seen_ids.add(nid)
        nodes.append(
            {
                "id": nid,
                "label": str(n.get("label", nid))[:200].strip() or nid,
                "source_file": str(n.get("source_file", title)),
                "source_location": str(n.get("source_location", "L1")),
            }
        )

    edges: list[dict] = []
    for e in data.get("edges", [])[:60]:
        src = str(e.get("source", "")).strip()
        tgt = str(e.get("target", "")).strip()
        if not src or not tgt:
            errors.append("edge sin source/target descartado")
            continue
        if src not in seen_ids or tgt not in seen_ids:
            errors.append(f"edge huérfano descartado: {src}->{tgt}")
            continue
        conf = str(e.get("confidence", "INFERRED")).upper()
        if conf not in {"EXTRACTED", "INFERRED", "AMBIGUOUS"}:
            conf = "INFERRED"
        edges.append(
            {
                "source": src,
                "target": tgt,
                "relation": str(e.get("relation", "related_to"))[:80],
                "confidence": conf,
            }
        )

    if not nodes:
        errors.append("0 nodos extraídos — fragmento inutilizable")
        return None, errors
    return {"nodes": nodes, "edges": edges}, errors


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
    """Paso 4 — artefactos: graph.json, vault Obsidian, HTML/SVG, reporte.

    Añade a cada nodo su ``domain`` (derivado de ``source_file`` relativo a
    data/raw — el primer nivel del path es la carpeta de dominio) y escribe
    un resumen por dominios ``domains.json``.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    communities = gx_cluster(G)  # dict[int, list[str]]; G ya lleva atributo de comunidad
    to_json(G, communities, str(out_dir / "graph.json"))
    _annotate_domains(out_dir / "graph.json")
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


def _annotate_domains(graph_file: Path) -> None:
    """Etiqueta cada nodo con su dominio (1er nivel de source_file relativo a raw)."""
    data = json.loads(graph_file.read_text())
    raw_root = settings.data_dir / "raw"
    domains: dict[str, int] = {}
    for n in data.get("nodes", []):
        sf = str(n.get("source_file", ""))
        rel = sf
        try:
            p = Path(sf)
            if p.is_absolute():
                # relativo a data/raw si cuelga de él; si no, relativo al repo
                try:
                    rel = str(p.relative_to(raw_root))
                except ValueError:
                    repo = Path(__file__).resolve().parents[2]
                    try:
                        rel = str(p.relative_to(repo))
                    except ValueError:
                        rel = p.name
        except (OSError, ValueError):
            rel = sf
        parts = rel.replace("\\", "/").split("/")
        domain = parts[0] if parts and parts[0] not in ("", ".") else "root"
        n["domain"] = domain
        domains[domain] = domains.get(domain, 0) + 1
    graph_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (graph_file.parent / "domains.json").write_text(
        json.dumps({"domains": dict(sorted(domains.items())), "total_nodes": len(data.get("nodes", []))},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("grafo anotado con %d dominios: %s", len(domains), list(domains))


def graph_stats(graph_path: Path) -> dict:
    """Nodos/edges/comunidades para dashboard y validación."""
    data = json.loads(graph_path.read_text())
    nodes = data.get("nodes", [])
    edges = data.get("links", data.get("edges", []))
    communities = len({n.get("community", -1) for n in nodes if n.get("community") is not None})
    return {"nodes": len(nodes), "edges": len(edges), "communities": communities}


def vault_dir() -> Path:
    return settings.vault_path / "04_GRAPH" / "exports"