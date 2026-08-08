"""CLI del Knowledge OS — interfaz de operación (§42: make setup/ingest/query).

uso: kos <comando> [args]
comandos: setup, ingest <dir>, worker, query "<pregunta>", memory <observación>,
          wiki, graph, versions, dashboard, backup, restore
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # src en path

from kos import db, s3, qdrant  # noqa: E402
from kos.config import settings as cfg  # noqa: E402

log = logging.getLogger("kos.cli")


def _log() -> None:
    logging.basicConfig(level=getattr(logging, cfg.log_level, logging.INFO),
                        format="%(levelname)s %(name)s: %(message)s")


def cmd_setup(_) -> None:
    """Esquema PG + buckets MinIO + colección Qdrant + registro de versiones."""
    async def _run():
        await db.apply_schema()
        s3.ensure_bucket()
        qdrant.ensure_collection()
        for comp, name, ver in [
            ("llm_model", "ollama", "0.32.6"),
            ("llm_model", "qwen2.5:7b", "7b"),
            ("embedding_model", "bge-m3", "1.2GB"),
            ("parser", "pypdf", "4.x"),
            ("pipeline", "kos", "0.1.0"),
        ]:
            await db.record_version(comp, name, ver)
        print("setup OK: PG, buckets, colección, versiones")
    asyncio.run(_run())


def cmd_ingest(args) -> None:
    """Registra documentos de un directorio y encola su procesamiento."""
    from kos import pipeline, security

    async def _run():
        root = Path(args.dir)
        if not root.is_dir():
            raise SystemExit(f"no es directorio: {root}")
        workdir = cfg.data_dir / "staging"
        workdir.mkdir(parents=True, exist_ok=True)
        n = 0
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            try:
                security.validate_file(p)
            except Exception as exc:  # noqa: BLE001
                log.warning("omito %s: %s", p, exc)
                continue
            content = p.read_bytes()
            c_hash = hashlib.sha256(content).hexdigest()
            doc = {
                "path": str(p), "title": p.stem, "content_hash": c_hash,
                "mime_type": "application/octet-stream", "source_type": "documentation",
                "uri": None, "language": None,
            }
            if await pipeline.process_document(doc, workdir):
                n += 1
        print(f"ingest: {n} documentos nuevos encolados en {root}")
    asyncio.run(_run())


def cmd_worker(args) -> None:
    from kos import pipeline

    async def _run():
        await pipeline.worker_loop(args.worker_id or "w1", once=args.once)
    asyncio.run(_run())


def cmd_query(args) -> None:
    from kos import router

    async def _run():
        r = await router.answer(args.question, mode=args.mode)
        print(f"\n[{r['type_name']}] {r['answer']}\n")
        print(f"evidencia: {r['evidence_n']} chunks · {r['latency_ms']} ms")
    asyncio.run(_run())


def cmd_memory(args) -> None:
    from kos import memory

    async def _run():
        if args.observation:
            r = await memory.add(args.observation, source_session="cli")
            print(json.dumps(r, ensure_ascii=False, indent=2))
        else:
            rows = await db.query_memory(top=args.top or 20)
            for m in rows:
                print(f"[{m['memory_kind']} {float(m['importance']):.2f}] {m['content']}")
    asyncio.run(_run())


def cmd_wiki(_) -> None:
    """Compila páginas wiki por dominio (top chunks de cada fuente)."""
    from kos import wiki

    async def _run():
        docs = await db.get_documents(limit=50)
        built = 0
        for d in docs:
            chunks = await db.load_chunks(d["doc_id"])
            evidence = [{"chunk_id": c["chunk_id"], "doc_id": d["doc_id"], "text": c["content"]} for c in chunks[:12]]
            if not evidence:
                continue
            try:
                if await wiki.compile_page(f"{d['title']} — síntesis", evidence):
                    built += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("wiki %s: %s", d["title"], exc)
        wiki.index_wiki()
        print(f"wiki: {built} páginas nuevas (índice actualizado)")
    asyncio.run(_run())


def cmd_graph(args) -> None:
    from kos import graph

    async def _run():
        corpus = Path(args.dir or cfg.data_dir / "raw")
        cache = cfg.data_dir / "graphify-cache"
        G = await graph.build_graph(corpus, cache_root=cache)
        out = graph.vault_dir()
        reports = graph.export_graph(G, out)
        stats = graph.graph_stats(out / "graph.json")
        print(json.dumps({"stats": stats, "reports": reports}, indent=2))
    asyncio.run(_run())


def cmd_versions(_) -> None:
    async def _run():
        rows = await db.get_versions()
        for v in rows:
            print(f"{v['component']:<14} {v['name']:<24} {v['version']}  active={v['active']}")
    asyncio.run(_run())


def cmd_dashboard(_) -> None:
    async def _run():
        stats = await db.dashboard_stats()
        print(json.dumps(stats, indent=2))
    asyncio.run(_run())


def cmd_backup(args) -> None:
    """Backup completo: pg_dump + tar de vault/staging/lightrag (§34)."""
    import shutil
    import subprocess
    import tarfile
    from datetime import datetime

    dest = Path(args.dir or cfg.data_dir / "backups")
    dest.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = dest / f"kos_backup_{ts}"
    sql = base.with_suffix(".sql")
    env = {**__import__("os").environ, "PGPASSWORD": cfg.pg_password}
    subprocess.run(
        ["pg_dump", "-h", cfg.pg_host, "-p", str(cfg.pg_port), "-U", cfg.pg_user,
         "-d", cfg.pg_database, "--no-owner", "-f", str(sql)],
        env=env, check=True, capture_output=True,
    )
    tar = dest / f"kos_backup_{ts}.tar.gz"
    with tarfile.open(tar, "w:gz") as tf:
        for d in (cfg.data_dir / "staging", cfg.data_dir / "lightrag", cfg.vault_path):
            if d.exists():
                tf.add(d, arcname=d.name)
    print(f"backup OK: {sql} + {tar}")


def cmd_restore(args) -> None:
    """Restaura el SQL de Postgres (los volúmenes Docker se restauran con sus
    snapshots; los objetos MinIO son inmutables y se re-sincronizan)."""
    import subprocess

    sql = Path(args.file)
    if not sql.exists():
        raise SystemExit(f"no existe: {sql}")
    env = {**__import__("os").environ, "PGPASSWORD": cfg.pg_password}
    subprocess.run(
        ["psql", "-h", cfg.pg_host, "-p", str(cfg.pg_port), "-U", cfg.pg_user,
         "-d", cfg.pg_database, "-f", str(sql)],
        env=env, check=True, capture_output=True,
    )
    print(f"restore OK: {sql}")


def main() -> None:
    _log()
    ap = argparse.ArgumentParser(prog="kos", description="Hermes Knowledge OS")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    p_ingest = sub.add_parser("ingest"); p_ingest.add_argument("dir")
    p_worker = sub.add_parser("worker")
    p_worker.add_argument("--worker-id", default="w1")
    p_worker.add_argument("--once", action="store_true",
                          help="una ronda: termina al vaciar la cola actual (no hace polling)")
    p_query = sub.add_parser("query"); p_query.add_argument("question"); p_query.add_argument("--mode", default="hybrid")
    p_mem = sub.add_parser("memory"); p_mem.add_argument("observation", nargs="?"); p_mem.add_argument("--top", type=int)
    sub.add_parser("wiki")
    p_graph = sub.add_parser("graph"); p_graph.add_argument("--dir")
    sub.add_parser("versions")
    sub.add_parser("dashboard")
    p_backup = sub.add_parser("backup"); p_backup.add_argument("--dir")
    p_restore = sub.add_parser("restore"); p_restore.add_argument("file")

    args = ap.parse_args()
    fn = {"setup": cmd_setup, "ingest": cmd_ingest, "worker": cmd_worker,
          "query": cmd_query, "memory": cmd_memory, "wiki": cmd_wiki,
          "graph": cmd_graph, "versions": cmd_versions, "dashboard": cmd_dashboard,
          "backup": cmd_backup, "restore": cmd_restore}[args.cmd]
    fn(args)


if __name__ == "__main__":
    main()